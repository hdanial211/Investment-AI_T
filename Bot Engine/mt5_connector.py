import MetaTrader5 as mt5
import logging
from typing import Dict, Optional, List, Union
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

class MT5Connector:
    def __init__(self):
        self.connected = False

    def initialize(self, path: str = "", login: int = 0, password: str = "", server: str = "") -> bool:
        """Initialize connection to MT5 terminal."""
        if path and login > 0:
            init_res = mt5.initialize(path=path, login=login, password=password, server=server)
        elif path:
            init_res = mt5.initialize(path=path)
        else:
            init_res = mt5.initialize()
            
        if not init_res:
            logger.error(f"MT5 initialize failed: {mt5.last_error()}")
            self.connected = False
            return False
            
        self.connected = True
        logger.info("MT5 initialized successfully.")
        return True

    def connect(self, login: int, password: str, server: str, path: str = "") -> bool:
        """Legacy alias for initialize"""
        return self.initialize(path, login, password, server)

    def is_connected(self) -> bool:
        """Check if connected to MT5."""
        if not self.connected:
            return False
        info = mt5.terminal_info()
        return info is not None and info.connected

    def shutdown(self):
        """Close connection to MT5 terminal."""
        if self.connected:
            mt5.shutdown()
            self.connected = False

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Fetch symbol properties like tick value, tick size, etc."""
        if not self.is_connected():
            return None
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning(f"Failed to get symbol info for {symbol}")
            return None
            
        return {
            "ask": info.ask,
            "bid": info.bid,
            "point": info.point,
            "trade_tick_value": info.trade_tick_value,
            "trade_tick_size": info.trade_tick_size,
            "trade_contract_size": info.trade_contract_size,
            "digits": info.digits,
            "spread": info.spread
        }

    def get_tick(self, symbol: str) -> Optional[Dict]:
        """Get latest tick for a symbol."""
        if not self.is_connected():
            return None
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return None
        return {
            "time": tick.time,
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume
        }

    def get_account_info(self) -> Optional[Dict]:
        """Get account balance, equity, margin, etc."""
        if not self.is_connected():
            return None
        info = mt5.account_info()
        if not info:
            return None
        return info._asdict()

    def get_ohlc_data(self, symbol: str, timeframe: int, count: int = 100) -> pd.DataFrame:
        """Fetch OHLC data for analysis."""
        if not self.is_connected():
            return pd.DataFrame()
            
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def get_multi_timeframe(self, symbol: str, timeframes: List[str], bars: int = 100) -> Dict[str, pd.DataFrame]:
        """Fetch OHLC data for multiple timeframes."""
        if not self.is_connected():
            return {}
            
        tf_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1
        }
        
        result = {}
        for tf_str in timeframes:
            tf_enum = tf_map.get(tf_str.upper())
            if tf_enum is None: continue
            
            df = self.get_ohlc_data(symbol, tf_enum, bars)
            if not df.empty:
                result[tf_str.upper()] = df
                
        return result

    def _get_filling_mode(self, symbol: str) -> int:
        info = mt5.symbol_info(symbol)
        if not info: return mt5.ORDER_FILLING_FOK
        
        # In Python MetaTrader5, filling_mode is a bit flag:
        # 1 = FOK, 2 = IOC
        if info.filling_mode & 1:  # FOK
            return mt5.ORDER_FILLING_FOK
        if info.filling_mode & 2:  # IOC
            return mt5.ORDER_FILLING_IOC
            
        return mt5.ORDER_FILLING_RETURN

    def execute_stealth_entry(self, symbol: str, direction: str, lot: float, magic_number: int) -> Optional[int]:
        """
        Execute a market order WITH NO SL AND TP (Stealth Mode).
        Returns the ticket number if successful, None otherwise.
        """
        if not self.is_connected():
            logger.error("MT5 not connected. Cannot execute entry.")
            return None

        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == 'BUY' else mt5.ORDER_TYPE_SELL
        info = mt5.symbol_info(symbol)
        if not info:
            logger.error(f"Symbol {symbol} not found.")
            return None
            
        price = info.ask if direction.upper() == 'BUY' else info.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": price,
            "sl": 0.0,  # Stealth mode
            "tp": 0.0,  # Stealth mode
            "deviation": 20,
            "magic": magic_number,
            "comment": "V4_AI_Stealth",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed for {symbol}. Error: {result.comment} (Code: {result.retcode})")
            return None
            
        logger.info(f"Stealth Entry Success: Ticket {result.order} for {symbol} ({direction} {lot} lots)")
        return result.order

    def open_trade(self, action: str, lot: float, sl: float, tp: float, symbol: str, comment: str = "", magic: int = 0) -> Union[int, Dict, None]:
        """Legacy alias that routes to Stealth Entry since V4 ignores broker SL/TP."""
        return self.execute_stealth_entry(symbol, action, lot, magic)

    def get_open_positions(self, symbol: str = "") -> List[Dict]:
        """Fetch all open positions."""
        if not self.is_connected():
            return []
            
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
            
        if positions is None:
            return []
            
        return [p._asdict() for p in positions]

    def close_position(self, ticket: int, lot: float, symbol: str, direction: str) -> bool:
        """Close an existing position (Used for emergency or manual intervention from Python)."""
        if not self.is_connected():
            return False

        info = mt5.symbol_info(symbol)
        if not info:
            return False

        # If it was a BUY (0), we close by SELLING (1) at BID.
        close_type = mt5.ORDER_TYPE_SELL if direction == 0 or str(direction).upper() == 'BUY' else mt5.ORDER_TYPE_BUY
        price = info.bid if close_type == mt5.ORDER_TYPE_SELL else info.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 0,
            "comment": "V4_Python_Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Failed to close ticket {ticket}. Code: {result.retcode}")
            return False
            
        return True

# Singleton instance for easy import
mt5_conn = MT5Connector()
