#!/usr/bin/env python3
"""
Daily finance/geopolitics audio briefing.

Pipeline: RSS feeds -> Claude (script) -> edge-tts (audio) -> podcast RSS feed
(docs/feed.xml, served by GitHub Pages) so the episode shows up in any normal
podcast app as a new episode.

Requires:
    ANTHROPIC_API_KEY   env var (console.anthropic.com)
    PODCAST_BASE_URL    env var, e.g. https://<user>.github.io/<repo>
    edge-tts installed  (pip install edge-tts)

Run locally:
    ANTHROPIC_API_KEY=sk-... PODCAST_BASE_URL=https://you.github.io/news-podcast \
        python3 scripts/generate_episode.py
"""

import datetime
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.feeds import FEEDS, ITEMS_PER_FEED, MAX_ITEM_AGE_HOURS

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
EPISODES_DIR = DOCS / "episodes"
FEED_XML = DOCS / "feed.xml"

MAX_EPISODES_KEPT = 14
TARGET_WORDS = "1200-1400"  # ~8-10 minutes spoken
TTS_VOICE = "en-US-AndrewNeural"

PODCAST_TITLE = "Morning Briefing: Finance & Geopolitics"
PODCAST_DESC = "A daily 8-10 minute audio briefing on world finance and geopolitics."
PODCAST_BASE_URL = os.environ.get("PODCAST_BASE_URL", "").rstrip("/")


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_feed_items():
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        hours=MAX_ITEM_AGE_HOURS
    )
    collected = []
    for label, url in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            items = root.findall(".//item")[:ITEMS_PER_FEED]
            for it in items:
                title = strip_html(it.findtext("title"))
                desc = strip_html(it.findtext("description"))[:300]
                pub_raw = it.findtext("pubDate")
                try:
                    pub_dt = parsedate_to_datetime(pub_raw) if pub_raw else None
                    if pub_dt and pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
                except Exception:
                    pub_dt = None
                if pub_dt and pub_dt < cutoff:
                    continue
                if not title:
                    continue
                collected.append({"source": label, "title": title, "desc": desc})
        except Exception as exc:  # noqa: BLE001 - a single bad feed shouldn't kill the run
            print(f"[warn] failed to fetch {label} ({url}): {exc}", file=sys.stderr)
    return collected


def build_script_with_claude(items):
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)

    bullet_lines = "\n".join(f"- [{it['source']}] {it['title']} — {it['desc']}" for it in items)
    today = datetime.date.today().strftime("%A, %B %d, %Y")

    prompt = f"""You are writing the spoken script for a daily audio news briefing called
"{PODCAST_TITLE}". The listener has {TARGET_WORDS} words of listening time (about
8-10 minutes) on their commute. Today is {today}.

Below are raw headlines and snippets pulled from RSS feeds in the last {MAX_ITEM_AGE_HOURS} hours.
Select the most important finance and geopolitics stories, merge duplicates/related
items into single narrative threads, and explain WHY each story matters, not just what
happened. Connect related stories where it's genuinely illuminating (e.g. a conflict
driving an oil price move).

Raw items:
{bullet_lines}

Write ONLY the spoken script, as continuous prose meant to be read aloud by a
text-to-speech voice:
- Start with a short greeting that names the day/date.
- No markdown, no headers, no bullet points, no stage directions.
- Natural spoken sentences, contractions are fine.
- End with a short, warm sign-off.
- Target length: {TARGET_WORDS} words.
"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def synthesize_audio(script_text: str, out_path: Path):
    tmp_txt = out_path.with_suffix(".txt")
    tmp_txt.write_text(script_text, encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            TTS_VOICE,
            "--file",
            str(tmp_txt),
            "--write-media",
            str(out_path),
        ],
        check=True,
    )


def get_duration_seconds(mp3_path: Path) -> int:
    try:
        from mutagen.mp3 import MP3

        return int(MP3(str(mp3_path)).info.length)
    except Exception:
        return 0


def format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def load_existing_items():
    if not FEED_XML.exists():
        return []
    tree = ET.parse(FEED_XML)
    return tree.getroot().findall(".//item")


def rebuild_feed(new_item_fields, existing_item_elements):
    NS = {
        "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "atom": "http://www.w3.org/2005/Atom",
    }
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "link").text = PODCAST_BASE_URL or "https://example.com"
    ET.SubElement(channel, "description").text = PODCAST_DESC
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit").text = "false"
    if PODCAST_BASE_URL:
        ET.SubElement(
            channel,
            "{http://www.w3.org/2005/Atom}link",
            {"href": f"{PODCAST_BASE_URL}/feed.xml", "rel": "self", "type": "application/rss+xml"},
        )

    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = new_item_fields["title"]
    ET.SubElement(item, "description").text = new_item_fields["description"]
    ET.SubElement(item, "pubDate").text = new_item_fields["pub_date"]
    ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = new_item_fields["guid"]
    ET.SubElement(
        item,
        "enclosure",
        {
            "url": new_item_fields["audio_url"],
            "length": str(new_item_fields["length_bytes"]),
            "type": "audio/mpeg",
        },
    )
    ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration").text = new_item_fields[
        "duration"
    ]

    for old_item in existing_item_elements[: MAX_EPISODES_KEPT - 1]:
        channel.append(old_item)

    ET.ElementTree(rss).write(FEED_XML, encoding="utf-8", xml_declaration=True)


def prune_old_episodes(existing_item_elements):
    for old_item in existing_item_elements[MAX_EPISODES_KEPT - 1 :]:
        guid_el = old_item.find("guid")
        if guid_el is None or not guid_el.text:
            continue
        stale_mp3 = EPISODES_DIR / f"{guid_el.text}.mp3"
        stale_txt = EPISODES_DIR / f"{guid_el.text}.txt"
        stale_mp3.unlink(missing_ok=True)
        stale_txt.unlink(missing_ok=True)


def main():
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching RSS feeds...")
    items = fetch_feed_items()
    print(f"Collected {len(items)} raw items from {len(FEEDS)} feeds")
    if not items:
        raise SystemExit("No news items collected -- aborting")

    print("Asking Claude to write today's script...")
    script_text = build_script_with_claude(items)

    today_str = datetime.date.today().isoformat()
    mp3_path = EPISODES_DIR / f"{today_str}.mp3"

    print("Synthesizing audio with edge-tts...")
    synthesize_audio(script_text, mp3_path)

    duration_s = get_duration_seconds(mp3_path)
    now = datetime.datetime.now(datetime.timezone.utc)

    new_item_fields = {
        "title": f"Briefing: {datetime.date.today().strftime('%B %d, %Y')}",
        "description": script_text[:500] + ("..." if len(script_text) > 500 else ""),
        "pub_date": format_datetime(now),
        "guid": today_str,
        "audio_url": f"{PODCAST_BASE_URL}/episodes/{today_str}.mp3" if PODCAST_BASE_URL else f"episodes/{today_str}.mp3",
        "length_bytes": mp3_path.stat().st_size,
        "duration": format_duration(duration_s),
    }

    existing_items = load_existing_items()
    rebuild_feed(new_item_fields, existing_items)
    prune_old_episodes(existing_items)

    print(f"Done. Episode: {mp3_path} ({duration_s}s, {mp3_path.stat().st_size} bytes)")
    print(f"Feed updated: {FEED_XML}")


if __name__ == "__main__":
    main()
