import sys
import os
import json
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "Bot Engine"))
from trade_management.supabase_sync import SupabaseSync

sync = SupabaseSync()

print("--- ACTIVE TRADES ---")
active = sync.client.table("active_trades").select("ticket, symbol, account_id, current_status").eq("current_status", "OPEN").execute()
for t in active.data:
    print(t)

print("--- CLOSED TRADES ---")
closed = sync.client.table("active_trades").select("ticket, symbol, account_id, current_status").eq("current_status", "CLOSED").order("updated_at", desc=True).limit(20).execute()
for t in closed.data:
    print(t)
