import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from trade_management.supabase_sync import SupabaseSync

supabase = SupabaseSync()
url = f"{supabase.base_url}/rest/v1/account_settings?limit=1"
import requests
response = requests.get(url, headers=supabase.headers)
if response.status_code == 200:
    data = response.json()
    if data:
        print("Providers list for account 0:")
        import json
        print(json.dumps(data[0].get("providers_list", {}), indent=2))
        print("Providers list for all accounts:")
        for r in data:
            print(r.get("account_id"), "->", r.get("providers_list"))
    else:
        print("Table is empty.")
else:
    print(f"Error: {response.text}")
