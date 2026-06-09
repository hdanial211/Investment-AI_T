import requests
import logging
import signal
import os
import sys
import time
import math
import json
from datetime import datetime

import config
import MetaTrader5 as mt5
from mt5_connector import mt5_conn
from strategy import calculate_multi_indicators
from ai_engine import get_ai_signal, query_ai_provider
from trade_management.supabase_sync import SupabaseSync
import system_settings
from logger import setup_logging
from account_settings import AccountSettings
from news_manager import is_high_impact_news_active

logger = setup_logging()

_shutdown_requested = False
def _signal_handler(signum, frame):
    global _shutdown_requested
    logger.info("Shutdown signal received for Evaluator...")
    _shutdown_requested = True

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

def sync_active_trades_from_mt5(supabase: SupabaseSync, acc: str, acct_settings):
    try:
        mt5_positions = mt5_conn.get_open_positions()
        if mt5_positions is None:
            return  # Error connecting or fetching
            
        db_trades = supabase.fetch_active_trades(acc)
        db_tickets = {int(t["ticket"]) for t in db_trades if t.get("ticket")}
        mt5_tickets = {int(p["ticket"]) for p in mt5_positions}
        
        # 1. Sync new/missing MT5 trades and update existing floating profit
        for p in mt5_positions:
            tkt = int(p["ticket"])
            if tkt not in db_tickets:
                magic = int(p.get("magic", 0))
                style = "UNKNOWN"
                is_manual = False
                if magic == 0: 
                    style = "MANUAL"
                    is_manual = True
                elif magic == 888801: style = "SCALPING"
                elif magic == 888802: style = "INTRADAY"
                elif magic == 888803: style = "SWING"
                
                payload = {
                    "ticket": tkt,
                    "account_id": acc,
                    "symbol": p["symbol"],
                    "direction": "BUY" if p["type"] == 0 else "SELL",  # type=0 is BUY, type=1 is SELL
                    "lot": p["volume"],
                    "entry_price": p["price_open"],
                    "floating_profit": p["profit"],
                    "trade_style": style,
                    "current_status": "OPEN",
                    "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
                
                # --- MANUAL TRADE MANAGEMENT ---
                if is_manual:
                    manage_sl = acct_settings._cache.get("manage_manual_sl", False)
                    manage_tp = acct_settings._cache.get("manage_manual_tp", False)
                    manage_be = acct_settings._cache.get("manage_manual_be", False)
                    
                    if manage_sl or manage_tp or manage_be:
                        payload["trade_style"] = "MANUAL_PENDING_AI"
                        payload["virtual_sl"] = 0
                        payload["virtual_tp"] = 0
                supabase._upsert("active_trades", payload, conflict="ticket")
                logger.info(f"🔄 [Sync: {acc}] Added missing MT5 trade {tkt} to Supabase")
            else:
                # Update floating profit for existing active trades
                supabase._upsert("active_trades", {
                    "ticket": tkt,
                    "floating_profit": p["profit"],
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }, conflict="ticket")
                
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

def loop_signal_executor(supabase: SupabaseSync, acc: str, acct_settings: AccountSettings):
    try:
        if not mt5_conn.is_connected(): return
        
        # 1. Fetch active signals
        url = f"{supabase.base_url}/rest/v1/signals?account_id=eq.{acc}&is_active=eq.true"
        resp = requests.get(url, headers=supabase.headers)
        signals = resp.json() if resp.status_code == 200 else []
        if not signals: return
        
        # 2. Base Risk Management Data
        acct_info = mt5_conn.get_account_info()
        if not acct_info: return
        
        balance = acct_info.get("balance", 0)
        equity = acct_info.get("equity", 0)
        current_dd = ((balance - equity) / balance * 100) if (balance > 0 and equity < balance) else 0
        
        max_dd = acct_settings.max_daily_drawdown_pct or 50.0
        open_positions = mt5_conn.get_open_positions() or []
        current_trades_count = len(open_positions)
        max_trades = acct_settings.get_max_total_trades() or 10
        min_conf = acct_settings.min_ai_confidence or 70
        max_spread = acct_settings.max_spread_points or 50
        
        # Determine Asia Session (Broker Time Hour 0 to 8)
        # Using the tick time of the first available symbol to get broker time
        is_asia = False
        gold_symbol = acct_settings._cache.get("symbol_xauusd", "XAUUSD")
        sample_tick = mt5_conn.get_tick(gold_symbol)
        if sample_tick:
            import time
            broker_hour = time.gmtime(sample_tick["time"]).tm_hour
            if 0 <= broker_hour < 8:
                is_asia = True
                
        # Check High-Impact News
        is_news = is_high_impact_news_active(["USD", "ALL"], 30, 30)
        
        for sig in signals:
            sym = sig.get("symbol", "XAUUSD")
            if sym == "XAUUSD":
                sym = gold_symbol
                
            action = sig.get("action") or sig.get("direction", "")
            style = sig.get("trade_style", sig.get("style", "UNKNOWN"))
            confidence = sig.get("confidence", 0)
            sig_id = sig.get("id")
            sl_price = float(sig.get("sl") or 0)
            tp_price = float(sig.get("tp") or 0)
            
            # --- V2 Risk Guard Saringan Ketat ---
            
            # 1. Adakah Trade Style Dibenarkan?
            if not acct_settings.is_style_enabled(style):
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Style {style} Disabled dalam UI.")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": f"Style {style} disabled"})
                continue
                
            # 2. Limit Trade Mengikut Style
            expected_magic = 888801 if style.upper()=="SCALPING" else 888802 if style.upper()=="INTRADAY" else 888803
            style_trades_count = len([p for p in open_positions if style.upper() in p.get("comment", "").upper() or int(p.get("magic", 0)) == expected_magic])
            max_style_trades = acct_settings.get_max_trades_for_style(style) or 3
            if style_trades_count >= max_style_trades:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Max {style} trades capai limit ({style_trades_count}/{max_style_trades})")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": f"Max {style} trades reached"})
                continue

            # 3. Allow Hedging Check
            # Jika hedging tidak dibenarkan, check adakah ada posisi berlawanan
            if not getattr(acct_settings, "allow_hedging", True):
                opposite = "SELL" if action == "BUY" else "BUY"
                has_opposite = any(("BUY" if p.get("type") == 0 else "SELL") == opposite for p in open_positions if p.get("symbol") == sym)
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
            mt5.symbol_select(sym, True)
            sym_info = mt5.symbol_info(sym)
            if not sym_info: 
                logger.error(f"❌ [{acc}] Signal {action} gagal: Simbol {sym} tidak ditemui di broker (Sila periksa symbol suffix seperti XAUUSDc/m).")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": f"Simbol {sym} tiada di broker"})
                continue
            spread = sym_info.spread
            if spread > max_spread:
                logger.warning(f"[{acc}] Signal {action} ditangguh (Hold): Spread semasa terlalu tinggi ({spread} > {max_spread})")
                # Jangan deactivate, tunggu next loop kot-kot spread turun
                continue
                
            # --- LULUS SEMUA TAPISAN, EKSEKUSI! ---
            # Default fallback lot
            lot_size = acct_settings.get_lot_for_style(style) or 0.01
            
            logger.info(f"🚀 [{acc}] Risk Guard LULUS! Eksekusi {action} pada {sym} dengan Lot: {lot_size}")
            
            # Magic number: 888801=SCALPING, 888802=INTRADAY, 888803=SWING
            magic_number = 888800
            if style.upper() == "SCALPING": magic_number = 888801
            elif style.upper() == "INTRADAY": magic_number = 888802
            elif style.upper() == "SWING": magic_number = 888803
            
            # V4: Buka trade TANPA broker SL/TP (sl=0, tp=0).
            # Virtual SL/TP akan diuruskan oleh bot sendiri dan disimpan ke Supabase.
            res_trade = mt5_conn.open_trade(action, lot_size, sl=0, tp=0, symbol=sym, comment=f"AI_{style}", magic=magic_number)
            if res_trade:
                ticket_id = res_trade if isinstance(res_trade, int) else res_trade.get("ticket", 0) if isinstance(res_trade, dict) else 0
                logger.info(f"✅ [{acc}] Berjaya membuka {action} {sym} (Ticket: {ticket_id})")
                
                # --- TULIS VIRTUAL SL/TP/TRAILING KE SUPABASE ---
                from style_params import get_style_params
                s_params = get_style_params(style, sym)
                trailing_settings = acct_settings.get_trailing_settings(style)
                
                # Guna SL/TP dari signal. Jika kosong (0), kira semula dari style_params.
                final_sl = sl_price
                final_tp = tp_price
                if final_sl == 0 or final_tp == 0:
                    pip_value = 0.10  # Gold: 1 pip = $0.10
                    tick_data = mt5_conn.get_tick(sym)
                    if tick_data:
                        avg_sl_pips = (s_params.get("min_sl_pips", 20) + s_params.get("max_sl_pips", 40)) / 2.0
                        avg_tp_pips = (s_params.get("min_tp_pips", 30) + s_params.get("max_tp_pips", 60)) / 2.0
                        sl_dist = avg_sl_pips * pip_value
                        tp_dist = avg_tp_pips * pip_value
                        if action == "BUY":
                            final_sl = final_sl or round(tick_data["ask"] - sl_dist, 2)
                            final_tp = final_tp or round(tick_data["ask"] + tp_dist, 2)
                        else:
                            final_sl = final_sl or round(tick_data["bid"] + sl_dist, 2)
                            final_tp = final_tp or round(tick_data["bid"] - tp_dist, 2)
                
                # Retrieve Pip-based trailing settings
                be_trigger_pips = trailing_settings.get("be_trigger_pips") or 15
                be_offset_pips = trailing_settings.get("be_offset_pips") or 2
                trail_start_pips = trailing_settings.get("trail_start_pips") or 20
                trail_dist_pips = trailing_settings.get("trail_dist_pips") or 10
                
                # Tulis ke active_trades di Supabase dengan virtual SL/TP penuh
                if ticket_id:
                    entry_price = mt5_conn.get_tick(sym)["ask"] if action == "BUY" else mt5_conn.get_tick(sym)["bid"]
                    trade_payload = {
                        "ticket": ticket_id,
                        "account_id": acc,
                        "symbol": sym,
                        "direction": action,
                        "lot": lot_size,
                        "entry_price": entry_price,
                        "trade_style": style,
                        "virtual_sl": final_sl,
                        "virtual_tp": final_tp,
                        "be_trigger_pips": be_trigger_pips,
                        "be_offset_pips": be_offset_pips,
                        "trail_start_pips": trail_start_pips,
                        "trail_dist_pips": trail_dist_pips,
                        "current_status": "OPEN",
                        "floating_profit": 0,
                        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    }
                    supabase._upsert("active_trades", trade_payload, conflict="ticket")
                    logger.info(f"📊 [{acc}] Virtual SL: {final_sl} | Virtual TP: {final_tp} | Pips BE/Trail Configured")
                
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "Executed successfully"})
                current_trades_count += 1
            else:
                logger.error(f"❌ [{acc}] Gagal membuka {action} {sym}")
                requests.patch(f"{supabase.base_url}/rest/v1/signals?id=eq.{sig_id}", headers=supabase.headers, json={"is_active": False, "reason": "Execution failed at broker"})
                
    except Exception as e:
        logger.error(f"Signal Executor error for {acc}: {e}")

def loop_evaluator(supabase, account_id, acct_settings, current_minute, is_startup=False):
    """
    Menilai setiap active trade dan menggunakan Provider (Main & Risk) 
    untuk menapis sentimen pasaran dan pergerakan semasa.
    Waktu Penilaian berdasarkan Trade Style:
    - Scalping: Setiap 15 Minit (00, 15, 30, 45)
    - Intraday: Setiap 30 Minit (00, 30)
    - Swing: Setiap 60 Minit (00)
    """
    
    acc = account_id
    trades = supabase.fetch_active_trades(acc)
    if not trades:
        # Kurangkan spam log: Hanya log jika minit 00, 15, 30, 45
        if current_minute % 15 == 0:
            logger.info(f"🧠 [{acc}] Tiada active trades untuk dinilai pada minit ke-{current_minute}.")
        return

    # Skip evaluation if provider list is empty
    provider_config = acct_settings.get_evaluator_config()
    if not provider_config:
        logger.warning(f"[{acc}] Tiada konfigurasi Evaluator dijumpai. Skipping evaluation.")
        return
        
    for t in trades:
        sym = t["symbol"]
        action_raw = t.get("direction") or t.get("action") or ""
        action_raw_str = str(action_raw).strip().upper()
        action = "BUY" if action_raw_str in ["0", "BUY"] else "SELL" if action_raw_str in ["1", "SELL"] else action_raw_str
        style = (t.get("trade_style") or t.get("style") or "UNKNOWN").upper()
        ticket = t["ticket"]
        sl = t.get("virtual_sl", 0)
        tp = t.get("virtual_tp", 0)
        entry = t.get("entry_price", 0)
        profit = t.get("floating_profit", 0)
        
        # --- SARINGAN MASA EVALUATOR MENGIKUT STYLE ---
        if not is_startup:
            if style == "SCALPING" and current_minute % 15 != 0:
                continue
            elif style == "INTRADAY" and current_minute % 30 != 0:
                continue
            elif style == "SWING" and current_minute != 0:
                continue
        
        logger.info(f"🧠 [{acc}] Menilai trade {ticket} ({sym} {action}) [{style}] pada minit ke-{current_minute}...")
        
        tick = mt5_conn.get_tick(sym)
        if not tick: continue
        
        mdf = mt5_conn.get_multi_timeframe(sym, timeframes=["H4", "H1", "M30", "M15", "M5", "M1"], bars=50)
        if not mdf: continue
        indicators = calculate_multi_indicators(mdf, symbol=sym)
        
        eval_prompt = (
            f"Trade {ticket} | Style: {style} | Entry: {entry} | "
            f"Current SL: {sl} | Current TP: {tp} | Floating Profit: {profit}\n"
            f"Market ADX: {indicators.get('adx', 0)} | H4 Trend: {indicators.get('h4_trend', 'UNKNOWN')}\n"
            f"Are there any reversal patterns on M15/H1? Provide CLOSE_TRADE if risk is high, else HOLD. DO NOT provide UPDATE_SL_TP."
        )
        
        # Guna konfigurasi Evaluator individu dari dashboard (jika ada)
        eval_cfg = acct_settings.get_evaluator_config() or {}
        
        if eval_cfg.get("provider") and eval_cfg.get("api_key"):
            # Jika user dah set provider/model/api_key khusus untuk Evaluator di Dashboard
            fast_provider = eval_cfg
            _prov = fast_provider.get("provider")
            _key = fast_provider.get("api_key")
            _mask = f"{_key[:4]}...{_key[-4:]}" if len(_key) > 8 else "***"
            logger.info(f"🔑 [Account {acc}] Evaluator mengikut Dashboard: Provider='{_prov}', Model='{fast_provider.get('model')}', Key='{_mask}'")
        else:
            # Fallback jika kosong
            fast_provider = {
                "provider": "groq", 
                "model": "llama-3.1-8b-instant"
            }
            logger.info(f"⚠️ [Account {acc}] Evaluator di Dashboard KOSONG. Guna Fallback: Provider='groq', Model='llama-3.1-8b-instant'")
        
        
        ai_result = get_ai_signal(
            {"trade_eval": eval_prompt}, 
            tick["bid"], tick["ask"], None, sym, 
            specific_provider_config=fast_provider,
            trade_eval_mode=True
        )
        
        if ai_result.get("action") == "CLOSE_TRADE":
            supabase.insert_trade_command(acc, "CLOSE_TRADE", sym, ticket=ticket, reason="AI Evaluator Decision")
            logger.info(f"🛑 [Evaluator: {acc}] Trade {ticket} diarahkan CLOSE_TRADE.")
        else:
            logger.info(f"🔵 [Evaluator: {acc}] Trade {ticket} status: HOLD.")

def evaluate_pending_manual_trades(supabase: SupabaseSync, account_id: str, acct_settings: AccountSettings):
    active_trades = supabase.fetch_active_trades(account_id)
    if not active_trades: return
    pending_manuals = [t for t in active_trades if t.get("current_status") == "OPEN" and (t.get("trade_style") == "MANUAL_PENDING_AI" or t.get("style") == "MANUAL_PENDING_AI")]
    
    if not pending_manuals:
        return
        
    for p in pending_manuals:
        ticket = p.get("ticket")
        symbol = p.get("symbol")
        dir_raw = p.get("direction") or p.get("action") or ""
        dir_raw_str = str(dir_raw).strip().upper()
        direction = "BUY" if dir_raw_str in ["0", "BUY"] else "SELL" if dir_raw_str in ["1", "SELL"] else dir_raw_str
        entry_price = float(p.get("entry_price", 0))
        
        from style_params import get_style_params
        s_scalping = get_style_params("SCALPING", symbol)
        s_intraday = get_style_params("INTRADAY", symbol)
        
        prompt = f'''Anda adalah pakar trading AI. Terdapat satu posisi MANUAL yang baru dibuka.
Maklumat Posisi:
- Simbol: {symbol}
- Arah (Direction): {direction}
- Entry Price: {entry_price}

Tugas anda adalah untuk mencadangkan paras Stop Loss (SL) dan Take Profit (TP) yang paling optimum berdasarkan struktur pasaran terkini untuk harga entry ini. 
Anda HANYA dibenarkan memilih profil SCALPING atau INTRADAY.
Had Maksimum Pips (Jarak SL):
- SCALPING max: {s_scalping.get('max_sl_pips', 40)} pips
- INTRADAY max: {s_intraday.get('max_sl_pips', 100)} pips

Sila berikan maklum balas HANYA dalam format JSON tulen berikut, tanpa teks tambahan:
{{
    "chosen_style": "SCALPING",
    "stop_loss_price": 0.00,
    "take_profit_price": 0.00,
    "reason": "..."
}}
'''
        logger.info(f"🧠 [Manual Evaluator] Asking AI for ticket {ticket} ({symbol} {direction})")
        
        import system_settings
        dash = system_settings.get_dashboard_settings()
        fast_provider = dash.get("fast_model") if dash else None
        
        raw_resp = query_ai_provider(
            prompt,
            role="main",
            provider_sequence=[fast_provider] if fast_provider else None
        )
        
        try:
            resp = raw_resp.strip()
            if "```json" in resp:
                resp = resp.split("```json")[1].split("```")[0].strip()
            elif "```" in resp:
                resp = resp.replace("```", "").strip()
            
            data = json.loads(resp)
            chosen_style = data.get("chosen_style", "SCALPING")
            if chosen_style not in ["SCALPING", "INTRADAY"]:
                chosen_style = "SCALPING"
                
            ai_sl = float(data.get("stop_loss_price", 0))
            ai_tp = float(data.get("take_profit_price", 0))
            
            pip_val = 0.10 if 'XAU' in symbol else 0.01
            max_sl = s_intraday.get("max_sl_pips", 100) if chosen_style == "INTRADAY" else s_scalping.get("max_sl_pips", 40)
            sl_dist = abs(ai_sl - entry_price) / pip_val
            
            if sl_dist > max_sl:
                cap_dist = max_sl * pip_val
                ai_sl = entry_price - cap_dist if direction == "BUY" else entry_price + cap_dist
                logger.warning(f"⚠️ AI SL exceeded {chosen_style} cap, capped to {ai_sl}")
                
            new_style = f"MANUAL_{chosen_style}"
            payload = {
                "ticket": ticket,
                "trade_style": new_style,
                "virtual_sl": round(ai_sl, 2),
                "virtual_tp": round(ai_tp, 2),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            supabase._upsert("active_trades", payload, conflict="ticket")
            logger.info(f"✅ [Manual Evaluator] Ticket {ticket} assigned AI SL={ai_sl}, TP={ai_tp}, Style={new_style}")
            
        except Exception as e:
            logger.error(f"Failed to parse AI response for manual trade {ticket}: {e}. Raw: {raw_resp}")
            pip_val = 0.10 if 'XAU' in symbol else 0.01
            payload = {
                "ticket": ticket,
                "trade_style": "MANUAL_SCALPING",
                "virtual_sl": entry_price - (30 * pip_val) if direction == "BUY" else entry_price + (30 * pip_val),
                "virtual_tp": entry_price + (50 * pip_val) if direction == "BUY" else entry_price - (50 * pip_val),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            supabase._upsert("active_trades", payload, conflict="ticket")

def main():

    if len(sys.argv) < 2:
        logger.error("Sila berikan account_id. Contoh: python trade_evaluator.py Hakim")
        sys.exit(1)
        
    account_id = sys.argv[1]
    config.ACCOUNT_ID = account_id
    
    supabase = SupabaseSync()
    
    # Ambil laluan MT5 peribadi
    acc_data = supabase.fetch_account_settings(account_id)
    path = acc_data.get("mt5_path") if acc_data else None
    
    # Hubungkan ke MT5 individu
    mt5_conn.connect(0, "", "", path)
    
    acct_settings = AccountSettings(account_id)
    eval_cfg = acct_settings.get_evaluator_config() or {}
    risk_cfg = acct_settings.get_risk_config() or {}
    
    e_model = f"{eval_cfg.get('provider')} / {eval_cfg.get('model')}" if eval_cfg.get("model") else "groq / llama-3.1-8b-instant (Fallback)"
    r_model = f"{risk_cfg.get('provider')} / {risk_cfg.get('model')}" if risk_cfg.get("model") else "groq / llama-3.1-8b-instant (Fallback)"
    
    logger.info("==================================================")
    logger.info(f" 🧠 TRADE EVALUATOR PROCESS ({account_id}) ")
    logger.info(f" Evaluator Model: {e_model}")
    logger.info(f" Risk Model: {r_model}")
    logger.info("==================================================")
    
    # Evaluator State
    last_eval_minute = -1
    last_info_sync = 0
    
    from datetime import datetime
    
    while not _shutdown_requested:
        now = time.time()
        current_minute = datetime.now().minute
        
        # Executor Loop (Setiap 5 saat)
        loop_signal_executor(supabase, account_id, acct_settings)
        sync_active_trades_from_mt5(supabase, account_id, acct_settings)
        
        # Evaluator Loop (Jalankan setiap minit, dan saring di dalam loop mengikut Trade Style)
        # Scalping (15m), Intraday (30m), Swing (60m). Startup (Sekali sahaja)
        is_startup = (last_eval_minute == -1)
        if current_minute != last_eval_minute or is_startup:
            loop_evaluator(supabase, account_id, acct_settings, current_minute, is_startup)
            last_eval_minute = current_minute
            
        # ── Kemaskini Balance & Info (Ikut masa 10 minit sekali, tak wajib genap)
        if now - last_info_sync >= 600:
            acct_info = mt5_conn.get_account_info() or {}
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
