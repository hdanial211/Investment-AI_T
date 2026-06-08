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

def loop_signal_generator(supabase: SupabaseSync, connector: MT5Connector, accounts: list):
    logger.info("🔍 Running Pre-Signal & Signal Generator Loop...")
    symbol = "XAUUSD" # We only trade gold in V4
    
    tick = connector.get_tick(symbol)
    if not tick: return
    
    mdf = connector.get_multi_timeframe(symbol, timeframes=["H4", "H1", "M30", "M15", "M5", "M1"], bars=100)
    if not mdf: return
    
    indicators = calculate_multi_indicators(mdf, symbol=symbol)
    
    # Pre-Signal Logic
    h4_trend = indicators.get("h4_trend", "RANGING")
    adx = indicators.get("adx", 0)
    pre_signal = f"Current H4 Trend is {h4_trend}. ADX is {adx}. Provide BUY, SELL, or HOLD."
    logger.info(f"Pre-Signal sent to AI: {pre_signal}")
    
    # Get Final Signals from AI for each style
    styles = ["SCALPING", "INTRADAY", "SWING"]
    
    for style in styles:
        ai_result = get_ai_signal(indicators, tick["bid"], tick["ask"], trade_memory=None, symbol=symbol, forced_style=style)
        action = ai_result.get("action", "HOLD")
        
        if action in ["BUY", "SELL"]:
            sig_id = str(uuid.uuid4())[:8]
            
            # V4 Architecture: Write one unified signal to market_signals
            market_payload = {
                "symbol": symbol,
                "action": action,
                "confidence": int(ai_result.get("confidence", 0.8) * 100),
                "trade_style": style,
                "reason": ai_result.get("reason", ""),
                "market_regime": indicators.get("market_regime", "UNKNOWN"),
                "bid": tick["bid"],
                "ask": tick["ask"],
                "atr": indicators.get("atr", 0),
                "signal_id": sig_id,
                "entry_zone": ai_result.get("entry_zone", ""),
                "sl_price": ai_result.get("sl_price", 0),
                "tp_price": ai_result.get("tp_price", 0)
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
                    "sl": ai_result.get("sl_price", 0),
                    "tp": ai_result.get("tp_price", 0),
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
    
    last_signal_time = 0
    last_heartbeat = 0
    
    while not _shutdown_requested:
        now = time.time()
        accounts = get_enabled_accounts(supabase)
        
        # 1. Heartbeat Loop (60s)
        if now - last_heartbeat >= 60:
            loop_heartbeat(supabase)
            last_heartbeat = now
            
        # 2. Signal Generator Loop (10m)
        if now - last_signal_time >= 600:
            loop_signal_generator(supabase, connector, accounts)
            last_signal_time = now
            
        time.sleep(5)

if __name__ == "__main__":
    main()
