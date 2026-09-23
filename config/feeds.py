"""Curated RSS sources for the morning finance/geopolitics briefing.

Add or remove feeds freely -- the pipeline treats every entry the same way.
Each tuple is (human label, RSS url). Labels show up in the prompt sent to
Claude, so keep them short and recognizable.
"""

FEEDS = [
    # World / geopolitics
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    # Markets, big tech, central banks
    ("BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
    ("CNBC Economy", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("CNBC Tech", "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("Fed news", "https://news.google.com/rss/search?q=%22Federal+Reserve%22+rates+when:2d&hl=en-US&gl=US&ceid=US:en"),
    # Philippines
    ("BSP news", "https://news.google.com/rss/search?q=%22Bangko+Sentral%22+OR+BSP+when:2d&hl=en-PH&gl=PH&ceid=PH:en"),
    # Inquirer and BusinessWorld block direct RSS fetches from CI (HTTP 403),
    # so pull their stories via Google News instead.
    ("Inquirer Business", "https://news.google.com/rss/search?q=site:business.inquirer.net+when:2d&hl=en-PH&gl=PH&ceid=PH:en"),
    ("BusinessWorld PH", "https://news.google.com/rss/search?q=site:bworldonline.com+when:2d&hl=en-PH&gl=PH&ceid=PH:en"),
    ("PSEi news", "https://news.google.com/rss/search?q=PSEi+stocks+when:2d&hl=en-PH&gl=PH&ceid=PH:en"),
    ("Philstar Business", "https://www.philstar.com/rss/business"),
    ("Philippines news", "https://news.google.com/rss/search?q=Philippines+when:1d&hl=en-PH&gl=PH&ceid=PH:en"),
]

# Only consider items published within this many hours of the run.
MAX_ITEM_AGE_HOURS = 36

# How many items to pull from each feed before the LLM filters/prioritizes.
ITEMS_PER_FEED = 8

# Market snapshot pulled from Yahoo Finance so the script quotes real numbers
# instead of guessing. (label, Yahoo symbol or tuple of fallback symbols tried
# in order). Failures are skipped.
MARKET_TICKERS = [
    ("Dow Jones", "^DJI"),
    ("S&P 500", "^GSPC"),
    ("Nasdaq Composite", "^IXIC"),
    ("US 10-year Treasury yield (%)", "^TNX"),
    ("PSEi (Philippine Stock Exchange index)", ("^PSEI", "PSEI.PS", "PSE.PS")),
    ("US dollar to Philippine peso", "PHP=X"),
    ("Apple", "AAPL"),
    ("Microsoft", "MSFT"),
    ("Nvidia", "NVDA"),
    ("Alphabet", "GOOGL"),
    ("Amazon", "AMZN"),
    ("Meta", "META"),
    ("Tesla", "TSLA"),
]
