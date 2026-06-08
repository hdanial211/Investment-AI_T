import sys

with open("Bot Engine/trade_evaluator.py", "r", encoding="utf-8") as f:
    content = f.read()

# We want to replace the old loop_signal_executor with the new one.
# So we split or regex it out.
import re
new_executor_code = """
import MetaTrader5 as mt5
from news_manager import is_high_impact_news_active

def loop_signal_executor(supabase: SupabaseSync, connector: MT5Connector, acc: str, acct_settings: AccountSettings):
    try:
        if not connector.is_connected(): return
        
        # 1. Fetch active signals
        res = supabase.client.table("signals").select("*").eq("account_id", acc).eq("is_active", True).execute()
        signals = res.data if res else []
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
                supabase.client.table("signals").update({"is_active": False, "reason": f"Style {style} disabled"}).eq("id", sig_id).execute()
                continue
                
            # 2. Limit Trade Mengikut Style
            style_trades_count = len([p for p in open_positions if style.upper() in p.get("comment", "").upper() or str(p.get("magic", "")).endswith(
                "1" if style.upper()=="SCALPING" else "2" if style.upper()=="INTRADAY" else "3"
            )])
            max_style_trades = acct_settings.get_max_trades_for_style(style) or 3
            if style_trades_count >= max_style_trades:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Max {style} trades capai limit ({style_trades_count}/{max_style_trades})")
                supabase.client.table("signals").update({"is_active": False, "reason": f"Max {style} trades reached"}).eq("id", sig_id).execute()
                continue

            # 3. Allow Hedging Check
            # Jika hedging tidak dibenarkan, check adakah ada posisi berlawanan
            if not getattr(acct_settings, "allow_hedging", True):
                opposite = "SELL" if action == "BUY" else "BUY"
                has_opposite = any(p["direction"] == opposite for p in open_positions if p["symbol"] == sym)
                if has_opposite:
                    logger.warning(f"[{acc}] Signal {action} dibatalkan: Hedging tidak dibenarkan dan ada posisi {opposite} aktif.")
                    supabase.client.table("signals").update({"is_active": False, "reason": "Hedging disabled"}).eq("id", sig_id).execute()
                    continue

            # 4. Block Asia Session Check
            if getattr(acct_settings, "block_asia_session", False) and is_asia:
                logger.warning(f"[{acc}] Signal {action} digantung: Asia Session sedang aktif.")
                # Kita tidak matikan is_active, supaya ia boleh berjalan bila session tamat jika masih valid, atau analyzer ganti baru.
                # Tapi elok matikan saja sebab signal boleh lapuk.
                supabase.client.table("signals").update({"is_active": False, "reason": "Asia Session Blocked"}).eq("id", sig_id).execute()
                continue

            # 5. Block News Check
            # Tetapan Supabase "trade_during_events" -> True maksudnya BOLEH trade masa news. 
            # Jika False, maksudnya Block News Entries = Enabled
            trade_during_events = getattr(acct_settings, "trade_during_events", True)
            if not trade_during_events and is_news:
                logger.warning(f"[{acc}] Signal {action} digantung: High-Impact News sedang aktif.")
                supabase.client.table("signals").update({"is_active": False, "reason": "High-Impact News Blocked"}).eq("id", sig_id).execute()
                continue

            # 6. Check Global Max Trades
            if current_trades_count >= max_trades:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Max total trades ({current_trades_count}/{max_trades})")
                supabase.client.table("signals").update({"is_active": False, "reason": "Max global trades reached"}).eq("id", sig_id).execute()
                continue
                
            # 7. Check Max Drawdown
            if current_dd >= max_dd:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Max drawdown harian capai ({current_dd:.1f}% >= {max_dd}%)")
                supabase.client.table("signals").update({"is_active": False, "reason": "Max drawdown reached"}).eq("id", sig_id).execute()
                continue
                
            # 8. Check AI Confidence
            if confidence < min_conf:
                logger.warning(f"[{acc}] Signal {action} dibatalkan: Confidence AI terlalu rendah ({confidence}% < {min_conf}%)")
                supabase.client.table("signals").update({"is_active": False, "reason": "Low confidence"}).eq("id", sig_id).execute()
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
            lot_size = acct_settings.get_lot_for_style(style) or 0.01
            logger.info(f"🚀 [{acc}] Risk Guard LULUS! Eksekusi {action} pada {sym} dengan Lot: {lot_size}")
            
            res_trade = connector.open_trade(action, lot_size, sl=0, tp=0, symbol=sym, comment=f"AI_{style}")
            if res_trade:
                logger.success(f"✅ [{acc}] Berjaya membuka {action} {sym}")
                supabase.client.table("signals").update({"is_active": False, "reason": "Executed successfully"}).eq("id", sig_id).execute()
                current_trades_count += 1
            else:
                logger.error(f"❌ [{acc}] Gagal membuka {action} {sym}")
                
    except Exception as e:
        logger.error(f"Signal Executor error for {acc}: {e}")
"""

# Replace the old function
content = re.sub(r'def loop_signal_executor.*?(?=def loop_evaluator)', new_executor_code, content, flags=re.DOTALL)

with open("Bot Engine/trade_evaluator.py", "w", encoding="utf-8") as f:
    f.write(content)

print("V2 Risk Guard patched successfully!")
