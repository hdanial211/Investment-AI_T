"""
master_analyzer.py - Market Signal Broadcaster & Active Trade Evaluator

This is the "brain" of the system. It runs on a 10-minute loop:
1. Connect to MT5 (read-only, just for market data) — stays connected 24/7
2. Fetch multi-timeframe OHLCV data for each symbol
3. Calculate indicators
4. Query Text AI + Vision AI for signal (BUY/SELL/HOLD + trade_style)
5. Broadcast the signal to Supabase `market_signals` table
6. Write OPEN_TRADE commands to `trade_commands` for each enabled account
7. Every 20 min: Evaluate active trades and write CLOSE/UPDATE commands

Executor bots read from `trade_commands` to execute trades.
"""

import logging
import signal
import os
import sys
import time
import uuid
import json
from datetime import datetime
from typing import Optional, Dict, List

import config
from mt5_connector import MT5Connector
from strategy import calculate_multi_indicators
from ai_engine import get_ai_signal, check_ai_health, merge_decisions
from chart_capture import capture_charts, cleanup_old_screenshots
from vision_engine import get_vision_signal
from trade_management.supabase_sync import SupabaseSync
from account_settings import get_all_enabled_accounts
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
# BROADCAST COMMANDS TO ALL ACCOUNTS
# ─────────────────────────────────────────────────────────────────────────────

def broadcast_commands_to_accounts(
    signal_data: dict,
    supabase: SupabaseSync,
    enabled_accounts: List[str],
) -> None:
    """Write OPEN_TRADE commands to trade_commands for each enabled account."""
    action = signal_data.get("action", "HOLD")
    if action == "HOLD":
        return  # No trade needed

    symbol = signal_data.get("symbol")
    signal_id = signal_data.get("signal_id", "")

    payload = {
        "action": action,
        "confidence": signal_data.get("confidence", 0.0),
        "trade_style": signal_data.get("trade_style", "INTRADAY"),
        "reason": signal_data.get("reason", ""),
        "market_regime": signal_data.get("market_regime", "RANGING"),
        "bid": signal_data.get("bid"),
        "ask": signal_data.get("ask"),
        "atr": signal_data.get("atr"),
        "adx": (signal_data.get("indicators_snapshot") or {}).get("adx"),
        "m15_rsi": (signal_data.get("indicators_snapshot") or {}).get("m15_rsi"),
        "h4_trend": (signal_data.get("indicators_snapshot") or {}).get("h4_trend"),
        "h1_macd_trend": (signal_data.get("indicators_snapshot") or {}).get("h1_macd_trend"),
        "detected_patterns": (signal_data.get("indicators_snapshot") or {}).get("detected_patterns", []),
    }

    for acc_id in enabled_accounts:
        if acc_id == "master":
            continue  # Master doesn't trade
        supabase.insert_trade_command(
            account_id=acc_id,
            command_type="OPEN_TRADE",
            symbol=symbol,
            payload=payload,
            signal_id=signal_id,
        )
    logger.info(f"📤 OPEN_TRADE command sent to {len([a for a in enabled_accounts if a != 'master'])} account(s)")


# ─────────────────────────────────────────────────────────────────────────────
# AI EVAL: Evaluate active trades every 20 minutes
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_active_trades(
    supabase: SupabaseSync,
    connector: MT5Connector,
    enabled_accounts: List[str],
) -> None:
    """Query AI for each active trade: HOLD, CLOSE, or UPDATE_SL_TP."""
    logger.info("🧠 AI Trade Evaluation: Checking all active trades...")

    # Build AI config
    master_ai_config = None
    if config.PROVIDERS_CONFIG and len(config.PROVIDERS_CONFIG) > 0:
        master_ai_config = config.PROVIDERS_CONFIG[0]
    elif config.MASTER_AI_PROVIDER:
        master_ai_config = {
            "provider": config.MASTER_AI_PROVIDER,
            "main_model": config.MASTER_AI_MAIN_MODEL,
            "risk_model": config.MASTER_AI_RISK_MODEL,
        }

    evaluated = 0
    commands_sent = 0

    for acc_id in enabled_accounts:
        if acc_id == "master":
            continue

        try:
            trades = supabase.fetch_active_trades(acc_id)
            if not trades:
                continue

            for trade in trades:
                ticket = trade.get("ticket")
                symbol = trade.get("symbol", "")
                action_dir = trade.get("action") or trade.get("direction", "")
                entry_price = float(trade.get("entry_price") or 0)
                current_price = float(trade.get("price_current") or 0)
                profit = float(trade.get("unrealized_profit") or trade.get("profit") or 0)
                virtual_sl = trade.get("virtual_sl")
                virtual_tp = trade.get("virtual_tp")
                trade_style = trade.get("trade_style", "INTRADAY")

                if not ticket or not symbol:
                    continue

                # Get fresh market data for this symbol
                tick = connector.get_tick(symbol)
                if tick:
                    current_price = tick["bid"] if action_dir == "BUY" else tick["ask"]

                # Build prompt for AI
                trade_summary = (
                    f"Active trade #{ticket} on {symbol}: "
                    f"Direction={action_dir}, Entry={entry_price:.5f}, "
                    f"Current={current_price:.5f}, Profit={profit:.2f}, "
                    f"Style={trade_style}, SL={virtual_sl}, TP={virtual_tp}"
                )

                try:
                    from ai_engine import get_ai_signal
                    eval_result = get_ai_signal(
                        indicators={"trade_eval": trade_summary, "atr": trade.get("atr", 0)},
                        bid=current_price if action_dir == "BUY" else 0,
                        ask=current_price if action_dir == "SELL" else 0,
                        trade_memory=None,
                        symbol=symbol,
                        specific_provider_config=master_ai_config,
                        trade_eval_mode=True,
                    )
                    evaluated += 1

                    ai_action = eval_result.get("action", "HOLD")

                    if ai_action == "CLOSE_TRADE":
                        supabase.insert_trade_command(
                            account_id=acc_id,
                            command_type="CLOSE_TRADE",
                            symbol=symbol,
                            payload={"ticket": ticket, "reason": eval_result.get("reason", "ai_eval_close")},
                        )
                        commands_sent += 1
                        logger.info(f"🔴 AI says CLOSE trade #{ticket} ({symbol}): {eval_result.get('reason')}")

                    elif ai_action == "UPDATE_SL_TP":
                        new_sl = eval_result.get("sl")
                        new_tp = eval_result.get("tp")
                        supabase.insert_trade_command(
                            account_id=acc_id,
                            command_type="UPDATE_SL_TP",
                            symbol=symbol,
                            payload={
                                "ticket": ticket,
                                "sl": new_sl,
                                "tp": new_tp,
                                "reason": eval_result.get("reason", "ai_eval_update"),
                            },
                        )
                        commands_sent += 1
                        logger.info(f"🟡 AI says UPDATE trade #{ticket}: SL={new_sl}, TP={new_tp}")
                    else:
                        logger.debug(f"🟢 AI says HOLD trade #{ticket} ({symbol})")

                except Exception as e:
                    logger.warning(f"AI eval failed for trade #{ticket}: {e}")

        except Exception as e:
            logger.error(f"evaluate_active_trades error for {acc_id}: {e}")

    logger.info(f"🧠 AI Evaluation complete: {evaluated} trades evaluated, {commands_sent} commands sent.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

ANALYSIS_INTERVAL = 600  # 10 minutes
TRADE_EVAL_INTERVAL = 1200  # 20 minutes

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
    from account_settings import AccountSettings

    cycle_count = 0
    last_trade_eval = 0  # Track when we last evaluated active trades

    while not _shutdown_requested:
        cycle_count += 1
        logger.info(f"\n{'═'*60}")
        logger.info(f"MASTER CYCLE #{cycle_count} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'═'*60}")

        # 0. Refresh system settings (API keys, models)
        system_settings.fetch_and_apply_system_settings()

        # 1. Fetch Master Settings from Supabase
        account_settings = AccountSettings("master")
        account_settings.force_refresh()

        # 2. AI Health check on first cycle
        if cycle_count == 1:
            logger.info(f"Checking cloud AI ({config.MASTER_AI_PROVIDER} / {config.MASTER_AI_MAIN_MODEL})...")
            if check_ai_health(role="main"):
                logger.info("✔ Cloud AI main model ready")
            else:
                logger.warning("⚠ Cloud AI not ready — signals may fail")

        # 3. Override broker connection with Master config
        mt5_login = str(account_settings.mt5_login).strip()
        mt5_pwd = account_settings.mt5_password
        mt5_server = str(account_settings.mt5_server).strip()
        mt5_path = str(account_settings.mt5_path).strip()

        logger.info(f"Connecting to Master MT5 Terminal: Login={mt5_login}, Server={mt5_server}")
        if not connector.connect(
            login=int(mt5_login) if mt5_login else 0,
            password=mt5_pwd,
            server=mt5_server,
            path=mt5_path if mt5_path else config.MT5_PATH
        ):
            logger.error("❌ Failed to connect to Master MT5 Terminal. Exiting cycle.")
            # Update connection status
            account_settings._cache["mt5_status"] = "Failed"
            account_settings.update_connection_status(connected=False, error_msg="Failed to connect to MT5 Terminal")
            time.sleep(30)
            continue

        logger.info("✅ Connected to Master MT5 Terminal successfully.")
        account_settings._cache["mt5_status"] = "Connected"
        account_settings.update_connection_status(connected=True)

        # Use master symbols, fallback to standard if not set
        trading_symbols = account_settings.get_symbols()
        if not trading_symbols:
            trading_symbols = ["XAUUSD", "EURUSD"]

        # Get enabled accounts for broadcasting commands
        enabled_accounts = get_all_enabled_accounts()

        # 5. Analyze each symbol
        for symbol in trading_symbols:
            if _shutdown_requested:
                break
            try:
                sig_data = analyze_symbol(symbol, connector, supabase, cycle_count)
                if sig_data:
                    # Broadcast OPEN_TRADE commands to all enabled accounts
                    broadcast_commands_to_accounts(sig_data, supabase, enabled_accounts)
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)

        # 6. AI Evaluation of active trades (every 20 minutes)
        now = time.time()
        if now - last_trade_eval >= TRADE_EVAL_INTERVAL:
            last_trade_eval = now
            try:
                evaluate_active_trades(supabase, connector, enabled_accounts)
            except Exception as e:
                logger.error(f"Active trade evaluation error: {e}", exc_info=True)

        # 7. Unload AI from memory if local models were used
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
