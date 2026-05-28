"""
session_filter.py - Market Session Profile and Logic

Differentiates market behavior between Asian, London, and NY sessions
with specific characteristics for XAUUSD and EURUSD.
"""

from datetime import datetime
from typing import Dict, Optional, Union
import pandas as pd


def get_session_profile(
    latest_time: Union[datetime, pd.Timestamp, None], 
    symbol: str = "XAUUSD"
) -> Dict[str, str]:
    """
    Returns the session name and characteristics based on the provided timestamp.
    Time should ideally be UTC, but broker time can be used as a proxy if GMT offset is stable.
    """
    if latest_time is None:
        latest_time = datetime.utcnow()

    hour = latest_time.hour
    
    # 00:00 to 07:00 (Asia)
    if 0 <= hour < 7:
        if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
            return {
                "name": "Asia",
                "profile": "Stop-hunt and reversal prone (Fakeout). Very tight range. Avoid breakouts. Look for liquidity sweeps."
            }
        else: # EURUSD
            return {
                "name": "Asia",
                "profile": "Quiet, narrow range. Low volatility. Breakouts often fail. Scalping small ranges only."
            }
            
    # 07:00 to 12:00 (London)
    elif 7 <= hour < 12:
        if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
            return {
                "name": "London",
                "profile": "High momentum. Clean breakouts possible. Harmonics starting to work."
            }
        else:
            return {
                "name": "London",
                "profile": "Clean breakout trends. Best session for EURUSD early trend establishment."
            }
            
    # 12:00 to 16:00 (London / NY Overlap)
    elif 12 <= hour < 16:
        if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
            return {
                "name": "London/NY overlap",
                "profile": "Highest liquidity and momentum. Fast follow-through. Harmonics highly successful. Watch out for extreme news spikes."
            }
        else:
            return {
                "name": "London/NY overlap",
                "profile": "Highest liquidity. Excellent for scalping Inside Bars and Engulfings."
            }
            
    # 16:00 to 21:00 (NY)
    elif 16 <= hour < 21:
        if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
            return {
                "name": "NY",
                "profile": "High liquidity. News-driven reversals and continuations. Harmonics work well."
            }
        else:
            return {
                "name": "NY",
                "profile": "Trend continuation or reversal of London trend. Clean chart patterns."
            }
            
    # 21:00 to 24:00 (Off-hours)
    else:
        return {
            "name": "Off-hours",
            "profile": "Low liquidity. Spreads may widen. Prefer holding or managing existing positions only."
        }


def _latest_time(mdf: Dict[str, pd.DataFrame]) -> Optional[pd.Timestamp]:
    """Helper to extract the latest time from the lowest timeframe available."""
    for tf in ["M1", "M5", "M15", "H1", "H4"]:
        df = mdf.get(tf)
        if df is not None and not df.empty and "time" in df.columns:
            return pd.to_datetime(df["time"].iloc[-1], errors="coerce")
    return None

def detect_session(mdf: Dict[str, pd.DataFrame], symbol: str = "XAUUSD") -> Dict[str, str]:
    """Wrapper to estimate session from multi-timeframe dict."""
    return get_session_profile(_latest_time(mdf), symbol)
