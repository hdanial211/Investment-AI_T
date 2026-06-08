import logging
import signal
import os
import sys
import time

import config
from mt5_connector import MT5Connector
from strategy import calculate_multi_indicators
from ai_engine import get_ai_signal
from trade_management.supabase_sync import SupabaseSync
import system_settings
from logger import setup_logging
from account_settings import AccountSettings

logger = setup_logging()

_shutdown_requested = False
def _signal_handler(signum, frame):
    global _shutdown_requested
    logger.info("Shutdown signal received for Evaluator...")
    _shutdown_requested = True

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

def sync_active_trades_from_mt5(supabase: SupabaseSync, connector: MT5Connector, acc: str):
    try:
        mt5_positions = connector.get_open_positions()
        if mt5_positions is None:
            return  # Error connecting or fetching
            
        db_trades = supabase.fetch_active_trades(acc)
        db_tickets = {int(t["ticket"]) for t in db_trades if t.get("ticket")}
        mt5_tickets = {int(p["ticket"]) for p in mt5_positions}
        
        # 1. Sync new/missing MT5 trades to Supabase
        for p in mt5_positions:
            tkt = int(p["ticket"])
            if tkt not in db_tickets:
                style = "UNKNOWN"
                magic = int(p.get("magic", 0))
                if magic == 0: style = "MANUAL"
                elif str(magic).endswith("1"): style = "SCALPING"
                elif str(magic).endswith("2"): style = "INTRADAY"
                elif str(magic).endswith("3"): style = "SWING"
                
                payload = {
                    "ticket": tkt,
                    "account_id": acc,
                    "symbol": p["symbol"],
                    "direction": p["direction"],
                    "lot": p["volume"],
                    "entry_price": p["price_open"],
                    "floating_profit": p["profit"],
                    "trade_style": style,
                    "current_status": "OPEN",
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
                supabase._upsert("active_trades", payload, conflict="ticket")
                logger.info(f"🔄 [Sync: {acc}] Added missing MT5 trade {tkt} to Supabase")
                
        # 2. Mark closed trades in Supabase
        for t in db_trades:
            tkt = int(t["ticket"])
            if tkt not in mt5_tickets:
                payload = {
                    "ticket": tkt,
                    "current_status": "CLOSED",
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
                supabase._upsert("active_trades", payload, conflict="ticket")
                logger.info(f"🔄 [Sync: {acc}] Marked trade {tkt} as CLOSED in Supabase")
                
    except Exception as e:
        logger.error(f"Sync MT5 to Supabase error for {acc}: {e}")

def loop_evaluator(supabase: SupabaseSync, connector: MT5Connector, acc: str):
    logger.info(f"🧠 [Evaluator: {acc}] Running Trade Evaluator Loop...")
    try:
        trades = supabase.fetch_active_trades(acc)
        if not trades:
            logger.info(f"🧠 [Evaluator: {acc}] Tiada active trades untuk dinilai.")
            return

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
                logger.info(f"🟡 [Evaluator: {acc}] Updated SL/TP for {ticket}")
    except Exception as e:
        logger.error(f"Evaluator error for {acc}: {e}")


def main():
    if len(sys.argv) < 2:
        logger.error("Sila berikan account_id. Contoh: python trade_evaluator.py acc_1")
        sys.exit(1)
        
    account_id = sys.argv[1]
    
    logger.info("==============================================")
    logger.info(f" 🧠 TRADE EVALUATOR PROCESS ({account_id}) ")
    logger.info("==============================================")
    
    # Refresh latest settings first
    system_settings.fetch_and_apply_system_settings()
    
    supabase = SupabaseSync()
    connector = MT5Connector()
    
    # Ambil laluan MT5 peribadi
    acc_data = supabase.fetch_account_settings(account_id)
    path = acc_data.get("mt5_path") if acc_data else None
    
    # Hubungkan ke MT5 individu. Jika login kosong, kita cuma 'attach' tanpa ubah akaun
    connector.connect(0, "", "", path)
    
    acct_settings = AccountSettings(account_id)
    
    last_eval_time = 0
    last_info_sync = 0
    
    while not _shutdown_requested:
        now = time.time()
        
        # Evaluator Loop (Setiap 10 minit / 600s)
        # Boleh laras jika nak cepat, contohnya 300s (5 minit)
        if now - last_eval_time >= 600:
            sync_active_trades_from_mt5(supabase, connector, account_id)
            loop_evaluator(supabase, connector, account_id)
            last_eval_time = now
            
        # ── Kemaskini Balance & Info (Akan run FIRST TIME masa mula-mula sebab last_info_sync = 0)
        if now - last_info_sync >= 600:
            acct_info = connector.get_account_info() or {}
            acct_settings.update_connection_status(
                connected=True,
                error_msg="",
                account_info=acct_info,
                symbol_status={},
            )
            logger.info(f"[{account_id}] Terminal Info & Balance di-kemaskini ke Supabase.")
            last_info_sync = now
            
        time.sleep(5)

if __name__ == "__main__":
    main()
