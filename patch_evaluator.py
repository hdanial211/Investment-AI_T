import sys
import os

with open("Bot Engine/trade_evaluator.py", "r", encoding="utf-8") as f:
    content = f.read()

executor_code = """
import MetaTrader5 as mt5

def loop_signal_executor(supabase: SupabaseSync, connector: MT5Connector, acc: str, acct_settings: AccountSettings):
    try:
        if not connector.is_connected(): return
        
        # 1. Fetch active signals
        res = supabase.client.table("signals").select("*").eq("account_id", acc).eq("is_active", True).execute()
        signals = res.data if res else []
        if not signals: return
        
        # 2. Risk Management
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
        
        for sig in signals:
            sym = sig.get("symbol", "XAUUSD")
            action = sig.get("action", "")
            style = sig.get("trade_style", "UNKNOWN")
            confidence = sig.get("confidence_score", 0)
            sig_id = sig.get("id")
            
            # Risk Guard
            if current_trades_count >= max_trades:
                logger.warning(f"[{acc}] Signal {action} ignored: Max trades ({current_trades_count}/{max_trades})")
                supabase.client.table("signals").update({"is_active": False}).eq("id", sig_id).execute()
                continue
                
            if current_dd >= max_dd:
                logger.warning(f"[{acc}] Signal {action} ignored: Max drawdown ({current_dd:.1f}% >= {max_dd}%)")
                supabase.client.table("signals").update({"is_active": False}).eq("id", sig_id).execute()
                continue
                
            if confidence < min_conf:
                logger.warning(f"[{acc}] Signal {action} ignored: Low confidence ({confidence}% < {min_conf}%)")
                supabase.client.table("signals").update({"is_active": False}).eq("id", sig_id).execute()
                continue
                
            sym_info = mt5.symbol_info(sym)
            if not sym_info: continue
            spread = sym_info.spread
            if spread > max_spread:
                logger.warning(f"[{acc}] Signal {action} ignored: Spread too high ({spread} > {max_spread})")
                # Do not deactivate, maybe spread will drop within 10 mins
                continue
                
            # Execute Entry
            lot_size = acct_settings.get_lot_for_style(style) or 0.01
            logger.info(f"🚀 [{acc}] Executing {action} on {sym} with Lot: {lot_size}")
            
            # Call open_trade
            res_trade = connector.open_trade(action, lot_size, sl=0, tp=0, symbol=sym, comment=f"AI_{style}")
            if res_trade:
                logger.success(f"✅ [{acc}] Successfully opened {action} {sym}")
                supabase.client.table("signals").update({"is_active": False}).eq("id", sig_id).execute()
                current_trades_count += 1
            else:
                logger.error(f"❌ [{acc}] Failed to open {action} {sym}")
                
    except Exception as e:
        logger.error(f"Signal Executor error for {acc}: {e}")

"""

if "def loop_signal_executor" not in content:
    content = content.replace("def loop_evaluator", executor_code + "def loop_evaluator")
    
    # Also patch the while loop in main()
    # We want a fast loop for signal execution (every 5 seconds)
    # The current loop has time.sleep(5)
    
    old_loop = """        # Evaluator Loop (Setiap 10 minit / 600s)
        # Boleh laras jika nak cepat, contohnya 300s (5 minit)
        if now - last_eval_time >= 600:
            sync_active_trades_from_mt5(supabase, connector, account_id)
            loop_evaluator(supabase, connector, account_id)
            last_eval_time = now"""
            
    new_loop = """        # Executor Loop (Setiap 5 saat)
        loop_signal_executor(supabase, connector, account_id, acct_settings)
        
        # Evaluator Loop (Setiap 10 minit / 600s)
        if now - last_eval_time >= 600:
            sync_active_trades_from_mt5(supabase, connector, account_id)
            loop_evaluator(supabase, connector, account_id)
            last_eval_time = now"""
            
    content = content.replace(old_loop, new_loop)
    
    with open("Bot Engine/trade_evaluator.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("trade_evaluator.py updated successfully!")
else:
    print("Already patched.")
