import requests
import json
import os
import time
from datetime import datetime, timezone, timedelta
from loguru import logger

CACHE_FILE = "news_cache.json"
CACHE_EXPIRY = 3600  # 1 hour

def fetch_forexfactory_news():
    """Fetch JSON from ForexFactory via faireconomy media API."""
    now = time.time()
    
    # Return cached data if valid
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if now - data.get("timestamp", 0) < CACHE_EXPIRY:
                return data.get("events", [])
                
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            events = resp.json()
            # Cache the response
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"timestamp": now, "events": events}, f)
            return events
    except Exception as e:
        logger.error(f"Failed to fetch ForexFactory news: {e}")
        
    # Fallback to expired cache if request failed
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("events", [])
            
    return []

def is_high_impact_news_active(target_currencies=None, block_minutes_before=30, block_minutes_after=30):
    """
    Check if a high-impact (Red) news event is currently active or near for the target currencies.
    If target_currencies is None, defaults to ["USD", "ALL"].
    """
    if target_currencies is None:
        target_currencies = ["USD", "ALL"]
        
    events = fetch_forexfactory_news()
    if not events:
        return False
        
    current_time_utc = datetime.now(timezone.utc)
    
    for ev in events:
        impact = ev.get("impact", "").strip().title()
        country = ev.get("country", "").strip().upper()
        date_str = ev.get("date", "")
        
        # Only care about High impact
        if impact != "High":
            continue
            
        # Only care about target currencies
        if country not in target_currencies:
            continue
            
        # date_str format: "2026-06-08T08:30:00-04:00"
        try:
            # Parse ISO 8601 string to timezone-aware datetime
            ev_time = datetime.fromisoformat(date_str).astimezone(timezone.utc)
            
            # Calculate time difference in minutes
            diff_mins = (current_time_utc - ev_time).total_seconds() / 60.0
            
            # -30 means event is in 30 minutes. +30 means event was 30 mins ago.
            if -block_minutes_before <= diff_mins <= block_minutes_after:
                logger.warning(f"🚨 HIGH IMPACT NEWS: {ev.get('title')} ({country}) at {date_str}")
                return True
                
        except Exception as e:
            continue
            
    return False

if __name__ == "__main__":
    active = is_high_impact_news_active(["USD"], 30, 30)
    print("Is High Impact News Active?", active)
