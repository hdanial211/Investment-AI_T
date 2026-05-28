import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone

import config

logger = logging.getLogger(__name__)

# Constants
NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_FILE = os.path.join(config.LOG_DIR, "news_cache.json")
CACHE_EXPIRY_HOURS = 4
NEWS_BUFFER_MINUTES = 30  # Do not trade 30 mins before or after high impact news

def get_symbol_currencies(symbol: str) -> list:
    """Extract currencies from a symbol (e.g. XAUUSD -> ['XAU', 'USD'])."""
    s = symbol.upper().replace("C", "").replace(".PRO", "")
    if len(s) == 6:
        return [s[:3], s[3:]]
    elif "XAU" in s:
        return ["USD"] # Gold is mostly tied to USD news
    return ["USD"] # Default to USD if parsing fails

class NewsFilter:
    def __init__(self):
        self.events = []
        self._load_cache()

    def _load_cache(self):
        """Load from cache if it exists and is fresh; otherwise fetch."""
        os.makedirs(config.LOG_DIR, exist_ok=True)
        need_fetch = True
        
        if os.path.exists(CACHE_FILE):
            try:
                mtime = os.path.getmtime(CACHE_FILE)
                file_age = datetime.now() - datetime.fromtimestamp(mtime)
                if file_age < timedelta(hours=CACHE_EXPIRY_HOURS):
                    with open(CACHE_FILE, "r") as f:
                        self.events = json.load(f)
                        need_fetch = False
            except Exception as e:
                logger.warning(f"Failed to read news cache: {e}")

        if need_fetch:
            self.refresh_news()

    def refresh_news(self):
        """Fetch news from Forex Factory JSON."""
        try:
            req = urllib.request.Request(
                NEWS_URL,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                self.events = data
                with open(CACHE_FILE, "w") as f:
                    json.dump(self.events, f)
                logger.info("Successfully fetched and cached Forex Factory news.")
        except Exception as e:
            logger.error(f"Failed to fetch news: {e}")
            # If fetch fails, we retain whatever was in cache (if any)

    def is_safe_to_trade(self, symbol: str) -> tuple[bool, str]:
        """
        Check if there are any high-impact news events for the symbol's currencies
        within the NEWS_BUFFER_MINUTES window.
        Returns: (is_safe: bool, reason: str)
        """
        if not self.events:
            return True, ""

        now = datetime.now(timezone.utc)
        currencies = get_symbol_currencies(symbol)

        for event in self.events:
            impact = event.get("impact", "")
            country = event.get("country", "")
            
            if impact == "High" and country in currencies:
                date_str = event.get("date", "")
                if date_str:
                    try:
                        # e.g., "2026-05-28T08:30:00-04:00"
                        event_time = datetime.fromisoformat(date_str).astimezone(timezone.utc)
                        time_diff = abs((now - event_time).total_seconds()) / 60.0
                        
                        if time_diff <= NEWS_BUFFER_MINUTES:
                            msg = f"High impact news ({event.get('title')}) for {country} near this time."
                            return False, msg
                    except ValueError:
                        pass
                        
        return True, ""
