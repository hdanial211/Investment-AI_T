"""
chart_capture.py - Automated Chart Screenshot Capture

Captures chart screenshots for vision AI analysis.
Two strategies:
  1. mt5_automation — Uses MT5 chart_shot() API (primary)
  2. matplotlib_fallback — Renders candlestick chart from OHLCV data

Screenshots are saved to a local folder and auto-cleaned after each cycle.
This folder is gitignored and never committed.
"""

import base64
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

# Try importing MT5 for chart_shot()
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

# Try importing matplotlib for fallback rendering
try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend for server/headless
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import FancyBboxPatch
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

# MT5 timeframe map (for chart_shot)
_TF_MAP = {}
if MT5_AVAILABLE:
    _TF_MAP = {
        "M1":  mt5.TIMEFRAME_M1,
        "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,
        "D1":  mt5.TIMEFRAME_D1,
    }


def _get_screenshot_dir() -> Path:
    """Get and create the screenshot output directory."""
    base_dir = Path(config.MT5_SCREENSHOT_DIR)
    if not base_dir.is_absolute():
        # Relative to Bot Engine directory
        base_dir = Path(__file__).parent / config.MT5_SCREENSHOT_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def capture_charts(
    symbol: str,
    connector,
    timeframes: List[str] = None,
) -> Dict[str, str]:
    """
    Capture chart screenshots for all configured timeframes.

    Returns:
        Dict mapping timeframe -> filepath for successful captures.
        Missing timeframes mean capture failed for that timeframe.
    """
    timeframes = timeframes or config.CHART_IMAGE_TIMEFRAMES
    source = config.CHART_IMAGE_SOURCE
    results: Dict[str, str] = {}

    screenshot_dir = _get_screenshot_dir()

    for tf in timeframes:
        tf = tf.strip().upper()
        filepath = None

        try:
            if source == "mt5_automation" and MT5_AVAILABLE:
                filepath = _capture_mt5_chart(symbol, tf, screenshot_dir)

            # Fallback to matplotlib if MT5 capture failed or source is not mt5
            if filepath is None and MATPLOTLIB_AVAILABLE:
                filepath = _capture_matplotlib_chart(
                    symbol, tf, screenshot_dir, connector
                )

            if filepath and validate_screenshot(filepath, symbol):
                results[tf] = filepath
                logger.debug(f"[{symbol}] Screenshot captured: {tf} -> {filepath}")
            else:
                logger.warning(f"[{symbol}] Screenshot failed/invalid for {tf}")

        except Exception as e:
            logger.warning(f"[{symbol}] Screenshot error for {tf}: {e}")

    if results:
        logger.info(
            f"[{symbol}] Captured {len(results)}/{len(timeframes)} screenshots"
        )
    else:
        logger.warning(f"[{symbol}] No screenshots captured. Vision AI will HOLD.")

    return results


def _capture_mt5_chart(
    symbol: str,
    timeframe: str,
    output_dir: Path,
) -> Optional[str]:
    """
    Capture chart using MT5's built-in screenshot functionality.

    Uses mt5.copy_rates_from_pos() data rendered with matplotlib since
    chart_shot() requires an open chart window which may not be available
    in headless/automated mode. This is the 'mt5_automation' mode that
    uses real MT5 data but renders locally.
    """
    if not MT5_AVAILABLE:
        return None

    tf_enum = _TF_MAP.get(timeframe)
    if tf_enum is None:
        logger.debug(f"Unsupported MT5 timeframe: {timeframe}")
        return None

    # Ensure symbol is visible
    mt5.symbol_select(symbol, True)

    # Get OHLCV data for rendering
    rates = mt5.copy_rates_from_pos(symbol, tf_enum, 0, 60)
    if rates is None or len(rates) == 0:
        logger.debug(f"No MT5 data for {symbol} {timeframe}")
        return None

    if not MATPLOTLIB_AVAILABLE:
        logger.debug("matplotlib not available for MT5 chart rendering")
        return None

    # Render using matplotlib
    return _render_candlestick(
        rates, symbol, timeframe, output_dir, source="mt5"
    )


def _capture_matplotlib_chart(
    symbol: str,
    timeframe: str,
    output_dir: Path,
    connector,
) -> Optional[str]:
    """
    Render a candlestick chart from OHLCV data fetched via connector.
    Used as fallback when MT5 chart_shot() is not available.
    """
    if not MATPLOTLIB_AVAILABLE:
        logger.debug("matplotlib not available for chart rendering")
        return None

    try:
        import pandas as pd
        df = connector.get_ohlcv(symbol, timeframe, bars=60)
        if df is None or df.empty:
            return None

        # Convert DataFrame to numpy structured array for rendering
        records = []
        for _, row in df.iterrows():
            ts = row["time"]
            if isinstance(ts, pd.Timestamp):
                ts = int(ts.timestamp())
            elif isinstance(ts, datetime):
                ts = int(ts.timestamp())
            records.append((
                ts,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                int(row.get("volume", 0) or 0),
            ))

        import numpy as np
        rates = np.array(
            records,
            dtype=[
                ("time", "i8"),
                ("open", "f8"),
                ("high", "f8"),
                ("low", "f8"),
                ("close", "f8"),
                ("tick_volume", "i8"),
            ],
        )

        return _render_candlestick(
            rates, symbol, timeframe, output_dir, source="mpl"
        )

    except Exception as e:
        logger.debug(f"Matplotlib chart capture failed: {e}")
        return None


def _render_candlestick(
    rates,
    symbol: str,
    timeframe: str,
    output_dir: Path,
    source: str = "mpl",
) -> Optional[str]:
    """Render candlestick chart from numpy structured array and save as PNG."""
    try:
        import numpy as np
        from datetime import datetime as dt

        times = [dt.fromtimestamp(int(r["time"])) for r in rates]
        opens = [float(r["open"]) for r in rates]
        highs = [float(r["high"]) for r in rates]
        lows = [float(r["low"]) for r in rates]
        closes = [float(r["close"]) for r in rates]
        volumes = [int(r["tick_volume"]) for r in rates]

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(12, 7), height_ratios=[3, 1],
            gridspec_kw={"hspace": 0.05},
        )

        # Dark theme
        fig.patch.set_facecolor("#1a1a2e")
        ax1.set_facecolor("#16213e")
        ax2.set_facecolor("#16213e")

        # Candlesticks
        width = 0.6
        x = np.arange(len(times))

        for i in range(len(times)):
            color = "#26a69a" if closes[i] >= opens[i] else "#ef5350"
            body_bottom = min(opens[i], closes[i])
            body_height = abs(closes[i] - opens[i])

            # Wick
            ax1.plot(
                [x[i], x[i]], [lows[i], highs[i]],
                color=color, linewidth=0.8,
            )
            # Body
            ax1.bar(
                x[i], body_height, bottom=body_bottom,
                width=width, color=color, edgecolor=color,
            )

        # EMA 9 and 21
        close_arr = np.array(closes)
        if len(close_arr) >= 21:
            ema9 = _ema(close_arr, 9)
            ema21 = _ema(close_arr, 21)
            ax1.plot(x, ema9, color="#ffd700", linewidth=1.2, alpha=0.8, label="EMA 9")
            ax1.plot(x, ema21, color="#4fc3f7", linewidth=1.2, alpha=0.8, label="EMA 21")

        # Price label
        last_price = closes[-1]
        ax1.axhline(y=last_price, color="#ffffff", linewidth=0.5, alpha=0.3, linestyle="--")

        # Volume bars
        vol_colors = [
            "#26a69a" if closes[i] >= opens[i] else "#ef5350"
            for i in range(len(volumes))
        ]
        ax2.bar(x, volumes, width=width, color=vol_colors, alpha=0.7)

        # Formatting
        ax1.set_title(
            f"{symbol} {timeframe}",
            color="#e0e0e0", fontsize=14, fontweight="bold", pad=10,
        )
        ax1.tick_params(colors="#9e9e9e", labelsize=8)
        ax1.yaxis.set_label_position("right")
        ax1.yaxis.tick_right()
        ax1.set_xlim(-1, len(x))
        ax1.grid(color="#2a3a5e", alpha=0.3)
        ax1.legend(loc="upper left", fontsize=8, facecolor="#1a1a2e", edgecolor="#444")

        ax2.tick_params(colors="#9e9e9e", labelsize=7)
        ax2.set_xlim(-1, len(x))
        ax2.grid(color="#2a3a5e", alpha=0.3)
        ax2.set_ylabel("Vol", color="#9e9e9e", fontsize=8)

        # X-axis labels (show every 10th candle)
        tick_positions = list(range(0, len(times), max(1, len(times) // 6)))
        ax2.set_xticks(tick_positions)
        ax2.set_xticklabels(
            [times[i].strftime("%H:%M\n%m/%d") for i in tick_positions],
            fontsize=7, color="#9e9e9e",
        )
        ax1.set_xticks([])

        # Timestamp watermark
        ax1.text(
            0.01, 0.97,
            f"Captured: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            transform=ax1.transAxes, fontsize=7, color="#666",
            va="top", ha="left",
        )

        # Save
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_{timeframe}_{timestamp}_{source}.png"
        filepath = str(output_dir / filename)
        fig.savefig(filepath, dpi=120, bbox_inches="tight", pad_inches=0.1)
        plt.close(fig)

        return filepath

    except Exception as e:
        logger.debug(f"Candlestick render failed: {e}")
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def _ema(data: "np.ndarray", period: int) -> "np.ndarray":
    """Calculate EMA over a numpy array."""
    import numpy as np
    result = np.zeros_like(data, dtype=float)
    result[0] = data[0]
    multiplier = 2.0 / (period + 1)
    for i in range(1, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def validate_screenshot(filepath: str, symbol: str) -> bool:
    """
    Validate a screenshot file:
    - File exists
    - File is non-zero size (at least 1KB for a valid PNG)
    - File is recent (within SCREENSHOT_MAX_AGE_SECONDS)
    """
    try:
        path = Path(filepath)
        if not path.exists():
            return False

        # Check minimum size (1KB)
        if path.stat().st_size < 1024:
            logger.debug(f"Screenshot too small: {filepath}")
            return False

        # Check age
        max_age = getattr(config, "SCREENSHOT_MAX_AGE_SECONDS", 120)
        file_age = time.time() - path.stat().st_mtime
        if file_age > max_age:
            logger.debug(f"Screenshot too old ({file_age:.0f}s): {filepath}")
            return False

        return True

    except Exception as e:
        logger.debug(f"Screenshot validation error: {e}")
        return False


def cleanup_old_screenshots(max_age_minutes: int = 30) -> None:
    """Delete screenshots older than max_age_minutes to prevent disk bloat."""
    try:
        screenshot_dir = _get_screenshot_dir()
        if not screenshot_dir.exists():
            return

        cutoff = time.time() - (max_age_minutes * 60)
        removed = 0

        for f in screenshot_dir.glob("*.png"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass

        if removed:
            logger.debug(f"Cleaned up {removed} old screenshot(s)")

    except Exception as e:
        logger.debug(f"Screenshot cleanup error: {e}")


def encode_image_base64(filepath: str) -> Optional[str]:
    """Read image file and return base64-encoded string for API calls."""
    try:
        with open(filepath, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.debug(f"Failed to encode image: {e}")
        return None
