import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "Bot Engine", ".env"))

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Missing Supabase credentials in .env")
    sys.exit(1)

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

def update_settings():
    print("Fetching account settings...")
    try:
        url = f"{SUPABASE_URL}/rest/v1/account_settings?select=*"
        resp = requests.get(url, headers=headers)
        
        if resp.status_code != 200:
            print(f"Failed to fetch settings: {resp.text}")
            return
            
        settings = resp.json()
        if not settings:
            print("No account settings found.")
            return

        for row in settings:
            acc_id = row.get("account_id")
            print(f"Updating account: {acc_id}")
            
            updates = {
                "scalping_be_trigger": 0.3,
                "scalping_trail_start": 0.5,
                "scalping_trail_dist": 0.2,
                "scalping_grid_dist": 0.6,
                
                "intraday_be_trigger": 0.5,
                "intraday_trail_start": 1.0,
                "intraday_trail_dist": 0.4,
                "intraday_grid_dist": 1.0,
                
                "swing_be_trigger": 1.0,
                "swing_trail_start": 2.0,
                "swing_trail_dist": 0.8,
                "swing_grid_dist": 2.0,
            }
            
            # Since use_auto_lot might not exist, we will try updating it.
            # If it fails, we will remove it and try again.
            payload_with_lot = dict(updates)
            payload_with_lot["use_auto_lot"] = True
            payload_with_lot["risk_percent"] = 1.0
            
            patch_url = f"{SUPABASE_URL}/rest/v1/account_settings?account_id=eq.{acc_id}"
            
            patch_resp = requests.patch(patch_url, headers=headers, json=payload_with_lot)
            if patch_resp.status_code in [200, 204]:
                print(f"Successfully updated {acc_id} (with Auto Lot columns)")
            else:
                print(f"Failed to update with Auto Lot columns: {patch_resp.text}")
                print("Trying without Auto Lot columns...")
                
                patch_resp_fallback = requests.patch(patch_url, headers=headers, json=updates)
                if patch_resp_fallback.status_code in [200, 204]:
                    print(f"Successfully updated {acc_id} (without Auto Lot columns)")
                else:
                    print(f"Failed to update {acc_id}: {patch_resp_fallback.text}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    update_settings()
