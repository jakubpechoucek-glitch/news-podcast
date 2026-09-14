"""Curated RSS sources for the morning finance/geopolitics briefing.

Add or remove feeds freely -- the pipeline treats every entry the same way.
Each tuple is (human label, RSS url). Labels show up in the prompt sent to
Claude, so keep them short and recognizable.
"""

FEEDS = [
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
    ("Guardian Economics", "https://www.theguardian.com/business/economics/rss"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("CNBC Economy", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("ECB Press", "https://www.ecb.europa.eu/rss/press.html"),
]

# Only consider items published within this many hours of the run.
MAX_ITEM_AGE_HOURS = 36

# How many items to pull from each feed before the LLM filters/prioritizes.
ITEMS_PER_FEED = 8
