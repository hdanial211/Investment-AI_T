import sys
import os
import requests
import json

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "Bot Engine"))
import config

url = config.SUPABASE_URL.rstrip("/") + "/rest/v1/active_trades?select=ticket,symbol,account_id,current_status"
headers = {
    "apikey": config.SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {config.SUPABASE_ANON_KEY}"
}
res = requests.get(url, headers=headers)
print(json.dumps(res.json(), indent=2))
