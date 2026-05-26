"""
🏆 GOLD AI Trading Algo — MT5 Connector
=========================================
MetaTrader 5 connection manager.
- AUTO-LAUNCHES MT5 terminal if it is not running.
- Connects to an already-running MT5 terminal (just mt5.initialize()).
- Falls back to credential-based login if needed.
- Falls back to DEMO MODE only if MetaTrader5 package is not installed.

Handle: connect, tick data, OHLCV, order execution.
"""

import os
import random
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import pandas as pd
from loguru import logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.warning("DEMO MODE: MT5 not available. Using simulated data.")

import config


# ── MT5 Auto-Launch Helpers ────────────────────────────────────────────────────

# Common MT5 install locations on Windows
_MT5_SEARCH_PATHS = [
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
    r"C:\Program Files\RoboForex MT5\terminal64.exe",
    r"C:\Program Files\RoboForex - MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\RoboForex - MetaTrader 5\terminal64.exe",
    r"C:\Program Files\MetaTrader 5 RoboForex\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5 RoboForex\terminal64.exe",
    # User-level installs
    str(Path.home() / "AppData" / "Roaming" / "MetaTrader 5" / "terminal64.exe"),
    str(Path.home() / "AppData" / "Local" / "Programs" / "MetaTrader 5" / "terminal64.exe"),
]


def _find_mt5_exe() -> Optional[str]:
    """Find MT5 executable path. Checks config first, then common locations."""
    # 1. Use path from config/.env if set
    if config.MT5_PATH and Path(config.MT5_PATH).exists():
        return config.MT5_PATH

    # 2. Search common paths
    for p in _MT5_SEARCH_PATHS:
        if Path(p).exists():
            logger.debug(f"Found MT5 at: {p}")
            return p

    # 3. Search APPDATA for any terminal64.exe
    appdata = Path(os.environ.get("APPDATA", ""))
    for match in appdata.rglob("terminal64.exe"):
        logger.debug(f"Found MT5 at: {match}")
        return str(match)

    return None


def _is_mt5_running() -> bool:
    """Check if MT5 process is already running (Windows only)."""
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
            stderr=subprocess.DEVNULL,
        ).decode(errors="ignore")
        return "terminal64.exe" in output
    except Exception:
        return False


def _launch_mt5(exe_path: str, wait_seconds: int = 12) -> bool:
    """
    Launch MT5 terminal and wait for it to be ready.
    Returns True if launched successfully.
    """
    logger.info(f"🚀 Launching MT5: {exe_path}")
    try:
        subprocess.Popen([exe_path], close_fds=True)
    except Exception as e:
        logger.error(f"Failed to launch MT5: {e}")
        return False

    logger.info(f"⏳ Waiting {wait_seconds}s for MT5 to start...")
    for i in range(wait_seconds):
        time.sleep(1)
        if _is_mt5_running():
            logger.info("✅ MT5 process detected — waiting a bit more for it to be ready...")
            time.sleep(4)   # extra wait for terminal to fully initialise
            return True

    logger.warning("MT5 process not detected after launch attempt.")
    return True  # still try to connect — might be slow


# ── Timeframe mapping ──────────────────────────────────────────────────────────
TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1  if MT5_AVAILABLE else 1,
    "M5":  mt5.TIMEFRAME_M5  if MT5_AVAILABLE else 5,
    "M15": mt5.TIMEFRAME_M15 if MT5_AVAILABLE else 15,
    "M30": mt5.TIMEFRAME_M30 if MT5_AVAILABLE else 30,
    "H1":  mt5.TIMEFRAME_H1  if MT5_AVAILABLE else 60,
    "H4":  mt5.TIMEFRAME_H4  if MT5_AVAILABLE else 240,
    "D1":  mt5.TIMEFRAME_D1  if MT5_AVAILABLE else 1440,
    "W1":  mt5.TIMEFRAME_W1  if MT5_AVAILABLE else 10080,
}

# Demo base prices per symbol
_DEMO_BASE = {
    "XAUUSD": 2320.0,
    "EURUSD": 1.0850,
    "GBPUSD": 1.2700,
    "USDJPY": 155.00,
    "BTCUSD": 67000.0,
}

_demo_ticket_counter = 100000
_demo_positions: dict = {}  # ticket -> position dict


def _get_demo_price(symbol: str) -> float:
    base = _DEMO_BASE.get(symbol, 1.0)
    return round(base + random.uniform(-base * 0.001, base * 0.001), 5)


class MT5Connector:
    """
    MetaTrader 5 connection manager.

    Priority:
      1. Use already-logged-in MT5 terminal (just mt5.initialize())
      2. Login via credentials from .env (MT5_LOGIN / MT5_PASSWORD / MT5_SERVER)
      3. DEMO fallback (simulated data only)
    """

    def __init__(self):
        self.connected = False
        self.demo_mode = False
        self._account_cache: Optional[dict] = None

    # ── CONNECTION ────────────────────────────────────────────────────────────

    def connect(self, login: Optional[int] = None, password: Optional[str] = None, server: Optional[str] = None, path: Optional[str] = None) -> bool:
        """
        Connect to MT5 terminal.
        Flow:
          1. Auto-launch MT5 if not already running.
          2. mt5.initialize() to attach to the terminal.
          3. Login with credentials (either passed from Supabase or from .env).
          4. Fall back to DEMO only if MetaTrader5 package is missing.
        """
        if not MT5_AVAILABLE:
            logger.warning("DEMO MODE: MetaTrader5 package not installed.")
            self.demo_mode = True
            self.connected = True
            return True

        # ── Step 1: Auto-launch MT5 if not running ───────────────────────────
        if not _is_mt5_running():
            exe = path if path else _find_mt5_exe()
            if exe:
                _launch_mt5(exe)
            else:
                logger.warning(
                    "MT5 executable not found. "
                    "Set MT5_PATH in your .env or Supabase to the full path of terminal64.exe."
                )

        # ── Step 2: Initialize (attach to running terminal) ──────────────────
        target_path = path if path else (config.MT5_PATH if config.MT5_PATH else None)
        init_ok = mt5.initialize(path=target_path) if target_path else mt5.initialize()

        if not init_ok:
            logger.error(f"MT5 initialize failed: {mt5.last_error()}")
            logger.warning("Falling back to DEMO mode.")
            self._enter_demo()
            return True

        # ── Step 3: Login with credentials ───────────────────────────────────
        target_login = int(login) if login is not None else int(config.MT5_LOGIN)
        target_password = password if password is not None else config.MT5_PASSWORD
        target_server = server if server is not None else config.MT5_SERVER

        account = mt5.account_info()

        if account is None or account.login != target_login:
            # Not logged in yet, or logged in as a different account
            logger.info(f"Logging in to account #{target_login} on {target_server}...")
            authorized = mt5.login(
                login=target_login,
                password=target_password,
                server=target_server,
            )
            if not authorized:
                logger.error(f"MT5 login failed: {mt5.last_error()}")
                mt5.shutdown()
                self._enter_demo()
                return True
            account = mt5.account_info()

        # ✅ MT5 connected & account ready
        self.connected = True
        self.demo_mode = False
        self._account_cache = {
            "login":      account.login,
            "balance":    account.balance,
            "equity":     account.equity,
            "margin":     account.margin,
            "free_margin":account.margin_free,
            "profit":     account.profit,
            "leverage":   account.leverage,
            "currency":   account.currency,
            "server":     account.server,
            "name":       account.name,
        }

        logger.success(f"✅ MT5 Connected — Account #{account.login} ({account.name})")
        logger.info(f"   Balance: {account.balance:,.2f} {account.currency}")
        logger.info(f"   Server:  {account.server}")
        logger.info(f"   Leverage: 1:{account.leverage}")
        return True

    def _enter_demo(self):
        """Switch to DEMO (simulated) mode."""
        self.demo_mode = True
        self.connected = True
        logger.warning("⚠ Running in DEMO MODE — no real trades will be executed.")

    def disconnect(self):
        """Shutdown MT5 connection."""
        if MT5_AVAILABLE and not self.demo_mode:
            mt5.shutdown()
        self.connected = False
        logger.info("🔌 MT5 Disconnected")

    # ── ACCOUNT ───────────────────────────────────────────────────────────────

    def get_account_info(self) -> dict:
        """Return current account info dict."""
        if self.demo_mode:
            return {
                "login":       0,
                "balance":     10_000.0,
                "equity":      10_000.0,
                "margin":      0.0,
                "free_margin": 10_000.0,
                "profit":      0.0,
                "leverage":    100,
                "currency":    "USD",
                "server":      "DEMO",
                "name":        "Demo Account",
            }

        account = mt5.account_info()
        if account is None:
            return self._account_cache or {}

        self._account_cache = {
            "login":       account.login,
            "balance":     account.balance,
            "equity":      account.equity,
            "margin":      account.margin,
            "free_margin": account.margin_free,
            "profit":      account.profit,
            "leverage":    account.leverage,
            "currency":    account.currency,
            "server":      account.server,
            "name":        account.name,
        }
        return self._account_cache

    # ── MARKET DATA ───────────────────────────────────────────────────────────

    def get_tick(self, symbol: str) -> Optional[dict]:
        """Get current bid/ask tick for a symbol."""
        if self.demo_mode:
            price = _get_demo_price(symbol)
            spread = 0.0003 if "USD" in symbol and "XAU" not in symbol else 0.30
            return {"bid": round(price - spread / 2, 5), "ask": round(price + spread / 2, 5)}

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"Cannot get tick for {symbol}: {mt5.last_error()}")
            return None
        return {"bid": tick.bid, "ask": tick.ask}

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = None,
        bars: int = None,
    ) -> Optional[pd.DataFrame]:
        """
        Get OHLCV bars as a DataFrame.
        Returns DataFrame with columns: time, open, high, low, close, volume, spread
        """
        tf_str = timeframe or config.TIMEFRAME
        bars   = bars or config.BARS_TO_FETCH

        if self.demo_mode:
            return self._generate_demo_ohlcv(symbol, bars)

        tf = TF_MAP.get(tf_str)
        if tf is None:
            logger.error(f"Invalid timeframe: {tf_str}")
            return None

        # Ensure symbol is visible
        mt5.symbol_select(symbol, True)

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            logger.error(f"No data for {symbol} {tf_str}: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})
        if "spread" not in df.columns:
            df["spread"] = 0
        return df[["time", "open", "high", "low", "close", "volume", "spread"]]

    def get_multi_timeframe(self, symbol: str, timeframes: list = None, bars: int = None) -> dict:
        """
        Get OHLCV for multiple timeframes.
        Returns: Dict of {timeframe: DataFrame}
        """
        if timeframes is None:
            timeframes = ["H4", "H1", "M15", "M5"]
        
        result = {}
        for tf in timeframes:
            df = self.get_ohlcv(symbol, tf, bars)
            if df is not None and not df.empty:
                result[tf] = df
        return result

    def _generate_demo_ohlcv(self, symbol: str, bars: int) -> pd.DataFrame:
        """Generate realistic-looking synthetic OHLCV data for DEMO mode."""
        base = _DEMO_BASE.get(symbol, 1.0)
        rows = []
        now = datetime.now()
        price = base
        for i in range(bars, 0, -1):
            t = now - timedelta(minutes=5 * i)
            change = random.uniform(-base * 0.002, base * 0.002)
            o = round(price, 5)
            c = round(price + change, 5)
            h = round(max(o, c) + abs(change) * random.uniform(0, 0.5), 5)
            l = round(min(o, c) - abs(change) * random.uniform(0, 0.5), 5)
            rows.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": random.randint(100, 1000), "spread": 3})
            price = c
        return pd.DataFrame(rows)

    # ── SYMBOL INFO ───────────────────────────────────────────────────────────

    def get_pip_value(self, symbol: str) -> float:
        """Return pip value (point size) for the symbol."""
        if self.demo_mode:
            return config.get_pip_multiplier(symbol)

        info = mt5.symbol_info(symbol)
        if info is None:
            return config.get_pip_multiplier(symbol)
        return info.point

    def get_contract_size(self, symbol: str) -> float:
        """Return contract size for the symbol."""
        if self.demo_mode:
            return 100.0 if "XAU" in symbol else 100_000.0

        info = mt5.symbol_info(symbol)
        if info is None:
            return 100_000.0
        return info.trade_contract_size

    # ── POSITIONS ─────────────────────────────────────────────────────────────

    def has_open_position(self, symbol: str) -> bool:
        """Return True if there is an open position on this symbol."""
        if self.demo_mode:
            return any(p["symbol"] == symbol for p in _demo_positions.values())

        positions = mt5.positions_get(symbol=symbol)
        return positions is not None and len(positions) > 0

    def get_open_positions(self, symbol: str = None) -> list:
        """Get all open positions (optionally filtered by symbol)."""
        if self.demo_mode:
            positions = [p for p in _demo_positions.values() if not symbol or p["symbol"] == symbol]
            result = []
            for pos in positions:
                tick = self.get_tick(pos["symbol"])
                current = tick["bid"] if pos["direction"] == "BUY" else tick["ask"]
                if pos["direction"] == "BUY":
                    profit = (current - pos["price_open"]) * pos["volume"]
                else:
                    profit = (pos["price_open"] - current) * pos["volume"]
                result.append({
                    **pos,
                    "price_current": current,
                    "profit": round(profit, 2),
                })
            return result

        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            return []

        result = []
        for pos in positions:
            result.append({
                "ticket":        pos.ticket,
                "symbol":        pos.symbol,
                "direction":     "BUY" if pos.type == 0 else "SELL",
                "volume":        pos.volume,
                "price_open":    pos.price_open,
                "price_current": pos.price_current,
                "sl":            pos.sl,
                "tp":            pos.tp,
                "profit":        pos.profit,
                "swap":          pos.swap,
                "comment":       pos.comment,
                "time":          datetime.fromtimestamp(pos.time),
            })
        return result

    def update_trailing_stop(self, symbol: str, atr: float = None):
        """
        Multi-Stage Trailing Stop:
        Stage 1: If profit > 0.5 * ATR, move SL to Break Even.
        Stage 2: If profit > 1.5 * ATR, trail SL by 1.0 * ATR.
        """
        if self.demo_mode or not MT5_AVAILABLE or not atr:
            return

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return

        stage1_distance = 0.5 * atr
        stage2_distance = 1.5 * atr
        trail_distance = 1.0 * atr

        for pos in positions:
            action = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
            current_sl = pos.sl
            
            if action == "BUY":
                profit_distance = pos.price_current - pos.price_open
                
                # Stage 2: Trailing
                if profit_distance > stage2_distance:
                    new_sl = pos.price_current - trail_distance
                    if new_sl > current_sl: # Only move up
                        self._modify_sl(pos.ticket, pos.symbol, new_sl, pos.tp)
                        
                # Stage 1: Break Even
                elif profit_distance > stage1_distance:
                    new_sl = pos.price_open
                    if current_sl < new_sl:
                        self._modify_sl(pos.ticket, pos.symbol, new_sl, pos.tp)
                        
            elif action == "SELL":
                profit_distance = pos.price_open - pos.price_current
                
                # Stage 2: Trailing
                if profit_distance > stage2_distance:
                    new_sl = pos.price_current + trail_distance
                    if current_sl == 0.0 or new_sl < current_sl: # Only move down
                        self._modify_sl(pos.ticket, pos.symbol, new_sl, pos.tp)
                        
                # Stage 1: Break Even
                elif profit_distance > stage1_distance:
                    new_sl = pos.price_open
                    if current_sl == 0.0 or current_sl > new_sl:
                        self._modify_sl(pos.ticket, pos.symbol, new_sl, pos.tp)

    def _modify_sl(self, ticket: int, symbol: str, new_sl: float, tp: float):
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": float(new_sl),
            "tp": float(tp),
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[{symbol}] Trailing Stop updated | Ticket {ticket} | New SL: {new_sl:.5f}")
        else:
            logger.debug(f"Failed to modify SL for {ticket}: {result.comment if result else mt5.last_error()}")

    # ── ORDER EXECUTION ───────────────────────────────────────────────────────

    def place_order(
        self,
        symbol:   str,
        action:   str,
        lot:      float,
        sl_price: float,
        tp_price: float,
        comment:  str = "AI_BOT",
    ) -> dict:
        """
        Place a market order.
        Returns: {"success": bool, "ticket": int|None, "message": str}
        """
        if self.demo_mode:
            return self._place_demo_order(symbol, action, lot, sl_price, tp_price, comment)

        # Ensure symbol is available
        if not mt5.symbol_select(symbol, True):
            return {"success": False, "ticket": None, "message": f"Cannot select symbol {symbol}"}

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "ticket": None, "message": f"No tick for {symbol}"}

        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        price      = tick.ask if action == "BUY" else tick.bid

        request = {
            "action":        mt5.TRADE_ACTION_DEAL,
            "symbol":        symbol,
            "volume":        float(lot),
            "type":          order_type,
            "price":         price,
            "deviation":     20,
            "magic":         123456,
            "comment":       comment,
            "type_time":     mt5.ORDER_TIME_GTC,
            "type_filling":  mt5.ORDER_FILLING_IOC,
        }

        if config.USE_BROKER_SL_TP:
            # Validate broker-visible SL/TP direction only when explicitly enabled.
            if action == "BUY" and sl_price >= price:
                sl_price = price * 0.995
            if action == "SELL" and sl_price <= price:
                sl_price = price * 1.005
            if action == "BUY" and tp_price <= price:
                tp_price = price * 1.01
            if action == "SELL" and tp_price >= price:
                tp_price = price * 0.99
            request["sl"] = round(sl_price, 5)
            request["tp"] = round(tp_price, 5)

        result = mt5.order_send(request)

        if result is None:
            return {"success": False, "ticket": None, "message": f"order_send returned None: {mt5.last_error()}"}

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.success(f"✅ Order placed: {action} {lot} {symbol} @ {price} | Ticket: {result.order}")
            return {"success": True, "ticket": result.order, "message": "OK", "price": price}
        else:
            msg = f"Order rejected (code {result.retcode}): {result.comment}"
            logger.error(f"❌ {msg}")
            return {"success": False, "ticket": None, "message": msg}

    def _place_demo_order(self, symbol, action, lot, sl_price, tp_price, comment) -> dict:
        global _demo_ticket_counter
        _demo_ticket_counter += 1
        ticket = _demo_ticket_counter
        tick = self.get_tick(symbol)
        price = tick["ask"] if action == "BUY" else tick["bid"]
        _demo_positions[ticket] = {
            "ticket":     ticket,
            "symbol":     symbol,
            "direction":  action,
            "volume":     lot,
            "price_open": price,
            "sl":         sl_price,
            "tp":         tp_price,
            "comment":    comment,
            "time":       datetime.now(),
        }
        logger.info(f"[DEMO] Order placed: {action} {lot} {symbol} | Ticket: {ticket}")
        return {"success": True, "ticket": ticket, "message": "DEMO", "price": price}

    def close_trade(self, ticket: int, symbol: str) -> bool:
        """Close an open position by ticket."""
        if self.demo_mode:
            if ticket in _demo_positions:
                del _demo_positions[ticket]
                logger.info(f"[DEMO] Position {ticket} closed")
                return True
            return False

        position = mt5.positions_get(ticket=ticket)
        if not position:
            logger.error(f"Position {ticket} not found")
            return False

        pos = position[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       pos.volume,
            "type":         close_type,
            "position":     ticket,
            "price":        price,
            "deviation":    20,
            "magic":        123456,
            "comment":      "AI_BOT_CLOSE",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.success(f"✅ Position {ticket} closed @ {price}")
            return True
        else:
            logger.error(f"❌ Close failed: {result.comment if result else mt5.last_error()}")
            return False

    def get_trade_history(self, days: int = 30) -> list:
        """Get closed trade history."""
        if self.demo_mode:
            return []

        from_date = datetime.now() - timedelta(days=days)
        to_date   = datetime.now()
        deals = mt5.history_deals_get(from_date, to_date)
        if deals is None:
            return []

        result = []
        for deal in deals:
            if deal.entry == 1:
                result.append({
                    "ticket":     deal.order,
                    "direction":  "BUY" if deal.type == 0 else "SELL",
                    "volume":     deal.volume,
                    "price":      deal.price,
                    "profit":     deal.profit,
                    "commission": deal.commission,
                    "swap":       deal.swap,
                    "comment":    deal.comment,
                    "time":       datetime.fromtimestamp(deal.time),
                })
        return result

    # ── COMPAT: Old API aliases ───────────────────────────────────────────────
    # (kept for backward compat with any direct references)

    def get_current_price(self, symbol: str) -> Optional[dict]:
        return self.get_tick(symbol)

    def open_trade(self, direction, lot_size, sl, tp, symbol=None, comment="AI_BOT") -> Optional[dict]:
        sym = symbol or config.SYMBOLS[0]
        result = self.place_order(sym, direction, lot_size, sl, tp, comment)
        if result["success"]:
            return result
        return None
