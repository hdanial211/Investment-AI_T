"""
master_analyzer.py - Market Signal Broadcaster

This is the "brain" of the system. It runs on a 10-minute loop:
1. Connect to MT5 (read-only, just for market data)
2. Fetch multi-timeframe OHLCV data for each symbol
3. Calculate indicators
4. Query Text AI + Vision AI for signal (BUY/SELL/HOLD + trade_style)
5. Broadcast the signal to Supabase `market_signals` table

Account Terminals read from `market_signals` to decide whether to trade.
This architecture saves API costs by only calling AI once per symbol per 10 mins.
"""

import logging
import signal
import os
import sys
import time
import uuid
import json
from datetime import datetime
from typing import Optional

import config
from mt5_connector import MT5Connector
from strategy import calculate_multi_indicators
from ai_engine import get_ai_signal, check_ai_health, merge_decisions
from chart_capture import capture_charts, cleanup_old_screenshots
from vision_engine import get_vision_signal
from trade_management.supabase_sync import SupabaseSync
import system_settings
from logger import setup_logging

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logger = setup_logging()

# ─────────────────────────────────────────────────────────────────────────────
# GRACEFUL SHUTDOWN
# ─────────────────────────────────────────────────────────────────────────────
_shutdown_requested = False

def _signal_handler(signum, frame):
    global _shutdown_requested
    logger.info("Shutdown signal received. Finishing current cycle...")
    _shutdown_requested = True

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ─────────────────────────────────────────────────────────────────────────────
# ANALYZE ONE SYMBOL
# ─────────────────────────────────────────────────────────────────────────────

def analyze_symbol(
    symbol: str,
    connector: MT5Connector,
    supabase: SupabaseSync,
    cycle_count: int,
) -> Optional[dict]:
    """Analyze a single symbol and broadcast signal to Supabase."""
    logger.info(f"{'─'*50}")
    logger.info(f"▶ Analyzing: {symbol} | {datetime.now().strftime('%H:%M:%S')}")

    # 1. Get tick data
    tick = connector.get_tick(symbol)
    if not tick:
        logger.error(f"Failed to get tick for {symbol}")
        return None

    bid = tick["bid"]
    ask = tick["ask"]
    logger.info(f"Tick: Bid={bid:.5f} | Ask={ask:.5f}")

    # 2. Get Multi-Timeframe data + indicators
    mdf = connector.get_multi_timeframe(
        symbol, timeframes=["H4", "H1", "M30", "M15", "M5", "M1"], bars=100
    )
    if not mdf or len(mdf) < 4:
        logger.error(f"Failed to get multi-timeframe data for {symbol}")
        return None

    indicators = calculate_multi_indicators(mdf, symbol=symbol)
    if not indicators:
        logger.warning(f"Cannot calculate indicators for {symbol}")
        return None

    # 3. Chart screenshot capture (if vision AI enabled)
    chart_paths = {}
    if config.VISION_AI_ENABLED:
        try:
            chart_paths = capture_charts(symbol, connector, config.CHART_IMAGE_TIMEFRAMES)
            cleanup_old_screenshots(max_age_minutes=30)
        except Exception as e:
            logger.warning(f"[{symbol}] Chart capture failed: {e}. Vision AI will HOLD.")

    # 4. Query Text AI
    logger.info("Querying text AI model...")
    master_ai_config = None
    if config.PROVIDERS_CONFIG and len(config.PROVIDERS_CONFIG) > 0:
        master_ai_config = config.PROVIDERS_CONFIG[0]
    elif config.MASTER_AI_PROVIDER:
        master_ai_config = {
            "provider": config.MASTER_AI_PROVIDER,
            "main_model": config.MASTER_AI_MAIN_MODEL,
            "risk_model": config.MASTER_AI_RISK_MODEL,
        }
        # In case it's huggingface/openrouter, fetch global api keys
        if config.MASTER_AI_PROVIDER.lower() in ("huggingface", "hf"):
            master_ai_config["api_key"] = config.HF_TOKEN
        elif config.MASTER_AI_PROVIDER.lower() in ("openrouter", "or"):
            master_ai_config["api_key"] = config.OPENROUTER_API_KEY
            
    text_signal = get_ai_signal(
        indicators, bid, ask, trade_memory=None, symbol=symbol, 
        specific_provider_config=master_ai_config
    )

    # 5. Query Vision AI + Merge (if enabled)
    if config.VISION_AI_ENABLED and chart_paths:
        logger.info("Querying vision AI model...")
        vision_signal = get_vision_signal(
            symbol=symbol,
            current_price=(bid + ask) / 2,
            indicators=indicators,
            chart_paths=chart_paths,
            trade_memory=None,
        )
        pattern_bias = indicators.get("pattern_bias") or {}
        final_signal = merge_decisions(text_signal, vision_signal, pattern_bias)
    else:
        final_signal = text_signal

    # 6. Broadcast to Supabase
    signal_id = str(uuid.uuid4())[:8]
    signal_data = {
        "symbol": symbol,
        "action": final_signal.get("action", "HOLD"),
        "confidence": final_signal.get("confidence", 0.0),
        "trade_style": final_signal.get("trade_style", "INTRADAY"),
        "reason": final_signal.get("reason", ""),
        "market_regime": indicators.get("market_regime", "RANGING"),
        "indicators_snapshot": {
            "h4_trend": indicators.get("h4_trend"),
            "h1_macd_trend": indicators.get("h1_macd_trend"),
            "m15_rsi": indicators.get("m15_rsi"),
            "adx": indicators.get("adx"),
            "atr": indicators.get("atr"),
            "detected_patterns": [
                {
                    "name": p.get("name"),
                    "timeframe": p.get("timeframe"),
                    "direction": p.get("direction"),
                    "confidence": p.get("confidence"),
                }
                for p in (indicators.get("detected_patterns") or [])[:8]
            ],
        },
        "vision_bias": final_signal.get("image_bias"),
        "bid": bid,
        "ask": ask,
        "atr": indicators.get("atr"),
        "signal_id": signal_id,
    }

    supabase.upsert_market_signal(signal_data)

    logger.info(
        f"✅ Signal broadcasted: {final_signal['action']} | "
        f"Style: {final_signal.get('trade_style')} | "
        f"Confidence: {final_signal.get('confidence', 0):.2f} | "
        f"ID: {signal_id}"
    )
    return signal_data


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

ANALYSIS_INTERVAL = 600  # 10 minutes

def main():
    global _shutdown_requested

    logger.info("=" * 60)
    logger.info("  MASTER ANALYZER — AI Market Signal Broadcaster")
    logger.info("=" * 60)

    connector = MT5Connector()
    supabase = SupabaseSync()

    # Ensure log directory exists
    os.makedirs(config.LOG_DIR, exist_ok=True)
    
    # Track accounts for symbol collection
    from account_settings import AccountSettings, get_all_enabled_accounts

    cycle_count = 0

    while not _shutdown_requested:
        cycle_count += 1
        logger.info(f"\n{'═'*60}")
        logger.info(f"MASTER CYCLE #{cycle_count} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'═'*60}")

        # 0. Refresh system settings (API keys, models)
        system_settings.fetch_and_apply_system_settings()

        # 1. MT5 connection config for Master Analyzer
        login_val = None
        password_val = None
        server_val = None
        path_val = None
        
        if config.MASTER_MT5_LOGIN and config.MASTER_MT5_LOGIN != "":
            try:
                login_val = int(config.MASTER_MT5_LOGIN)
                password_val = config.MASTER_MT5_PASSWORD
                server_val = config.MASTER_MT5_SERVER
                path_val = config.MASTER_MT5_PATH
            except ValueError:
                pass

        # 2. AI Health check on first cycle
        if cycle_count == 1:
            logger.info(f"Checking cloud AI ({config.MASTER_AI_PROVIDER} / {config.MASTER_AI_MAIN_MODEL})...")
            if check_ai_health(role="main"):
                logger.info("✔ Cloud AI main model ready")
            else:
                logger.warning("⚠ Cloud AI not ready — signals may fail")

        # 3. Connect to MT5 for market data
        mt5_connected = connector.connect(
            login=login_val, password=password_val,
            server=server_val, path=path_val,
        )
        if not mt5_connected:
            logger.warning("MT5 connection failed for market data. Retrying in 30s...")
            time.sleep(30)
            continue

        # 4. Determine all unique symbols across all accounts
        accounts = get_all_enabled_accounts()
        all_symbols = set()
        for acc_id in accounts:
            acc = AccountSettings(acc_id)
            for sym in acc.get_symbols():
                all_symbols.add(sym)

        logger.info(f"Symbols to analyze: {list(all_symbols)}")

        # 5. Analyze each symbol
        cycle_signals = {}
        for symbol in all_symbols:
            if _shutdown_requested:
                break
            try:
                sig_data = analyze_symbol(symbol, connector, supabase, cycle_count)
                if sig_data:
                    cycle_signals[symbol] = sig_data
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)

        # Broadcast all signals to local JSON for Watchdog to trigger Entry Terminals
        if cycle_signals:
            try:
                sig_file = os.path.join(config.LOG_DIR, "latest_signals.json")
                with open(sig_file, "w") as f:
                    json.dump(cycle_signals, f, indent=4)
                logger.info(f"✅ Local trigger updated: latest_signals.json")
            except Exception as e:
                logger.error(f"Failed to write latest_signals.json: {e}")

        # 6. Disconnect MT5 to free it for Account Terminals
        connector.disconnect()

        # 7. Unload AI from memory if local models were used
        # Construct the specific provider config for Master Analyzer
        from ai_engine import unload_ai
        
        master_ai_config = None
        if config.PROVIDERS_CONFIG and len(config.PROVIDERS_CONFIG) > 0:
            master_ai_config = config.PROVIDERS_CONFIG[0]
        elif config.MASTER_AI_PROVIDER:
            master_ai_config = {
                "provider": config.MASTER_AI_PROVIDER,
                "main_model": config.MASTER_AI_MAIN_MODEL,
                "risk_model": config.MASTER_AI_RISK_MODEL,
                "api_key": config.HF_TOKEN if config.MASTER_AI_PROVIDER.lower() in ("hf", "huggingface") else config.OPENROUTER_API_KEY
            }
        if master_ai_config:
            unload_ai(provider_sequence=[master_ai_config])
        else:
            unload_ai()

        # 7. Sleep until next analysis cycle
        if not _shutdown_requested:
            logger.info(f"Next analysis in {ANALYSIS_INTERVAL}s ({ANALYSIS_INTERVAL // 60} min)...")
            # Sleep in small chunks so shutdown is responsive
            current_provider = config.MASTER_AI_PROVIDER
            
            for i in range(ANALYSIS_INTERVAL):
                if _shutdown_requested:
                    break
                    
                # Check for settings changes every 60 seconds so we respond quickly to dashboard updates
                if i > 0 and i % 60 == 0:
                    system_settings.fetch_and_apply_system_settings()
                    if config.MASTER_AI_PROVIDER != current_provider:
                        logger.info(f"🔄 AI Provider changed from {current_provider} to {config.MASTER_AI_PROVIDER}! Restarting analysis cycle immediately...")
                        break
                        
                time.sleep(1)

    logger.info("\n" + "=" * 60)
    logger.info("MASTER ANALYZER SHUTTING DOWN")
    logger.info("=" * 60)
    connector.disconnect()


if __name__ == "__main__":
    main()
