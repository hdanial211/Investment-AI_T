import sys
import re

path = r'E:\PROJECTS\SAHAM\Investment-AI_T_latest\Bot Engine\trade_evaluator.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Import query_ai_provider and json
if 'from ai_engine import query_ai_provider' not in content:
    content = content.replace('from ai_engine import get_ai_signal', 'from ai_engine import get_ai_signal, query_ai_provider\nimport json')

# 2. Add evaluate_pending_manual_trades function before main()
new_func = """
def evaluate_pending_manual_trades(supabase: SupabaseSync, connector: MT5Connector, account_id: str, acct_settings: AccountSettings):
    active_trades = supabase.fetch_active_trades(account_id)
    if not active_trades: return
    pending_manuals = [t for t in active_trades if t.get("current_status") == "OPEN" and t.get("trade_style") == "MANUAL_PENDING_AI"]
    
    if not pending_manuals:
        return
        
    for p in pending_manuals:
        ticket = p.get("ticket")
        symbol = p.get("symbol")
        direction = p.get("direction")
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
"""

if 'def evaluate_pending_manual_trades' not in content:
    content = content.replace('def main():', new_func)

# 3. Call it inside main loop
if 'evaluate_pending_manual_trades(' not in content:
    target = 'sync_active_trades_from_mt5(supabase, connector, account_id)'
    replacement = target + '\\n        evaluate_pending_manual_trades(supabase, connector, account_id, acct_settings)'
    content = content.replace(target, replacement)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied to trade_evaluator.py successfully.")
