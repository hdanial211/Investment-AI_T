import requests
import logging
import signal
import os
import sys
import time
import math

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


import MetaTrader5 as mt5


import MetaTrader5 as mt5
from news_manager import is_high_impact_news_active

def loop_signal_executor(supabase: SupabaseSync, connector: MT5Connector, acc: str, acct_settings: AccountSettings):
    try:
        if not connector.is_connected(): return
        
        # 1. Fetch active signals
        url = f"{supabase.base_url}/rest/v1/signals?account_id=eq.{acc}&is_active=eq.true"
        resp = requests.get(url, headers=supabase.headers)
        signals = resp.json() if resp.status_code == 200 else []
        if not signals: return
        
        # 2. Base Risk Management Data
        acct_info = connector.get_account_info()
        if not acct_info: return
        
        balance = acct_info.get("balance", 0)
        equity = acct_info.get("equity", 0)
        current_dd = ((balance - equity) / balance * 100) if (balance > 0 and equity < balance) else 0
        
        max_dd = acct_settings.max_daily_drawdown_pct or 50.0
        open_positions = connector.get_open_positions() or []
        current_trades_count = len(open_positions)
        max_trades = acct_settings.get_max_total_trades() or 10
        min_conf = acct_settings.min_ai_confidence or 70
        max_spread = acct_settings.max_spread_points or 50
        
        # Determine Asia Session (Broker Time Hour 0 to 8)
        # Using the tick time of the first available symbol to get broker time
        is_asia = False
        sample_tick = connector.get_tick("XAUUSD")
        if sample_tick:
            import time
            broker_hour = time.gmtime(sample_tick["time"]).tm_hour
            if 0 <= broker_hour < 8:
                is_asia = True
                
        # Check High-Impact News
        is_news = is_high_impact_news_active(["USD", "ALL"], 30, 30)
        
        for sig in signals:
            sym = sig.get("symbol", "XAUUSD")
            action = sig.get("action", "")
            style = sig.get("trade_style", "UNKNOWN")
            confidence = sig.get("confidence_score", 0)
            sig_id = sig.get("id")
            
            # --- V2 Risk Guard Saringan Ketat ---
            
            # 1. Adakah Trade Style Dibenarkan?
            if not acct_settings.is_style_enabled(style):
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Style {style} Disabled dalam UI.")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": f"Style {style} disabled"})
                continue
                
            # 2. Limit Trade Mengikut Style
            style_trades_count = len([p for p in open_positions if style.upper() in p.get("comment", "").upper() or str(p.get("magic", "")).endswith(
                "1" if style.upper()=="SCALPING" else "2" if style.upper()=="INTRADAY" else "3"
            )])
            max_style_trades = acct_settings.get_max_trades_for_style(style) or 3
            if style_trades_count >= max_style_trades:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Max {style} trades capai limit ({style_trades_count}/{max_style_trades})")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": f"Max {style} trades reached"})
                continue

            # 3. Allow Hedging Check
            # Jika hedging tidak dibenarkan, check adakah ada posisi berlawanan
            if not getattr(acct_settings, "allow_hedging", True):
                opposite = "SELL" if action == "BUY" else "BUY"
                has_opposite = any(p["direction"] == opposite for p in open_positions if p["symbol"] == sym)
                if has_opposite:
                    logger.warning(f"[{acc}] Signal {action} dibatalkan: Hedging tidak dibenarkan dan ada posisi {opposite} aktif.")
                    requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "Hedging disabled"})
                    continue

            # 4. Block Asia Session Check
            if getattr(acct_settings, "block_asia_session", False) and is_asia:
                logger.warning(f"[{acc}] Signal {action} digantung: Asia Session sedang aktif.")
                # Kita tidak matikan is_active, supaya ia boleh berjalan bila session tamat jika masih valid, atau analyzer ganti baru.
                # Tapi elok matikan saja sebab signal boleh lapuk.
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "Asia Session Blocked"})
                continue

            # 5. Block News Check
            # Tetapan Supabase "trade_during_events" -> True maksudnya BOLEH trade masa news. 
            # Jika False, maksudnya Block News Entries = Enabled
            trade_during_events = getattr(acct_settings, "trade_during_events", True)
            if not trade_during_events and is_news:
                logger.warning(f"[{acc}] Signal {action} digantung: High-Impact News sedang aktif.")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "High-Impact News Blocked"})
                continue

            # 6. Check Global Max Trades
            if current_trades_count >= max_trades:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Max total trades ({current_trades_count}/{max_trades})")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "Max global trades reached"})
                continue
                
            # 7. Check Max Drawdown
            if current_dd >= max_dd:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Max drawdown harian capai ({current_dd:.1f}% >= {max_dd}%)")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "Max drawdown reached"})
                continue
                
            # 8. Check AI Confidence
            if confidence < min_conf:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Confidence AI terlalu rendah ({confidence}% < {min_conf}%)")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "Low confidence"})
                continue
                
            # 9. Check Max Spread
            sym_info = mt5.symbol_info(sym)
            if not sym_info: continue
            spread = sym_info.spread
            if spread > max_spread:
                logger.warning(f"[{acc}] Signal {action} ditangguh (Hold): Spread semasa terlalu tinggi ({spread} > {max_spread})")
                # Jangan deactivate, tunggu next loop kot-kot spread turun
                continue
                
            # --- LULUS SEMUA TAPISAN, EKSEKUSI! ---
            use_auto_lot = acct_settings._cache.get("use_auto_lot", True)
            risk_percent = float(acct_settings._cache.get("max_risk_percent", 1.0))
            
            # Default fallback lot
            lot_size = acct_settings.get_lot_for_style(style) or 0.01
            
            # Auto Lot Logic based on SL Distance
            if use_auto_lot and sl_price > 0:
                tick = connector.get_tick(sym)
                balance = connector.get_balance()
                if tick and balance > 0:
                    entry_price = tick["ask"] if action == "BUY" else tick["bid"]
                    sl_dist = abs(entry_price - sl_price)
                    
                    # For XAUUSD, $1 move = $100 per 1.00 lot
                    contract_size = 100 
                    risk_amount = balance * (risk_percent / 100.0)
                    
                    if sl_dist > 0:
                        calc_lot = risk_amount / (sl_dist * contract_size)
                        # Round down to 2 decimals
                        calc_lot = math.floor(calc_lot * 100) / 100.0
                        lot_size = max(config.MIN_LOT, min(config.MAX_LOT, calc_lot))
                        logger.info(f"Auto-Lot active: Bal={balance}, Risk={risk_percent}%, SL_Dist={sl_dist:.2f} -> Calc Lot={lot_size}")
            
            logger.info(f"🚀 [{acc}] Risk Guard LULUS! Eksekusi {action} pada {sym} dengan Lot: {lot_size}")
            
            
            magic_number = 888999
            if style.upper() == "SCALPING": magic_number = 889000
            elif style.upper() == "INTRADAY": magic_number = 889001
            elif style.upper() == "SWING": magic_number = 889002
            
            res_trade = connector.open_trade(action, lot_size, sl=0, tp=0, symbol=sym, comment=f"AI_{style}", magic=magic_number)
            if res_trade:
                logger.success(f"✅ [{acc}] Berjaya membuka {action} {sym}")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "Executed successfully"})
                current_trades_count += 1
            else:
                logger.error(f"❌ [{acc}] Gagal membuka {action} {sym}")
                
    except Exception as e:
        logger.error(f"Signal Executor error for {acc}: {e}")
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
    
    last_eval_minute = -1
    last_info_sync = 0
    
    from datetime import datetime
    
    while not _shutdown_requested:
        now = time.time()
        current_minute = datetime.now().minute
        
        # Executor Loop (Setiap 5 saat)
        loop_signal_executor(supabase, connector, account_id, acct_settings)
        
        # Evaluator Loop (Setiap 10 minit ikut jam sebenar: 00, 10, 20...)
        # Juga akan jalan sekali sebaik sahaja bot dihidupkan (last_eval_minute == -1)
        if (current_minute % 10 == 0 and current_minute != last_eval_minute) or last_eval_minute == -1:
            sync_active_trades_from_mt5(supabase, connector, account_id)
            loop_evaluator(supabase, connector, account_id)
            last_eval_minute = current_minute
            
        # ── Kemaskini Balance & Info (Ikut masa 10 minit sekali, tak wajib genap)
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
