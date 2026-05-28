import sys, os, requests, json
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "Bot Engine"))
import config

url = config.SUPABASE_URL.rstrip("/") + "/rest/v1/pattern_usage_stats?select=*&limit=1"
headers = {"apikey": config.SUPABASE_ANON_KEY, "Authorization": f"Bearer {config.SUPABASE_ANON_KEY}"}
res = requests.get(url, headers=headers)
print(json.dumps(res.json(), indent=2))
