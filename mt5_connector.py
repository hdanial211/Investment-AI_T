"""
mt5_connector.py - MetaTrader 5 Connection & Trade Execution Module

Responsibilities:
- Initialize and maintain MT5 connection
- Login with account credentials
- Fetch live tick data and OHLCV bars
- Place BUY/SELL market orders with SL/TP
- Check open positions
- Handle MT5 errors gracefully
"""

import time
import logging
from typing import Optional, Dict, List, Tuple

import pandas as pd

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = False # Forced demo mode
except ImportError:
    MT5_AVAILABLE = False
    logging.warning("MetaTrader5 package not installed. Running in DEMO mode.")

import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MT5 TIMEFRAME MAP
# ─────────────────────────────────────────────────────────────────────────────
TIMEFRAME_MAP = {
    "M1":  1,   "M5":  5,   "M15": 15,  "M30": 30,
    "H1":  16385, "H4": 16388, "D1": 16408,
}

def _tf(tf_str: str):
    """Convert timeframe string to MT5 constant."""
    if not MT5_AVAILABLE:
        return tf_str
    tf_map = {
        "M1":  mt5.TIMEFRAME_M1,
        "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,
        "D1":  mt5.TIMEFRAME_D1,
    }
    return tf_map.get(tf_str, mt5.TIMEFRAME_M5)


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

class MT5Connector:
    """Handles all MetaTrader 5 operations."""

    def __init__(self):
        self.connected = False
        self._demo_mode = not MT5_AVAILABLE

    # ── CONNECT ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Initialize MT5 terminal and login."""
        if self._demo_mode:
            logger.warning("DEMO MODE: MT5 not available. Using simulated data.")
            self.connected = True
            return True

        try:
            # Initialize MT5 terminal
            init_args = {}
            if config.MT5_PATH:
                init_args["path"] = config.MT5_PATH

            if not mt5.initialize(**init_args):
                logger.error(f"MT5 initialize failed: {mt5.last_error()}")
                return False

            # Login to account
            login_result = mt5.login(
                login    = config.MT5_LOGIN,
                password = config.MT5_PASSWORD,
                server   = config.MT5_SERVER,
            )
            if not login_result:
                err = mt5.last_error()
                logger.error(f"MT5 login failed: {err}")
                mt5.shutdown()
                return False

            account = mt5.account_info()
            logger.info(
                f"MT5 connected | Account: {account.login} | "
                f"Balance: {account.balance:.2f} {account.currency} | "
                f"Broker: {account.company}"
            )
            self.connected = True
            return True

        except Exception as e:
            logger.error(f"MT5 connection exception: {e}")
            return False

    def disconnect(self):
        """Shut down MT5 connection."""
        if not self._demo_mode and MT5_AVAILABLE:
            mt5.shutdown()
        self.connected = False
        logger.info("MT5 disconnected.")

    def ensure_connected(self) -> bool:
        """Reconnect if connection dropped."""
        if not self.connected:
            logger.warning("MT5 not connected. Attempting reconnect...")
            return self.connect()
        if not self._demo_mode:
            if mt5.terminal_info() is None:
                self.connected = False
                return self.connect()
        return True

    # ── ACCOUNT INFO ─────────────────────────────────────────────────────────

    def get_account_info(self) -> Dict:
        """Return account balance, equity, margin."""
        if self._demo_mode:
            return {"balance": 10000.0, "equity": 10000.0, "margin": 0.0, "currency": "USD"}
        info = mt5.account_info()
        if info is None:
            return {}
        return {
            "balance":  info.balance,
            "equity":   info.equity,
            "margin":   info.margin,
            "currency": info.currency,
            "leverage": info.leverage,
        }

    # ── MARKET DATA ──────────────────────────────────────────────────────────

    def get_tick(self, symbol: str) -> Optional[Dict]:
        """Get the latest bid/ask tick for a symbol."""
        if self._demo_mode:
            import random
            base = 1950.0 if "XAU" in symbol else 1.0850
            spread = 0.30 if "XAU" in symbol else 0.0001
            bid = base + random.uniform(-2, 2)
            ask = bid + spread
            return {"bid": round(bid, 5), "ask": round(ask, 5), "symbol": symbol}

        if not self.ensure_connected():
            return None

        # Make sure symbol is selected in Market Watch
        if not mt5.symbol_select(symbol, True):
            logger.error(f"Cannot select symbol {symbol}: {mt5.last_error()}")
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"No tick data for {symbol}: {mt5.last_error()}")
            return None

        return {
            "symbol": symbol,
            "bid":    tick.bid,
            "ask":    tick.ask,
            "time":   tick.time,
        }

    def get_ohlcv(self, symbol: str, timeframe: str = None, bars: int = None) -> Optional[pd.DataFrame]:
        """Fetch OHLCV bars as a DataFrame."""
        tf  = timeframe or config.TIMEFRAME
        n   = bars or config.BARS_TO_FETCH

        if self._demo_mode:
            return self._generate_demo_bars(symbol, n)

        if not self.ensure_connected():
            return None

        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, _tf(tf), 0, n)
        if rates is None or len(rates) == 0:
            logger.error(f"No OHLCV data for {symbol}: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df[["time", "open", "high", "low", "close", "volume"]]

    def _generate_demo_bars(self, symbol: str, n: int) -> pd.DataFrame:
        """Generate realistic demo OHLCV data for testing."""
        import numpy as np
        np.random.seed(42)
        base = 1950.0 if "XAU" in symbol else 1.0850
        closes = base + np.cumsum(np.random.randn(n) * 0.5)
        highs  = closes + np.abs(np.random.randn(n) * 0.3)
        lows   = closes - np.abs(np.random.randn(n) * 0.3)
        opens  = np.roll(closes, 1)
        times  = pd.date_range(end=pd.Timestamp.now(), periods=n, freq="5min")
        return pd.DataFrame({
            "time":   times,
            "open":   opens,
            "high":   highs,
            "low":    lows,
            "close":  closes,
            "volume": np.random.randint(100, 1000, n).astype(float),
        })

    def get_spread_pips(self, symbol: str) -> float:
        """Return current spread in pips."""
        tick = self.get_tick(symbol)
        if not tick:
            return 999.0
        spread = tick["ask"] - tick["bid"]
        # XAU: 1 pip = 0.01 | Forex: 1 pip = 0.0001
        pip_size = 0.01 if "XAU" in symbol or "JPY" in symbol else 0.0001
        return round(spread / pip_size, 1)

    # ── POSITIONS ────────────────────────────────────────────────────────────

    def get_open_positions(self, symbol: str = None) -> List[Dict]:
        """Return list of open positions, optionally filtered by symbol."""
        if self._demo_mode:
            return []  # No demo positions

        if not self.ensure_connected():
            return []

        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if positions is None:
            return []

        result = []
        for p in positions:
            result.append({
                "ticket":     p.ticket,
                "symbol":     p.symbol,
                "type":       "BUY" if p.type == 0 else "SELL",
                "volume":     p.volume,
                "open_price": p.price_open,
                "sl":         p.sl,
                "tp":         p.tp,
                "profit":     p.profit,
                "time":       p.time,
            })
        return result

    def has_open_position(self, symbol: str) -> bool:
        """Check if there's already an open position for this symbol."""
        return len(self.get_open_positions(symbol)) > 0

    # ── ORDER EXECUTION ──────────────────────────────────────────────────────

    def place_order(
        self,
        symbol:    str,
        action:    str,        # "BUY" or "SELL"
        lot:       float,
        sl_price:  float = 0.0,
        tp_price:  float = 0.0,
        comment:   str   = "AI_BOT",
    ) -> Dict:
        """
        Place a market order.
        Returns dict with success flag, ticket, and message.
        """
        if self._demo_mode:
            import random
            ticket = random.randint(100000, 999999)
            logger.info(f"[DEMO] Order placed: {action} {lot} {symbol} | Ticket: {ticket}")
            return {"success": True, "ticket": ticket, "message": "Demo order OK"}

        if not self.ensure_connected():
            return {"success": False, "ticket": None, "message": "MT5 not connected"}

        tick = self.get_tick(symbol)
        if not tick:
            return {"success": False, "ticket": None, "message": "No tick data"}

        # Determine order type and price
        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        price      = tick["ask"] if action == "BUY" else tick["bid"]

        # Get symbol point for deviation calculation
        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            return {"success": False, "ticket": None, "message": f"Symbol info not found: {symbol}"}

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    symbol,
            "volume":    lot,
            "type":      order_type,
            "price":     price,
            "sl":        sl_price,
            "tp":        tp_price,
            "deviation": 20,        # Max price deviation in points
            "magic":     20240101,   # Magic number to identify bot orders
            "comment":   comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None:
            err = mt5.last_error()
            logger.error(f"order_send returned None: {err}")
            return {"success": False, "ticket": None, "message": str(err)}

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                f"Order executed: {action} {lot} {symbol} @ {price:.5f} | "
                f"Ticket: {result.order} | SL: {sl_price:.5f} | TP: {tp_price:.5f}"
            )
            return {"success": True, "ticket": result.order, "message": "Order filled"}
        else:
            msg = f"Order failed: retcode={result.retcode} | {result.comment}"
            logger.error(msg)
            return {"success": False, "ticket": None, "message": msg}

    def close_position(self, ticket: int, symbol: str, lot: float, pos_type: str) -> Dict:
        """Close an existing position by ticket."""
        if self._demo_mode:
            return {"success": True, "message": "Demo close OK"}

        tick = self.get_tick(symbol)
        if not tick:
            return {"success": False, "message": "No tick data"}

        # To close BUY → SELL, to close SELL → BUY
        close_type  = mt5.ORDER_TYPE_SELL if pos_type == "BUY" else mt5.ORDER_TYPE_BUY
        close_price = tick["bid"] if pos_type == "BUY" else tick["ask"]

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       lot,
            "type":         close_type,
            "position":     ticket,
            "price":        close_price,
            "deviation":    20,
            "magic":        20240101,
            "comment":      "AI_BOT_CLOSE",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return {"success": True, "message": f"Position {ticket} closed"}
        return {"success": False, "message": f"Close failed: {result.comment if result else 'None'}"}

    # ── SYMBOL INFO ──────────────────────────────────────────────────────────

    def get_pip_value(self, symbol: str) -> float:
        """Return pip size for the symbol."""
        if "XAU" in symbol or "XAG" in symbol:
            return 0.01
        if "JPY" in symbol:
            return 0.01
        return 0.0001

    def get_contract_size(self, symbol: str) -> float:
        """Return contract size for lot calculation."""
        if self._demo_mode:
            return 100.0 if "XAU" in symbol else 100000.0
        info = mt5.symbol_info(symbol)
        return info.trade_contract_size if info else 100000.0
