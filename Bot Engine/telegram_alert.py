import os
import time
import requests
from dotenv import load_dotenv
from trade_management.supabase_sync import SupabaseSync

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

def send_telegram_message(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase credentials missing.")
        return
        
    print("Telegram Alert Service started.")
    db = SupabaseSync()
    
    last_checked_signals = set()
    last_checked_trades = set()
    
    while True:
        try:
            # Check for new signals
            signals = db.table("market_signals").select("*").order("created_at", desc=True).limit(5).execute()
            if signals and hasattr(signals, 'data'):
                for s in signals.data:
                    if s['id'] not in last_checked_signals:
                        last_checked_signals.add(s['id'])
                        msg = f"🔔 <b>NEW AI SIGNAL</b>\n\n<b>Symbol:</b> {s['symbol']}\n<b>Action:</b> {s['action']}\n<b>Style:</b> {s['trade_style']}\n<b>Confidence:</b> {s.get('confidence', 0)*100:.1f}%"
                        send_telegram_message(msg)
            
            # Limit set size
            if len(last_checked_signals) > 100:
                last_checked_signals.clear()
                
            time.sleep(10)
        except Exception as e:
            print(f"Error checking updates: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
