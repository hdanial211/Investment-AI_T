import os, sys, json
sys.path.append('Bot Engine')
import config
from trade_management.supabase_sync import SupabaseSync
sync = SupabaseSync()
url = f"{config.SUPABASE_URL}/rest/v1/active_trades?select=*&current_status=eq.CLOSED&order=updated_at.desc&limit=5"
headers = {
    "apikey": config.SUPABASE_KEY,
    "Authorization": f"Bearer {config.SUPABASE_KEY}",
    "Content-Type": "application/json"
}
import requests
resp = requests.get(url, headers=headers)
for r in resp.json():
    print(f"Ticket: {r.get('ticket')}, Exit: {r.get('exit_reason')}, Profit: {r.get('floating_profit')}")
