"""
master_analyzer.py - AI Brain for V4 Cloud-Native Hybrid Architecture

This is the Brain. It does NOT execute trades.
It writes 'signals' and 'sl_tp_updates' to Supabase. MQL5 EA executes them.

Loops:
1. Signal Generator (Every 10 mins) -> Writes to `signals` table
2. Active Trade Evaluator (Every 10 mins) -> Writes to `sl_tp_updates` table
3. Heartbeat (Every 60s) -> Writes to `bot_heartbeat`
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
    
    # Get Final Signal from AI
    ai_result = get_ai_signal(indicators, tick["bid"], tick["ask"], trade_memory=None, symbol=symbol, forced_style="INTRADAY")
    action = ai_result.get("action", "HOLD")
    
    if action in ["BUY", "SELL"]:
        sig_id = str(uuid.uuid4())[:8]
        for acc in accounts:
            payload = {
                "signal_id": f"{acc}_{sig_id}",
                "account_id": acc,
                "symbol": symbol,
                "action": action,
                "sl": ai_result.get("sl_price", 0),
                "tp": ai_result.get("tp_price", 0),
                "confidence": ai_result.get("confidence", 80),
                "style": ai_result.get("trade_style", "INTRADAY"),
                "reason": ai_result.get("reason", ""),
                "is_active": True
            }
            try:
                supabase._insert("signals", payload)
                logger.info(f"✅ Signal {action} inserted for account {acc}")
            except Exception as e:
                logger.error(f"Error inserting signal for {acc}: {e}")

def loop_evaluator(supabase: SupabaseSync, connector: MT5Connector, accounts: list):
    logger.info("🧠 Running Trade Evaluator Loop...")
    for acc in accounts:
        try:
            trades = supabase.fetch_active_trades(acc)
            for t in trades:
                ticket = t["ticket"]
                sym = t["symbol"]
                sl = t.get("virtual_sl", 0)
                tp = t.get("virtual_tp", 0)
                style = t.get("trade_style", "UNKNOWN")
                entry = t.get("entry_price", 0)
                profit = t.get("floating_profit", 0)
                
                tick = connector.get_tick(sym)
                if not tick: continue
                
                mdf = connector.get_multi_timeframe(sym, timeframes=["H4", "H1", "M30", "M15", "M5", "M1"], bars=50)
                if not mdf: continue
                indicators = calculate_multi_indicators(mdf, symbol=sym)
                
                eval_prompt = (
                    f"Trade {ticket} | Style: {style} | Entry: {entry} | "
                    f"Current SL: {sl} | Current TP: {tp} | Floating Profit: {profit}\n"
                    f"Market ADX: {indicators.get('adx', 0)} | H4 Trend: {indicators.get('h4_trend', 'UNKNOWN')}\n"
                    f"Are there any reversal patterns on M15/H1? Provide UPDATE_SL_TP or CLOSE_TRADE if risk is high, else HOLD."
                )
                
                ai_result = get_ai_signal(
                    {"trade_eval": eval_prompt}, 
                    tick["bid"], tick["ask"], None, sym, 
                    specific_provider_config=config.EVALUATOR_PROVIDER_CONFIG,
                    trade_eval_mode=True
                )
                
                if ai_result.get("action") == "UPDATE_SL_TP":
                    new_sl = ai_result.get("sl") or sl
                    new_tp = ai_result.get("tp") or tp
                    supabase._insert("sl_tp_updates", {
                        "signal_id": t.get("signal_id", str(ticket)),
                        "account_id": acc,
                        "ticket": ticket,
                        "new_sl": new_sl,
                        "new_tp": new_tp,
                        "applied": False
                    })
                    logger.info(f"🟡 Evaluator updated SL/TP for {ticket}")
        except Exception as e:
            logger.error(f"Evaluator error for {acc}: {e}")

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
    last_eval_time = 0
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
            
        # 3. Evaluator Loop (10m)
        if now - last_eval_time >= 600:
            loop_evaluator(supabase, connector, accounts)
            last_eval_time = now
            
        time.sleep(5)

if __name__ == "__main__":
    main()
