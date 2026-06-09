"""
master_analyzer.py - AI Brain for V4 Cloud-Native Hybrid Architecture

This is the Brain. It does NOT execute trades.
It writes 'signals' to Supabase (broadcasted). MQL5 EA executes them.

Loops:
1. Signal Generator (Cron Schedule 00/30) -> Writes to `signals` table
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
from mt5_connector import mt5_conn
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

def loop_signal_generator(supabase: SupabaseSync, accounts: list, target_style: str = None):
    logger.info("🔍 Running Signal Generator Loop...")
    symbol = "XAUUSD" # We only trade gold in V4
    
    tick = mt5_conn.get_tick(symbol)
    if not tick: return
    
    mdf = mt5_conn.get_multi_timeframe(symbol, timeframes=["D1", "H4", "H1", "M30", "M15", "M5", "M1"], bars=100)
    if not mdf: return
    
    indicators = calculate_multi_indicators(mdf, symbol=symbol)
    
    styles = [target_style] if target_style else ["SCALPING", "INTRADAY", "SWING"]
    
    for style in styles:
        ai_result = get_ai_signal(indicators, tick["bid"], tick["ask"], trade_memory=None, symbol=symbol, forced_style=style)
        action = ai_result.get("action", "HOLD")
        
        if action in ["BUY", "SELL"]:
            # --- V4 STATIC PIP CALCULATION FOR INITIAL SIGNAL ---
            s_params = get_style_params(style)
            pip_value = 0.10  # 1 pip = $0.10 for Gold
            
            final_sl_dist = s_params.get("max_virtual_sl_pips", 40) * pip_value
            final_tp_dist = s_params.get("max_virtual_tp_pips", 80) * pip_value
                
            if action == "BUY":
                calc_sl = tick["ask"] - final_sl_dist
                calc_tp = tick["ask"] + final_tp_dist
            else:
                calc_sl = tick["bid"] + final_sl_dist
                calc_tp = tick["bid"] - final_tp_dist
            # ------------------------------------------
            
            # V4 Architecture: Broadcast signal to all enabled accounts
            signal_data = {
                "symbol": symbol,
                "action": action,
                "sl": calc_sl,
                "tp": calc_tp,
                "confidence": int(ai_result.get("confidence", 0.8) * 100),
                "style": style,
                "reason": ai_result.get("reason", ""),
            }
            
            try:
                supabase.broadcast_signal_to_accounts(accounts, signal_data)
                logger.info(f"✅ Signal {action} ({style}) broadcasted to {len(accounts)} accounts")
            except Exception as e:
                logger.error(f"Error broadcasting signal {style}: {e}")

def loop_heartbeat(supabase: SupabaseSync):
    try:
        supabase.upsert_heartbeat(status="online", message="Master Analyzer OK")
    except Exception as e:
        logger.error(f"Heartbeat error: {e}")

def main():
    # Try connecting to Master MT5 using dynamic settings from Supabase
    system_settings.fetch_and_apply_system_settings(silent_global=True)
    
    m_provider = config.MAIN_PROVIDER_CONFIG.get("provider", "groq") if hasattr(config, "MAIN_PROVIDER_CONFIG") else "groq"
    m_model = config.MASTER_AI_MAIN_MODEL if hasattr(config, "MASTER_AI_MAIN_MODEL") else "llama-3.3-70b-versatile"
    v_provider = config.VISION_PROVIDER_CONFIG.get("provider", "groq") if hasattr(config, "VISION_PROVIDER_CONFIG") else "groq"
    v_model = config.VISION_AI_MODEL if hasattr(config, "VISION_AI_MODEL") else "llama-3.3-70b-versatile"
    
    logger.info("==================================================")
    logger.info(" 🧠 MASTER ANALYZER (V4 CLOUD-NATIVE BRAIN) ")
    logger.info(f" Main Model: {m_provider} / {m_model}")
    logger.info(f" Vision Model: {v_provider} / {v_model}")
    logger.info("==================================================")
    
    supabase = SupabaseSync()
    
    master_path = getattr(config, "MASTER_MT5_PATH", config.MT5_PATH)
    mt5_conn.connect(0, "", "", master_path)
    
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
            
        # 2. Clock-Based Schedule (Cron logic)
        dt_now = datetime.now()
        cur_min = dt_now.minute
        cur_hour = dt_now.hour
        time_str = dt_now.strftime("%Y-%m-%d %H:%M")
        
        # SWING (Setiap 2 Jam: Jam genap, minit 00)
        if (cur_hour % 2 == 0) and cur_min == 0 and last_runs["SWING"] != time_str:
            loop_signal_generator(supabase, accounts, target_style="SWING")
            last_runs["SWING"] = time_str
            
        # INTRADAY (Setiap 1 Jam: XX:00)
        if cur_min == 0 and last_runs["INTRADAY"] != time_str:
            loop_signal_generator(supabase, accounts, target_style="INTRADAY")
            last_runs["INTRADAY"] = time_str
            
        # SCALPING (Setiap 30 Min: XX:00, XX:30)
        if (cur_min == 0 or cur_min == 30) and last_runs["SCALPING"] != time_str:
            loop_signal_generator(supabase, accounts, target_style="SCALPING")
            last_runs["SCALPING"] = time_str
            
        time.sleep(5)

if __name__ == "__main__":
    main()
