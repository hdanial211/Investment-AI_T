import re

with open("Bot Engine/trade_evaluator.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add 'import requests' to the top if not present
if "import requests" not in content:
    content = "import requests\n" + content

# 2. Replace fetching signals
old_fetch = 'res = supabase.client.table("signals").select("*").eq("account_id", acc).eq("is_active", True).execute()\n        signals = res.data if res else []'
new_fetch = """url = f"{supabase.base_url}/rest/v1/signals?account_id=eq.{acc}&is_active=eq.true"
        resp = requests.get(url, headers=supabase.headers)
        signals = resp.json() if resp.status_code == 200 else []"""
content = content.replace(old_fetch, new_fetch)

# 3. Replace all update statements
# Old format: supabase.client.table("signals").update({"is_active": False, "reason": f"Style {style} disabled"}).eq("id", sig_id).execute()
def replace_update(match):
    json_payload = match.group(1)
    return f'requests.patch(f"{{supabase.base_url}}/rest/v1/signals?id=eq.{{sig_id}}", headers=supabase.headers, json={json_payload})'

content = re.sub(r'supabase\.client\.table\("signals"\)\.update\((.*?)\)\.eq\("id", sig_id\)\.execute\(\)', replace_update, content)

with open("Bot Engine/trade_evaluator.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Evaluator Supabase client patched successfully!")
