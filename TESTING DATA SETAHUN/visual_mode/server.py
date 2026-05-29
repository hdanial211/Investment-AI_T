import os
import sys
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import yfinance as yf

# Insert Bot Engine path
VISUAL_DIR = os.path.dirname(os.path.abspath(__file__))
TESTING_DIR = os.path.dirname(VISUAL_DIR)
PROJECT_DIR = os.path.dirname(TESTING_DIR)
BOT_DIR = os.path.join(PROJECT_DIR, "Bot Engine")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

# Import Bot Engine modules
try:
    import config
    from strategy import calculate_multi_indicators
    from ai_engine import get_ai_signal
    import system_settings
    HAS_BOT_ENGINE = True
except ImportError as e:
    HAS_BOT_ENGINE = False
    logging.error(f"Failed to load Bot Engine: {e}")

app = Flask(__name__, static_url_path='', static_folder='static')
CORS(app)
logger = logging.getLogger("VisualTester")

# State variables
sim_state = {
    "is_ready": False,
    "symbol": "XAUUSD",
    "tf": "H1",
    "df": None,
    "total_bars": 0,
    "current_index": 0,
    "balance": 10000.0,
    "open_trades": [],
    "history": [],
    "ai_logs": [],
    "trade_mode": "INTRADAY"
}

def load_data_yfinance(symbol: str, days: int = 60, interval: str = "1h") -> pd.DataFrame:
    yf_sym = symbol
    if "USD" in symbol and symbol not in ["EURUSD", "GBPUSD"]:
        yf_sym = f"{symbol}=X"
    if "XAUUSD" in symbol:
        yf_sym = "GC=F"
        
    start_date = datetime.now() - timedelta(days=days)
    df = yf.download(yf_sym, start=start_date.strftime('%Y-%m-%d'), interval=interval, progress=False)
    if df.empty:
        return None
        
    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    df.index.name = 'time'
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    
    # Fill missing columns
    if 'volume' not in df.columns:
        df['volume'] = 0
    if 'spread' not in df.columns:
        df['spread'] = 0.0002
        
    # Convert 'time' to naive datetime (UTC) to avoid JSON serialization issues
    df['time'] = pd.to_datetime(df['time'], utc=True).dt.tz_localize(None)
    
    return df

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/api/init", methods=["POST"])
def init_simulation():
    data = request.json or {}
    symbol = data.get("symbol", "XAUUSD")
    days = int(data.get("days", 30))
    tf = data.get("timeframe", "1h")
    mode = data.get("mode", "INTRADAY")
    
    config.TRADING_MODE = mode
    
    df = load_data_yfinance(symbol, days, tf)
    if df is None or df.empty:
        return jsonify({"success": False, "error": "No data found for symbol."})
        
    # Reset state
    sim_state["symbol"] = symbol
    sim_state["tf"] = tf
    sim_state["df"] = df
    sim_state["total_bars"] = len(df)
    sim_state["current_index"] = 0
    sim_state["balance"] = 10000.0
    sim_state["open_trades"] = []
    sim_state["history"] = []
    sim_state["ai_logs"] = []
    sim_state["trade_mode"] = mode
    sim_state["is_ready"] = True
    
    return jsonify({
        "success": True, 
        "total_bars": len(df),
        "symbol": symbol,
        "first_time": df.iloc[0]['time'].isoformat(),
        "last_time": df.iloc[-1]['time'].isoformat()
    })

def simulate_trade_execution(row, ind, ai_action):
    pip_size = config.get_pip_multiplier(sim_state["symbol"])
    price = float(row['close'])
    
    # Mocking SL/TP
    sl_pips = 50
    tp_pips = 100
    
    if ai_action == "BUY":
        sl = price - (sl_pips * pip_size)
        tp = price + (tp_pips * pip_size)
    else:
        sl = price + (sl_pips * pip_size)
        tp = price - (tp_pips * pip_size)
        
    trade = {
        "id": len(sim_state["history"]) + len(sim_state["open_trades"]) + 1,
        "action": ai_action,
        "open_price": price,
        "sl": sl,
        "tp": tp,
        "open_time": row['time'].isoformat(),
        "profit": 0.0,
        "status": "OPEN"
    }
    sim_state["open_trades"].append(trade)
    return trade

def manage_open_trades(row):
    high = float(row['high'])
    low = float(row['low'])
    close = float(row['close'])
    events = []
    still_open = []
    
    for trade in sim_state["open_trades"]:
        closed = False
        reason = ""
        
        # Check SL/TP
        if trade["action"] == "BUY":
            if low <= trade["sl"]:
                closed = True
                reason = "SL"
                close_price = trade["sl"]
            elif high >= trade["tp"]:
                closed = True
                reason = "TP"
                close_price = trade["tp"]
            else:
                trade["profit"] = (close - trade["open_price"]) * 10000 # Mock pip value
        else:
            if high >= trade["sl"]:
                closed = True
                reason = "SL"
                close_price = trade["sl"]
            elif low <= trade["tp"]:
                closed = True
                reason = "TP"
                close_price = trade["tp"]
            else:
                trade["profit"] = (trade["open_price"] - close) * 10000
                
        if closed:
            trade["close_time"] = row['time'].isoformat()
            trade["close_price"] = close_price
            if trade["action"] == "BUY":
                trade["profit"] = (close_price - trade["open_price"]) * 10000
            else:
                trade["profit"] = (trade["open_price"] - close_price) * 10000
                
            trade["status"] = "CLOSED"
            trade["reason"] = reason
            sim_state["balance"] += trade["profit"]
            sim_state["history"].append(trade)
            events.append({"type": "TRADE_CLOSE", "trade": trade})
        else:
            still_open.append(trade)
            
    sim_state["open_trades"] = still_open
    return events

@app.route("/api/next_bar", methods=["GET"])
def next_bar():
    if not sim_state["is_ready"]:
        return jsonify({"success": False, "error": "Not initialized"})
        
    idx = sim_state["current_index"]
    if idx >= sim_state["total_bars"]:
        return jsonify({"success": True, "done": True})
        
    df = sim_state["df"]
    row = df.iloc[idx]
    sim_state["current_index"] += 1
    
    events = []
    
    # 1. Manage open trades
    trade_events = manage_open_trades(row)
    events.extend(trade_events)
    
    # 2. Extract current OHLC for frontend
    candle = {
        "time": int(row['time'].timestamp()), # TV charts use unix timestamp
        "open": float(row['open']),
        "high": float(row['high']),
        "low": float(row['low']),
        "close": float(row['close']),
        "volume": float(row.get('volume', 0))
    }
    
    # 3. Strategy Logic (Simplified for Visualizer if MTF is unavailable)
    # Reconstruct history up to current index
    history_slice = df.iloc[:idx+1]
    
    ai_event = None
    # Very basic trigger to prevent querying AI on every bar
    # Only query if we have a sharp move or cross
    trigger_ai = False
    
    if len(history_slice) >= 21 and len(sim_state["open_trades"]) == 0:
        ema9 = history_slice['close'].ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = history_slice['close'].ewm(span=21, adjust=False).mean().iloc[-1]
        prev_ema9 = history_slice['close'].ewm(span=9, adjust=False).mean().iloc[-2]
        prev_ema21 = history_slice['close'].ewm(span=21, adjust=False).mean().iloc[-2]
        
        cross_up = prev_ema9 < prev_ema21 and ema9 >= ema21
        cross_down = prev_ema9 > prev_ema21 and ema9 <= ema21
        
        if cross_up or cross_down:
            trigger_ai = True
            
            # Construct mock MTF dict
            mdf = {"H1": history_slice.copy()}
            if HAS_BOT_ENGINE:
                try:
                    ind = calculate_multi_indicators(mdf, sim_state["symbol"])
                    if ind:
                        action = "BUY" if cross_up else "SELL"
                        sim_state["ai_logs"].append(f"[{row['time']}] Potential {action} Setup detected. Querying AI...")
                        
                        # In visual mode, we might want to MOCK the AI delay or actually call it
                        # If we actually call it, it will be slow, which is cool for visual mode!
                        if config.AI_PROVIDER != "":
                            ai_response = get_ai_signal(ind, float(row['close']), float(row['close']), None, sim_state["symbol"])
                            final_action = ai_response.get("action", "HOLD")
                            reason = ai_response.get("reason", "")
                            
                            sim_state["ai_logs"].append(f"[{row['time']}] AI Decision: {final_action}. Reason: {reason}")
                            ai_event = {"type": "AI_DECISION", "action": final_action, "reason": reason, "time": row['time'].isoformat()}
                            
                            if final_action in ["BUY", "SELL"]:
                                trade = simulate_trade_execution(row, ind, final_action)
                                events.append({"type": "TRADE_OPEN", "trade": trade})
                except Exception as e:
                    logger.error(f"Error in strategy: {e}")
                    sim_state["ai_logs"].append(f"[{row['time']}] Error: {e}")

    if ai_event:
        events.append(ai_event)

    return jsonify({
        "success": True,
        "done": False,
        "candle": candle,
        "events": events,
        "balance": sim_state["balance"],
        "open_trades_count": len(sim_state["open_trades"])
    })

if __name__ == "__main__":
    # Initialize Supabase Keys if available
    if HAS_BOT_ENGINE:
        system_settings.fetch_and_apply_system_settings()
        
    print("="*60)
    print("Visual Backtest Server Running!")
    print("Open your browser to: http://127.0.0.1:5000")
    print("="*60)
    app.run(host="127.0.0.1", port=5000, debug=False)
