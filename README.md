# Morning Briefing: Finance & Geopolitics

An automated daily ~6-7 minute audio news briefing (markets, Fed/BSP, big tech,
a one-minute Philippines focus, then world news), delivered as a private
podcast feed you subscribe to in any normal podcast app (Apple Podcasts,
Overcast, Pocket Casts, Spotify...).

## How it works

```
RSS feeds  --->  Claude (writes the script)  --->  edge-tts (voice)  --->  podcast RSS feed
(config/feeds.py)                                                          (docs/feed.xml, served by GitHub Pages)
```

A GitHub Actions workflow runs this every morning, commits the new mp3 +
updated feed.xml into `docs/`, and GitHub Pages serves that folder as a
website. Your podcast app just polls that feed URL like any other podcast.

## One-time setup

1. **Anthropic API key** — get one at https://console.anthropic.com, then add
   it as a repo secret: Settings -> Secrets and variables -> Actions -> New
   repository secret -> name `ANTHROPIC_API_KEY`.

2. **Enable GitHub Pages** — Settings -> Pages -> Build and deployment ->
   Source: "Deploy from a branch" -> Branch: `main`, folder: `/docs`.

3. **Run it once manually** — Actions tab -> "Daily Briefing" -> Run workflow.
   After it finishes, `docs/feed.xml` and `docs/episodes/*.mp3` will exist and
   Pages will start serving them at:
   `https://<your-username>.github.io/<repo-name>/feed.xml`

4. **Subscribe** — in your podcast app, use "Add by URL" / "Add a show by RSS
   feed" and paste that feed.xml URL. The episode shows up like any other
   podcast, with normal playback speed/resume/queue controls.

After that, it just runs on its own every morning (cron in
`.github/workflows/daily-briefing.yml`, currently set for 06:00 Asia/Manila).

## Run locally (for testing/tweaking)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
export PODCAST_BASE_URL=https://your-username.github.io/your-repo
python3 scripts/generate_episode.py
```

This writes `docs/episodes/<date>.mp3` and updates `docs/feed.xml` locally so
you can preview before pushing.

## Customizing

- **News sources**: edit `config/feeds.py` — just a list of (label, RSS url)
  tuples. Add Reuters/AP/IMF/Fed/whatever you like.
- **Length**: `TARGET_WORDS` / `PHILIPPINES_WORDS` in
  `scripts/generate_episode.py` (roughly 150 spoken words per minute).
- **Market numbers**: `MARKET_TICKERS` in `config/feeds.py` (Yahoo Finance
  symbols) -- indices, 10-year yield, PSEi, USD/PHP and big-tech stocks.
- **Voice**: `TTS_VOICE` in the same file. List all available voices with
  `edge-tts --list-voices`.
- **How many episodes to keep**: `MAX_EPISODES_KEPT` (older mp3s get deleted
  automatically to keep the repo small).

## Cost

- Claude Haiku: a few cents/day for one summarization call.
- edge-tts: free (Microsoft's neural voices, no API key needed).
- GitHub Actions + Pages: free for a public repo on the free tier.

Total: well under $1/month.

## Note on privacy

The repo (and therefore the audio files) needs to be **public** for free
GitHub Pages hosting. Nothing links to it from anywhere, but the URL isn't a
secret either -- don't put anything sensitive in the briefing content.
