"""
master_analyzer.py - AI Brain for V4 Cloud-Native Hybrid Architecture

This is the Brain. It does NOT execute trades.
It writes 'signals' and 'sl_tp_updates' to Supabase. MQL5 EA executes them.

Loops:
1. Signal Generator (Every 10 mins) -> Writes to `signals` table
2. Heartbeat (Every 60s) -> Writes to `bot_heartbeat`
"""

import logging
import signal
import os
import sys
import time
import uuid
import json
from datetime import datetime

import config
from mt5_connector import MT5Connector
from strategy import calculate_multi_indicators
from ai_engine import get_ai_signal
from trade_management.supabase_sync import SupabaseSync
import system_settings
from logger import setup_logging
from style_params import get_style_params

logger = setup_logging()

_shutdown_requested = False
def _signal_handler(signum, frame):
    global _shutdown_requested
    logger.info("Shutdown signal received...")
    _shutdown_requested = True

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

def get_enabled_accounts(supabase: SupabaseSync) -> list:
    try:
        return supabase.fetch_all_enabled_accounts()
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        return []

def loop_signal_generator(supabase: SupabaseSync, connector: MT5Connector, accounts: list, target_style: str = None):
    logger.info("🔍 Running Pre-Signal & Signal Generator Loop...")
    symbol = "XAUUSD" # We only trade gold in V4
    
    tick = connector.get_tick(symbol)
    if not tick: return
    
    mdf = connector.get_multi_timeframe(symbol, timeframes=["D1", "H4", "H1", "M30", "M15", "M5", "M1"], bars=100)
    if not mdf: return
    
    indicators = calculate_multi_indicators(mdf, symbol=symbol)
    
    # Pre-Signal Logic
    h4_trend = indicators.get("h4_trend", "RANGING")
    adx = indicators.get("adx", 0)
    pre_signal = f"Current H4 Trend is {h4_trend}. ADX is {adx}. Provide BUY, SELL, or HOLD."
    logger.info(f"Pre-Signal sent to AI: {pre_signal}")
    
    # Get Final Signals from AI for each style
    styles = [target_style] if target_style else ["SCALPING", "INTRADAY", "SWING"]
    
    for style in styles:
        ai_result = get_ai_signal(indicators, tick["bid"], tick["ask"], trade_memory=None, symbol=symbol, forced_style=style)
        action = ai_result.get("action", "HOLD")
        
        if action in ["BUY", "SELL"]:
            sig_id = str(uuid.uuid4())[:8]
            
            # --- V3 DETERMINISTIC SL/TP CALCULATION ---
            s_params = get_style_params(style, symbol)
            
            if style == "SCALPING":
                active_atr = indicators.get("atr_scalping", 0)
            elif style == "INTRADAY":
                active_atr = indicators.get("atr_intraday", 0)
            elif style == "SWING":
                active_atr = indicators.get("atr_swing", 0)
            else:
                active_atr = indicators.get("atr", 0)
            
            if active_atr == 0:
                active_atr = 2.0 # Fallback for XAUUSD if data missing
                
            # 1. ATR Dynamic Bounds
            min_atr_dist = active_atr * 0.5
            daily_limit_dist = indicators.get("atr_swing", 0) * 1.5 # Maximum 1.5x D1 ATR
            
            raw_sl_dist = active_atr * s_params.get("sl_atr_multi", 2.0)
            raw_tp_dist = active_atr * s_params.get("tp_atr_multi", 3.0)
            
            # 2. Hard Limits based on Pips (1 Pip = $0.10 for Gold)
            pip_value = 0.10
            min_sl_dist = s_params.get("min_sl_pips", 0) * pip_value
            max_sl_dist = s_params.get("max_sl_pips", 9999) * pip_value
            min_tp_dist = s_params.get("min_tp_pips", 0) * pip_value
            max_tp_dist = s_params.get("max_tp_pips", 9999) * pip_value
            
            # 3. Apply ATR Constraints
            atr_sl_dist = max(min_atr_dist, raw_sl_dist)
            if style in ["INTRADAY", "SWING"] and daily_limit_dist > 0:
                atr_sl_dist = min(atr_sl_dist, daily_limit_dist)
                
            # 4. Apply Hard Limits (Clamp between Min and Max Pips)
            final_sl_dist = max(min_sl_dist, min(max_sl_dist, atr_sl_dist))
            final_tp_dist = max(min_tp_dist, min(max_tp_dist, raw_tp_dist))
                
            if action == "BUY":
                calc_sl = tick["ask"] - final_sl_dist
                calc_tp = tick["ask"] + final_tp_dist
            else:
                calc_sl = tick["bid"] + final_sl_dist
                calc_tp = tick["bid"] - final_tp_dist
            # ------------------------------------------
            
            # V4 Architecture: Write one unified signal to market_signals
            market_payload = {
                "symbol": symbol,
                "action": action,
                "confidence": float(ai_result.get("confidence", 0.8)),
                "trade_style": style,
                "reason": ai_result.get("reason", ""),
                "market_regime": indicators.get("market_regime", "UNKNOWN"),
                "bid": tick["bid"],
                "ask": tick["ask"],
                "atr": indicators.get("atr", 0),
                "signal_id": sig_id,
                "entry_zone": ai_result.get("entry_zone", ""),
                "sl_price": calc_sl,
                "tp_price": calc_tp
            }
            
            try:
                supabase.upsert_market_signal(market_payload)
                logger.info(f"✅ Market Signal {action} ({style}) upserted to Supabase")
            except Exception as e:
                logger.error(f"Error upserting market signal for {style}: {e}")
                
            # Legacy/Executor signals: write commands to trade_commands or signals if still needed
            for acc in accounts:
                payload = {
                    "signal_id": f"{acc}_{sig_id}",
                    "account_id": acc,
                    "symbol": symbol,
                    "action": action,
                    "sl": calc_sl,
                    "tp": calc_tp,
                    "confidence": int(ai_result.get("confidence", 0.8) * 100),
                    "style": style,
                    "reason": ai_result.get("reason", ""),
                    "is_active": True
                }
                try:
                    supabase._insert("signals", payload)
                    logger.info(f"✅ Signal {action} ({style}) inserted for account {acc}")
                except Exception as e:
                    logger.error(f"Error inserting signal {style} for {acc}: {e}")


def loop_heartbeat(supabase: SupabaseSync):
    try:
        supabase.upsert_heartbeat(status="online", message="Master Analyzer OK")
    except Exception as e:
        logger.error(f"Heartbeat error: {e}")

def main():
    logger.info("==============================================")
    logger.info(" 🧠 MASTER ANALYZER (V4 CLOUD-NATIVE BRAIN) ")
    logger.info("==============================================")
    
    supabase = SupabaseSync()
    connector = MT5Connector()
    
    # Try connecting to Master MT5 using dynamic settings from Supabase
    system_settings.fetch_and_apply_system_settings()
    master_path = getattr(config, "MASTER_MT5_PATH", config.MT5_PATH)
    connector.connect(0, "", "", master_path)
    
    last_runs = {
        "SCALPING": "",
        "INTRADAY": "",
        "SWING": ""
    }
    last_heartbeat = 0
    
    while not _shutdown_requested:
        now = time.time()
        accounts = get_enabled_accounts(supabase)
        
        # 1. Heartbeat Loop (60s)
        if now - last_heartbeat >= 60:
            loop_heartbeat(supabase)
            last_heartbeat = now
            
        # 2. Clock-Based Schedule (Genap Masa)
        dt_now = datetime.now()
        cur_min = dt_now.minute
        time_str = dt_now.strftime("%Y-%m-%d %H:%M")
        
        # SWING (Setiap 1 Jam: XX:00)
        if cur_min == 0 and last_runs["SWING"] != time_str:
            loop_signal_generator(supabase, connector, accounts, target_style="SWING")
            last_runs["SWING"] = time_str
            
        # INTRADAY (Setiap 30 Min: XX:00, XX:30)
        if (cur_min == 0 or cur_min == 30) and last_runs["INTRADAY"] != time_str:
            loop_signal_generator(supabase, connector, accounts, target_style="INTRADAY")
            last_runs["INTRADAY"] = time_str
            
        # SCALPING (Setiap 10 Min: XX:00, XX:10, XX:20...)
        if (cur_min % 10 == 0) and last_runs["SCALPING"] != time_str:
            loop_signal_generator(supabase, connector, accounts, target_style="SCALPING")
            last_runs["SCALPING"] = time_str
            
        time.sleep(5)

if __name__ == "__main__":
    main()
