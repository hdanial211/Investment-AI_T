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

class TickSimulator:
    def __init__(self, df_m1):
        self.df_m1 = df_m1
        # Make a copy so we don't modify the original
        self.df_m1 = self.df_m1.copy()
        
        if 'time' in self.df_m1.columns:
            self.df_m1.set_index('time', inplace=True)
            
        self.total_ticks = len(self.df_m1)
        self.current_idx = 0
        
        # Pre-resample history for fast lookup
        self.history = {}
        tfs = {'M5': '5min', 'M15': '15min', 'M30': '30min', 'H1': '1h', 'H4': '4h'}
        for name, pd_freq in tfs.items():
            resampled = self.df_m1.resample(pd_freq).agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            self.history[name] = resampled
            
    def get_current_time(self):
        if self.current_idx >= self.total_ticks:
            return self.df_m1.index[-1]
        return self.df_m1.index[self.current_idx]

    def get_candle(self, tf_name='H1'):
        if self.current_idx >= self.total_ticks:
            return None
            
        current_time = self.df_m1.index[self.current_idx]
        
        if tf_name == 'M1':
            row = self.df_m1.iloc[self.current_idx]
            return {
                'time': int(current_time.timestamp()),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume'])
            }
            
        pd_freq = {'M5': '5min', 'M15': '15min', 'M30': '30min', 'H1': '1h', 'H4': '4h'}.get(tf_name, '1h')
        t_start = current_time.floor(pd_freq)
        
        forming_m1 = self.df_m1.loc[t_start:current_time]
        if forming_m1.empty:
            return None
            
        return {
            'time': int(t_start.timestamp()),
            'open': float(forming_m1['open'].iloc[0]),
            'high': float(forming_m1['high'].max()),
            'low': float(forming_m1['low'].min()),
            'close': float(forming_m1['close'].iloc[-1]),
            'volume': float(forming_m1['volume'].sum())
        }
        
    def get_mdf(self):
        current_time = self.df_m1.index[self.current_idx]
        mdf = {}
        tfs = {'M1': '1min', 'M5': '5min', 'M15': '15min', 'M30': '30min', 'H1': '1h', 'H4': '4h'}
        for name, pd_freq in tfs.items():
            if name == 'M1':
                mdf['M1'] = self.df_m1.iloc[:self.current_idx+1].copy()
                continue
                
            t_start = current_time.floor(pd_freq)
            past_df = self.history[name].loc[:t_start - pd.Timedelta('1min')].copy()
            
            forming_m1 = self.df_m1.loc[t_start:current_time]
            if not forming_m1.empty:
                current_row = pd.DataFrame([{
                    'time': t_start,
                    'open': forming_m1['open'].iloc[0],
                    'high': forming_m1['high'].max(),
                    'low': forming_m1['low'].min(),
                    'close': forming_m1['close'].iloc[-1],
                    'volume': forming_m1['volume'].sum()
                }]).set_index('time')
                mdf[name] = pd.concat([past_df, current_row])
            else:
                mdf[name] = past_df
                
        return mdf

# Global State
sim = None
sim_state = {
    "is_ready": False,
    "symbol": "XAUUSD",
    "balance": 10000.0,
    "open_trades": [],
    "history": [],
    "ai_logs": [],
    "trade_mode": "INTRADAY"
}

def load_data_yfinance(symbol: str, days: int = 60) -> pd.DataFrame:
    yf_sym = symbol
    if "USD" in symbol and symbol not in ["EURUSD", "GBPUSD"]:
        yf_sym = f"{symbol}=X"
    if "XAUUSD" in symbol:
        yf_sym = "GC=F"
        
    start_date = datetime.now() - timedelta(days=days)
    df = yf.download(yf_sym, start=start_date.strftime('%Y-%m-%d'), interval="1m", progress=False)
    if df.empty:
        return None
        
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    df.index.name = 'time'
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    
    if 'volume' not in df.columns:
        df['volume'] = 0
    if 'spread' not in df.columns:
        df['spread'] = 0.0002
        
    df['time'] = pd.to_datetime(df['time'], utc=True).dt.tz_localize(None)
    return df

def load_data_mt5(symbol: str, days: int) -> pd.DataFrame:
    if not HAS_BOT_ENGINE:
        return None
        
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
        
    mt5_tf = mt5.TIMEFRAME_M1
    bars = 1440 * days
    
    logger.info(f"Connecting to MT5 to download {bars} bars of M1 data for {symbol}...")
    print(f"\n[MT5] Downloading {bars} M1 bars for {symbol} ({days} days)... Please wait.")
    
    if not mt5.initialize():
        print("[MT5] Error: Could not initialize MT5. Is it open?")
        return None
        
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"[MT5] Error: Symbol '{symbol}' not found in your MT5 broker! Check Market Watch for the exact name (e.g., GOLD, XAUUSD.m).")
        mt5.shutdown()
        return None
        
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, bars)
    mt5.shutdown()
    
    if rates is None or len(rates) == 0:
        print("[MT5] Error: MT5 returned no data.")
        return None
        
    print(f"[MT5] Successfully downloaded {len(rates)} bars!")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    if "spread" not in df.columns:
        df["spread"] = 0
    return df

@app.route("/")
def index():
    resp = app.send_static_file("index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/api/init", methods=["POST"])
def init_simulation():
    global sim
    data = request.json or {}
    symbol = data.get("symbol", "XAUUSD")
    days = int(data.get("days", 30))
    mode = data.get("mode", "INTRADAY")
    source = data.get("source", "mt5")
    
    config.TRADING_MODE = mode
    
    if source == "mt5":
        df = load_data_mt5(symbol, days)
        if df is None or df.empty:
            df = load_data_yfinance(symbol, min(days, 7)) # yfinance 1m is limited to 7 days
    else:
        df = load_data_yfinance(symbol, min(days, 7))
        
    if df is None or df.empty:
        return jsonify({"success": False, "error": "No data found. Note: yfinance 1m data is limited to 7 days."})
        
    sim = TickSimulator(df)
    
    # Start the simulation index after 2 days (2880 M1 bars) 
    # to ensure there is enough historical data to show on the graph
    start_offset = min(2880, max(0, sim.total_ticks - 1440))
    sim.current_idx = start_offset
    
    sim_state["symbol"] = symbol
    sim_state["balance"] = 10000.0
    sim_state["open_trades"] = []
    sim_state["history"] = []
    sim_state["ai_logs"] = []
    sim_state["trade_mode"] = mode
    sim_state["is_ready"] = True
    
    return jsonify({
        "success": True, 
        "total_bars": sim.total_ticks,
        "symbol": symbol,
        "first_time": sim.df_m1.index[0].isoformat(),
        "last_time": sim.df_m1.index[-1].isoformat()
    })

def simulate_trade_execution(row, ind, ai_action):
    pip_size = config.get_pip_multiplier(sim_state["symbol"])
    price = float(row['close'])
    
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
        "open_time": row['time'].isoformat() if isinstance(row['time'], datetime) else str(row['time']),
        "profit": 0.0,
        "status": "OPEN"
    }
    sim_state["open_trades"].append(trade)
    return trade

def manage_open_trades(price, time_str):
    events = []
    still_open = []
    
    for trade in sim_state["open_trades"]:
        closed = False
        reason = ""
        
        if trade["action"] == "BUY":
            if price <= trade["sl"]:
                closed = True
                reason = "SL"
                close_price = trade["sl"]
            elif price >= trade["tp"]:
                closed = True
                reason = "TP"
                close_price = trade["tp"]
            else:
                trade["profit"] = (price - trade["open_price"]) * 10000 
        else:
            if price >= trade["sl"]:
                closed = True
                reason = "SL"
                close_price = trade["sl"]
            elif price <= trade["tp"]:
                closed = True
                reason = "TP"
                close_price = trade["tp"]
            else:
                trade["profit"] = (trade["open_price"] - price) * 10000
                
        if closed:
            trade["close_time"] = time_str
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

@app.route("/api/history", methods=["GET"])
def get_history():
    global sim
    if not sim_state["is_ready"] or sim is None:
        return jsonify({"success": False, "error": "Not initialized"})
        
    req_tf = request.args.get('tf', 'H1')
    
    # We need the completed history up to current_idx
    # The mdf dict has exactly what we need!
    mdf = sim.get_mdf()
    df_tf = mdf.get(req_tf)
    
    if df_tf is None or df_tf.empty:
        return jsonify({"success": True, "candles": []})
        
    # Convert to lightweight charts format
    candles = []
    for t, row in df_tf.iterrows():
        candles.append({
            "time": int(t.timestamp()),
            "open": float(row['open']),
            "high": float(row['high']),
            "low": float(row['low']),
            "close": float(row['close'])
        })
        
    return jsonify({"success": True, "candles": candles})

@app.route("/api/next_bar", methods=["GET"])
def next_bar():
    global sim
    if not sim_state["is_ready"] or sim is None:
        return jsonify({"success": False, "error": "Not initialized"})
        
    req_tf = request.args.get('tf', 'M1')
    
    if sim.current_idx >= sim.total_ticks:
        return jsonify({"success": True, "done": True})
        
    # Get current M1 row for internal logic
    current_time = sim.get_current_time()
    m1_row = sim.df_m1.iloc[sim.current_idx]
    current_price = float(m1_row['close'])
    time_str = current_time.isoformat()
    
    events = []
    
    # 1. Manage open trades using M1 price (high precision)
    trade_events = manage_open_trades(current_price, time_str)
    events.extend(trade_events)
    
    # 2. Extract current forming candle for frontend based on requested TF
    candle = sim.get_candle(req_tf)
    
    # 3. Strategy Logic (Execute once per new H1 candle close? Or M15?)
    # To save CPU, we only run AI logic on the close of an M15 bar
    ai_event = None
    is_m5_close = (sim.current_idx % 5 == 0) and sim.current_idx > 0
    
    if is_m5_close and len(sim_state["open_trades"]) == 0:
        if not HAS_BOT_ENGINE:
            ai_event = {"type": "AI_DECISION", "action": "ERROR", "reason": "HAS_BOT_ENGINE is False (ImportError)", "time": time_str}
        else:
            mdf = sim.get_mdf()
            try:
                ind = calculate_multi_indicators(mdf, sim_state["symbol"])
                if not ind:
                    ai_event = {"type": "AI_DECISION", "action": "SKIP", "reason": "Not enough data for indicators", "time": time_str}
                else:
                    h1_adx = ind.get("adx", 0)
                    if h1_adx > 15:
                        if config.AI_PROVIDER != "":
                            ai_response = get_ai_signal(ind, current_price, current_price, None, sim_state["symbol"])
                            final_action = ai_response.get("action", "HOLD")
                            reason = ai_response.get("reason", "")
                            
                            ai_event = {"type": "AI_DECISION", "action": final_action, "reason": reason, "time": time_str}
                            
                            if final_action in ["BUY", "SELL"]:
                                trade = simulate_trade_execution({'close': current_price, 'time': time_str}, ind, final_action)
                                events.append({"type": "TRADE_OPEN", "trade": trade})
                        else:
                            ai_event = {"type": "AI_DECISION", "action": "ERROR", "reason": "AI_PROVIDER is empty", "time": time_str}
                    else:
                        ai_event = {"type": "AI_DECISION", "action": "SKIP", "reason": f"ADX ({h1_adx}) is too low (<15)", "time": time_str}
            except Exception as e:
                logger.error(f"Error in strategy: {e}")
                ai_event = {"type": "AI_DECISION", "action": "ERROR", "reason": f"Exception: {e}", "time": time_str}

    if ai_event:
        events.append(ai_event)

    # Advance tick for next call
    sim.current_idx += 1

    return jsonify({
        "success": True,
        "done": False,
        "candle": candle,
        "events": events,
        "balance": sim_state["balance"],
        "open_trades_count": len(sim_state["open_trades"]),
        "current_idx": sim.current_idx
    })

if __name__ == "__main__":
    if HAS_BOT_ENGINE:
        system_settings.fetch_and_apply_system_settings()
        
    print("="*60)
    print("Visual Backtest Server Running!")
    print("Open your browser to: http://127.0.0.1:5000")
    print("="*60)
    app.run(host="127.0.0.1", port=5000, debug=False)
