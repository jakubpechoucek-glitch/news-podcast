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
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.feeds import FEEDS, ITEMS_PER_FEED, MARKET_TICKERS, MAX_ITEM_AGE_HOURS

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
EPISODES_DIR = DOCS / "episodes"
FEED_XML = DOCS / "feed.xml"

MAX_EPISODES_KEPT = 14
TARGET_WORDS = "850-1000"  # ~6-7 minutes spoken
MIN_WORDS = 800  # below this, ask Claude once to expand the draft
MODEL = "claude-opus-5"
BACKUP_MODEL = "claude-haiku-4-5"  # used only if the MODEL request fails
PHILIPPINES_WORDS = "140-160"  # ~1 minute
TTS_VOICE = "en-US-AndrewNeural"

PODCAST_TITLE = "Morning Briefing: Finance & Geopolitics"
PODCAST_DESC = (
    "A tight daily 6-7 minute briefing: markets, the Fed and BSP, big tech, "
    "a one-minute Philippines focus, and world news."
)
PODCAST_BASE_URL = os.environ.get("PODCAST_BASE_URL", "").rstrip("/")

# The listener is in Manila (UTC+8, no DST). The workflow runs at 22:00 UTC,
# which is already the next morning there, so dates must use Manila time.
LISTENER_TZ = datetime.timezone(datetime.timedelta(hours=8), "Asia/Manila")


def listener_today() -> datetime.date:
    return datetime.datetime.now(LISTENER_TZ).date()


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


def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _num(text):
    return float(str(text).replace(",", "").replace("%", "").strip())


def _yahoo_prices(symbol):
    data = json.loads(
        _http_get(
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{urllib.parse.quote(symbol)}?range=1mo&interval=1d"
        )
    )
    result = data["chart"]["result"][0]
    # A month of daily bars so thinly reported indices still have a prior
    # close; fall back to the quote metadata if they don't.
    closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    meta = result.get("meta", {})
    if len(closes) >= 2:
        return closes[-1], closes[-2]
    if meta.get("regularMarketPrice") and meta.get("previousClose"):
        return meta["regularMarketPrice"], meta["previousClose"]
    return None


def _cnbc_prices(symbol):
    data = json.loads(
        _http_get(
            "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
            f"?symbols={urllib.parse.quote(symbol)}&requestMethod=itv&noform=1"
            "&partnerId=2&fund=1&exthrs=1&output=json"
        )
    )
    quote = data["FormattedQuoteResult"]["FormattedQuote"][0]
    last = _num(quote["last"])
    # Prefer CNBC's own change figure; outside PSE trading hours (e.g. our 6am
    # run) previous_day_closing can equal last, which would read as "flat".
    try:
        change = _num(quote.get("change", ""))
    except ValueError:
        change = 0.0
    if change:
        return last, last - change
    prev = _num(quote["previous_day_closing"])
    return last, (prev if prev != last else None)


def _google_finance_prices(symbol):
    html = _http_get(f"https://www.google.com/finance/quote/{urllib.parse.quote(symbol)}")
    last = re.search(r'data-last-price="([\d.,]+)"', html) or re.search(
        r'class="YMlKec fxKbKc">[^\d]*([\d.,]+)<', html
    )
    prev = re.search(r'Previous close.*?class="P6K39c">[^\d]*([\d.,]+)<', html, re.S)
    if last and prev:
        return _num(last.group(1)), _num(prev.group(1))
    return None


QUOTE_SOURCES = {"yahoo": _yahoo_prices, "cnbc": _cnbc_prices, "gfin": _google_finance_prices}


def _fetch_quote_line(label, symbol):
    """symbol is "source:SYMBOL" (see QUOTE_SOURCES) or a bare Yahoo symbol."""
    source, sep, sym = symbol.partition(":")
    if not sep or source not in QUOTE_SOURCES:
        source, sym = "yahoo", symbol
    try:
        prices = QUOTE_SOURCES[source](sym)
        if not prices:
            print(f"[warn] not enough data for quote {symbol}", file=sys.stderr)
            return None
        last, prev = prices
        if prev is None:
            print(f"Quote {label}: {last:,.2f} via {symbol} (no daily change)")
            return f"- {label}: {last:,.2f} (latest close; daily change not available)"
        if sym == "^TNX":
            change = f"{(last - prev) * 100:+.0f} basis points"
        else:
            change = f"{(last - prev) / prev * 100:+.2f}%"
        print(f"Quote {label}: {last:,.2f} via {symbol}")
        return f"- {label}: {last:,.2f} ({change} vs prior close)"
    except Exception as exc:  # noqa: BLE001 - missing quotes shouldn't kill the run
        print(f"[warn] failed to fetch quote {symbol}: {exc}", file=sys.stderr)
        return None


def fetch_market_snapshot():
    """Latest close and daily % change per ticker, as prompt-ready lines."""
    lines = []
    for label, symbols in MARKET_TICKERS:
        if isinstance(symbols, str):
            symbols = (symbols,)
        for symbol in symbols:
            line = _fetch_quote_line(label, symbol)
            if line:
                lines.append(line)
                break
    return lines


def clean_for_speech(text: str) -> str:
    """Strip markdown the model sometimes emits despite instructions."""
    text = re.sub(r"^\s*#+\s*.*$", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ask_claude(client, messages):
    # Server-side fallbacks: if the model declines (e.g. a safety classifier
    # tripping on war/security headlines), the API re-runs the request on a
    # fallback model instead of returning an empty script.
    import anthropic

    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
            messages=messages,
        )
    except anthropic.APIStatusError as exc:
        # Don't lose the day's episode over a model/beta access problem.
        print(f"[warn] {MODEL} request failed ({exc}); using {BACKUP_MODEL}", file=sys.stderr)
        resp = client.messages.create(model=BACKUP_MODEL, max_tokens=4000, messages=messages)
    if resp.stop_reason == "refusal":
        raise SystemExit(f"Claude declined to write the script: {resp.stop_details}")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise SystemExit(f"Claude returned no script text (stop_reason={resp.stop_reason})")
    print(f"Script written by {resp.model}")
    return text


def build_script_with_claude(items, market_lines):
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)

    bullet_lines = "\n".join(f"- [{it['source']}] {it['title']} — {it['desc']}" for it in items)
    today = listener_today().strftime("%A, %B %d, %Y")

    market_block = (
        "\n".join(market_lines)
        if market_lines
        else "(unavailable today -- do NOT state index levels or percentages you can't see in the headlines)"
    )

    prompt = f"""You are writing the spoken script for a daily audio news briefing called
"{PODCAST_TITLE}". Today is {today}. The listener is based in the Philippines and wants a
tight, precise update: the key facts and the one-line "why it matters", no long background
or speculation. Total length: {TARGET_WORDS} words.

Market snapshot (latest closes):
{market_block}

Raw headlines and snippets from the last {MAX_ITEM_AGE_HOURS} hours:
{bullet_lines}

Structure the script in this order:
1. Greeting naming the day and date, then a one-sentence preview. Keep it short.
2. Markets (about 250-300 words): how the Dow, S&P 500 and Nasdaq closed, the US 10-year
   Treasury yield, and notable big-tech movers (Apple, Microsoft, Nvidia, Alphabet, Amazon,
   Meta, Tesla) with the reason if the headlines give one. Then central banks: the Federal
   Reserve and the Bangko Sentral ng Pilipinas (BSP) -- any rate decisions, signals from
   officials, or market expectations for their next moves. If there's no fresh Fed or BSP
   news, say so in one sentence rather than padding.
3. Philippines focus -- one minute, {PHILIPPINES_WORDS} words: the PSEi and peso if available,
   plus the two or three most important Philippine economic, business or political stories.
4. World and geopolitics (about 250-300 words): the three or four biggest stories, one or two
   sentences each, noting any market impact (e.g. oil).
5. A one-line sign-off.

Rules:
- Precise: numbers and facts first, no filler, no repeating yourself. Being precise does
  NOT mean being short -- hit every section's word target by covering more stories and
  giving each a sentence of "why it matters". The total MUST be {TARGET_WORDS} words.
- Round numbers for the ear: index levels to the nearest whole number ("the Dow closed at
  about 52,049"), percentages to one decimal ("up 2.3 percent"), yields to two decimals
  ("4.96 percent"), the peso to two decimals ("62.56 pesos to the dollar"). Write numbers
  as digits, never spelled out digit by digit.
- Only use facts present in the snapshot or headlines above; never invent figures.
- Output ONLY the spoken script as plain prose for a text-to-speech voice: no markdown,
  no headings, no asterisks, no bullet points, no stage directions. Use short spoken
  transitions like "Now to the Philippines." between sections.
"""

    messages = [{"role": "user", "content": prompt}]
    script = _ask_claude(client, messages)
    word_count = len(script.split())
    print(f"Draft script: {word_count} words")
    if word_count < MIN_WORDS:
        messages += [
            {"role": "assistant", "content": script},
            {
                "role": "user",
                "content": f"That's only {word_count} words; the target is {TARGET_WORDS}. "
                "Rewrite the full script to reach the target: add more market detail and "
                "more world stories from the headlines, keep the Philippines segment at "
                f"{PHILIPPINES_WORDS} words, and follow all the same rules. "
                "Output only the script.",
            },
        ]
        script = _ask_claude(client, messages)
        print(f"Expanded script: {len(script.split())} words")
    return clean_for_speech(script)


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


def load_existing_items(exclude_guid=None):
    """Existing feed items, minus any with exclude_guid (a same-day re-run)."""
    if not FEED_XML.exists():
        return []
    tree = ET.parse(FEED_XML)
    return [
        it
        for it in tree.getroot().findall(".//item")
        if exclude_guid is None or it.findtext("guid") != exclude_guid
    ]


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

    if os.environ.get("QUOTES_ONLY"):
        # Diagnostic mode: check market data sources without publishing anything.
        lines = fetch_market_snapshot()
        print("\n".join(lines))
        print(f"Got {len(lines)}/{len(MARKET_TICKERS)} quotes")
        return

    print("Fetching RSS feeds...")
    items = fetch_feed_items()
    print(f"Collected {len(items)} raw items from {len(FEEDS)} feeds")
    if not items:
        raise SystemExit("No news items collected -- aborting")

    print("Fetching market snapshot...")
    market_lines = fetch_market_snapshot()
    print(f"Got {len(market_lines)}/{len(MARKET_TICKERS)} quotes")

    print("Asking Claude to write today's script...")
    script_text = build_script_with_claude(items, market_lines)

    today_str = listener_today().isoformat()
    mp3_path = EPISODES_DIR / f"{today_str}.mp3"

    print("Synthesizing audio with edge-tts...")
    synthesize_audio(script_text, mp3_path)

    duration_s = get_duration_seconds(mp3_path)
    now = datetime.datetime.now(datetime.timezone.utc)

    new_item_fields = {
        "title": f"Briefing: {listener_today().strftime('%B %d, %Y')}",
        "description": script_text[:500] + ("..." if len(script_text) > 500 else ""),
        "pub_date": format_datetime(now),
        "guid": today_str,
        "audio_url": f"{PODCAST_BASE_URL}/episodes/{today_str}.mp3" if PODCAST_BASE_URL else f"episodes/{today_str}.mp3",
        "length_bytes": mp3_path.stat().st_size,
        "duration": format_duration(duration_s),
    }

    existing_items = load_existing_items(exclude_guid=today_str)
    rebuild_feed(new_item_fields, existing_items)
    prune_old_episodes(existing_items)

    print(f"Done. Episode: {mp3_path} ({duration_s}s, {mp3_path.stat().st_size} bytes)")
    print(f"Feed updated: {FEED_XML}")


if __name__ == "__main__":
    main()
