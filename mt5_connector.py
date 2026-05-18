"""
🏆 GOLD AI Trading Algo — MT5 Connector
=========================================
MetaTrader 5 connection manager untuk RoboForex PRO.
Handle connect, data retrieval, order execution.
"""

from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
from loguru import logger

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.warning("⚠️ MetaTrader5 package not installed — running in OFFLINE mode")

from config import MT5_ACCOUNT, MT5_PASSWORD, MT5_SERVER, SYMBOL, TIMEFRAMES


# ── Timeframe mapping ──
TF_MAP = {
    "M1": mt5.TIMEFRAME_M1 if MT5_AVAILABLE else 1,
    "M5": mt5.TIMEFRAME_M5 if MT5_AVAILABLE else 5,
    "M15": mt5.TIMEFRAME_M15 if MT5_AVAILABLE else 15,
    "M30": mt5.TIMEFRAME_M30 if MT5_AVAILABLE else 30,
    "H1": mt5.TIMEFRAME_H1 if MT5_AVAILABLE else 60,
    "H4": mt5.TIMEFRAME_H4 if MT5_AVAILABLE else 240,
    "D1": mt5.TIMEFRAME_D1 if MT5_AVAILABLE else 1440,
    "W1": mt5.TIMEFRAME_W1 if MT5_AVAILABLE else 10080,
}


class MT5Connector:
    """MetaTrader 5 connection manager."""

    def __init__(self):
        self.connected = False
        self.account_info = None

    def connect(self) -> bool:
        """Connect to MT5 terminal."""
        if not MT5_AVAILABLE:
            logger.error("❌ MT5 not available — install MetaTrader5 package")
            return False

        if not mt5.initialize():
            logger.error(f"❌ MT5 initialize failed: {mt5.last_error()}")
            return False

        # Login to account
        if MT5_ACCOUNT and MT5_PASSWORD:
            authorized = mt5.login(
                login=MT5_ACCOUNT,
                password=MT5_PASSWORD,
                server=MT5_SERVER,
            )
            if not authorized:
                logger.error(f"❌ MT5 login failed: {mt5.last_error()}")
                mt5.shutdown()
                return False

        self.account_info = mt5.account_info()
        self.connected = True

        logger.info(f"✅ MT5 Connected — Account: {self.account_info.login}")
        logger.info(f"   Balance: ${self.account_info.balance:,.2f}")
        logger.info(f"   Server: {self.account_info.server}")
        logger.info(f"   Leverage: 1:{self.account_info.leverage}")

        return True

    def disconnect(self):
        """Disconnect from MT5."""
        if MT5_AVAILABLE and self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("🔌 MT5 Disconnected")

    def get_account_info(self) -> Optional[dict]:
        """Get current account information."""
        if not self.connected:
            return None

        info = mt5.account_info()
        if info is None:
            return None

        return {
            "login": info.login,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "profit": info.profit,
            "leverage": info.leverage,
            "server": info.server,
        }

    def get_symbol_info(self, symbol: str = SYMBOL) -> Optional[dict]:
        """Get symbol information."""
        if not self.connected:
            return None

        info = mt5.symbol_info(symbol)
        if info is None:
            logger.error(f"❌ Symbol {symbol} not found")
            return None

        return {
            "symbol": info.name,
            "bid": info.bid,
            "ask": info.ask,
            "spread": info.spread,
            "point": info.point,
            "digits": info.digits,
            "trade_mode": info.trade_mode,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
        }

    def get_current_price(self, symbol: str = SYMBOL) -> Optional[dict]:
        """Get current bid/ask."""
        if not self.connected:
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None

        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "time": datetime.fromtimestamp(tick.time),
            "spread": round(tick.ask - tick.bid, 2),
        }

    def get_ohlcv(
        self,
        symbol: str = SYMBOL,
        timeframe: str = "H1",
        bars: int = 500,
    ) -> Optional[pd.DataFrame]:
        """Get OHLCV data as DataFrame.

        Args:
            symbol: Trading symbol (default XAUUSD)
            timeframe: Timeframe string (M5, M15, H1, H4, D1)
            bars: Number of bars to fetch

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, spread
        """
        if not self.connected:
            return None

        tf = TF_MAP.get(timeframe)
        if tf is None:
            logger.error(f"❌ Invalid timeframe: {timeframe}")
            return None

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            logger.error(f"❌ No data for {symbol} {timeframe}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})

        return df[["time", "open", "high", "low", "close", "volume", "spread"]]

    def get_multi_timeframe(self, symbol: str = SYMBOL, bars: int = 500) -> dict:
        """Get OHLCV for all configured timeframes.

        Returns:
            Dict of {timeframe: DataFrame}
        """
        result = {}
        for tf in TIMEFRAMES:
            df = self.get_ohlcv(symbol, tf, bars)
            if df is not None:
                result[tf] = df
                logger.debug(f"📊 Got {len(df)} bars for {symbol} {tf}")
        return result

    # ── TRADING OPERATIONS ──

    def open_trade(
        self,
        direction: str,
        lot_size: float,
        sl: float,
        tp: float,
        symbol: str = SYMBOL,
        comment: str = "GOLD_AI",
    ) -> Optional[dict]:
        """Open a new trade.

        Args:
            direction: 'BUY' or 'SELL'
            lot_size: Trade volume
            sl: Stop loss price
            tp: Take profit price
            symbol: Symbol to trade
            comment: Trade comment

        Returns:
            Trade result dict or None
        """
        if not self.connected:
            logger.error("❌ MT5 not connected")
            return None

        # Ensure symbol is visible
        if not mt5.symbol_select(symbol, True):
            logger.error(f"❌ Cannot select symbol {symbol}")
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"❌ Cannot get tick for {symbol}")
            return None

        # Build order request
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if direction == "BUY" else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 123456,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None:
            logger.error(f"❌ Order send failed: {mt5.last_error()}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"❌ Order rejected: {result.comment} (code: {result.retcode})")
            return None

        logger.info(f"✅ Trade opened: {direction} {lot_size} {symbol} @ {price}")
        logger.info(f"   SL: {sl} | TP: {tp} | Ticket: {result.order}")

        return {
            "ticket": result.order,
            "direction": direction,
            "lot_size": lot_size,
            "price": price,
            "sl": sl,
            "tp": tp,
            "comment": comment,
        }

    def close_trade(self, ticket: int, symbol: str = SYMBOL) -> bool:
        """Close an open position by ticket number."""
        if not self.connected:
            return False

        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            logger.error(f"❌ Position {ticket} not found")
            return False

        pos = position[0]
        # Reverse direction to close
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 123456,
            "comment": "GOLD_AI_CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"❌ Close failed: {result.comment}")
            return False

        logger.info(f"✅ Position {ticket} closed @ {price} | P/L: {pos.profit}")
        return True

    def modify_sl_tp(self, ticket: int, sl: float, tp: float, symbol: str = SYMBOL) -> bool:
        """Modify SL/TP of an open position."""
        if not self.connected:
            return False

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": sl,
            "tp": tp,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"❌ Modify failed: {result.comment}")
            return False

        logger.info(f"✅ Position {ticket} modified — SL: {sl} | TP: {tp}")
        return True

    def get_open_positions(self, symbol: str = SYMBOL) -> list:
        """Get all open positions."""
        if not self.connected:
            return []

        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return []

        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "direction": "BUY" if pos.type == 0 else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "price_current": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "swap": pos.swap,
                "comment": pos.comment,
                "time": datetime.fromtimestamp(pos.time),
            })

        return result

    def get_trade_history(self, days: int = 30) -> list:
        """Get closed trade history."""
        if not self.connected:
            return []

        from_date = datetime.now() - timedelta(days=days)
        to_date = datetime.now()

        deals = mt5.history_deals_get(from_date, to_date)
        if deals is None:
            return []

        result = []
        for deal in deals:
            if deal.entry == 1:  # Only exit deals
                result.append({
                    "ticket": deal.order,
                    "direction": "BUY" if deal.type == 0 else "SELL",
                    "volume": deal.volume,
                    "price": deal.price,
                    "profit": deal.profit,
                    "commission": deal.commission,
                    "swap": deal.swap,
                    "comment": deal.comment,
                    "time": datetime.fromtimestamp(deal.time),
                })

        return result
