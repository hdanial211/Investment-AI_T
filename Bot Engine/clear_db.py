import os
import sys

# Tambah parent dir supaya boleh import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from trade_management.supabase_sync import SupabaseSync

import requests

def clear_all():
    supabase = SupabaseSync()
    
    # We use a dummy condition that matches everything, like id=not.is.null or ticket=gte.0
    headers = supabase.headers.copy()
    
    print("Clearing 'signals' table...")
    requests.delete(f"{supabase.base_url}/rest/v1/signals?id=not.is.null", headers=headers)
    print("Signals cleared.")
    
    print("Clearing 'active_trades' table...")
    requests.delete(f"{supabase.base_url}/rest/v1/active_trades?ticket=gte.0", headers=headers)
    print("Active trades cleared.")
    
    print("Clearing 'sl_tp_updates' table...")
    requests.delete(f"{supabase.base_url}/rest/v1/sl_tp_updates?id=not.is.null", headers=headers)
    print("SL/TP updates cleared.")
    
    print("Clearing 'mt5_logs' table...")
    requests.delete(f"{supabase.base_url}/rest/v1/mt5_logs?id=not.is.null", headers=headers)
    print("Logs cleared.")
    
    print("DONE! Pangkalan data telah dikosongkan.")

if __name__ == "__main__":
    clear_all()
