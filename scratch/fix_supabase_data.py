import sys
import os
import json
import requests

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "Bot Engine"))
import config
from account_settings import get_all_enabled_accounts, AccountSettings

def fix_db():
    base_url = config.SUPABASE_URL.rstrip("/")
    headers = {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    
    # Get all active accounts and their symbols
    acc_symbols = {}
    for acc in get_all_enabled_accounts():
        s = AccountSettings(acc)
        acc_symbols[acc] = s.get_symbols()
    print("Account Symbols Map:", acc_symbols)

    # Fetch trades
    res = requests.get(f"{base_url}/rest/v1/active_trades?select=ticket,symbol,account_id", headers=headers)
    trades = res.json()
    
    updates = 0
    for t in trades:
        t_id = t["ticket"]
        t_sym = t["symbol"]
        t_acc = t["account_id"]
        
        # Check if symbol belongs to current account
        if t_acc in acc_symbols and t_sym in acc_symbols[t_acc]:
            continue # all good
            
        # Find correct account
        correct_acc = None
        for acc, syms in acc_symbols.items():
            if t_sym in syms:
                if correct_acc is None:
                    correct_acc = acc
                else:
                    # Multiple accounts trade this symbol... Can't auto-resolve easily, but we'll pick first
                    pass
                    
        if correct_acc and correct_acc != t_acc:
            print(f"Fixing Ticket {t_id}: {t_sym} from {t_acc} -> {correct_acc}")
            payload = {"account_id": correct_acc}
            requests.patch(f"{base_url}/rest/v1/active_trades?ticket=eq.{t_id}", headers=headers, json=payload)
            updates += 1
            
    print(f"Fixed {updates} trades.")

if __name__ == "__main__":
    fix_db()
