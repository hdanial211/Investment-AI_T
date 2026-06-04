"""
risk_manager.py - Risk Management & Position Sizing

Responsibilities:
- Calculate lot size based on account balance and risk %
- Compute SL/TP price levels from pips
- Enforce max consecutive loss limit
- Validate trades before execution
- Track trading session stats
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import config
from news_filter import NewsFilter

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE (in-memory, resets on restart)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionStats:
    """Tracks live trading session performance."""
    trades_total:       int   = 0
    trades_win:         int   = 0
    trades_loss:        int   = 0
    consecutive_losses: int   = 0
    total_pnl:          float = 0.0
    session_start:      datetime = field(default_factory=datetime.now)
    trading_halted:     bool  = False
    halt_reason:        str   = ""

    @property
    def win_rate(self) -> float:
        if self.trades_total == 0:
            return 0.0
        return round(self.trades_win / self.trades_total * 100, 2)

    def record_win(self, profit: float):
        self.trades_total      += 1
        self.trades_win        += 1
        self.consecutive_losses = 0
        self.total_pnl         += profit

    def record_loss(self, loss: float):
        self.trades_total      += 1
        self.trades_loss       += 1
        self.consecutive_losses += 1
        self.total_pnl         -= abs(loss)

        if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
            self.trading_halted = True
            self.halt_reason    = (
                f"Max consecutive losses reached ({self.consecutive_losses}). "
                "Manual review required."
            )
            logger.critical(f"🛑 TRADING HALTED: {self.halt_reason}")

    def resume_trading(self):
        """Manually resume trading after halt (called externally)."""
        self.trading_halted     = False
        self.halt_reason        = ""
        self.consecutive_losses = 0
        logger.warning("Trading resumed manually. Monitor closely.")


# ─────────────────────────────────────────────────────────────────────────────
# LOT SIZE CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

def calculate_lot_size(
    balance:       float,
    risk_pct:      float,
    sl_pips:       int,
    symbol:        str,
    pip_value:     float,
    contract_size: float,
) -> float:
    """
    Calculate position size based on fixed percentage risk.

    Formula:
        risk_amount   = balance × (risk_pct / 100)
        pip_value_lot = pip_size × contract_size
        lot_size      = risk_amount / (sl_pips × pip_value_lot)

    Args:
        balance:       Account balance in account currency
        risk_pct:      Risk percentage per trade (e.g., 2.0)
        sl_pips:       Stop loss distance in pips
        symbol:        Trading symbol
        pip_value:     Value of 1 pip (e.g., 0.0001 for EURUSD)
        contract_size: Contract size per lot (e.g., 100000 for EURUSD)

    Returns:
        Lot size rounded to 2 decimal places, clamped to [MIN_LOT, MAX_LOT]
    """
    if sl_pips <= 0 or balance <= 0:
        logger.warning("Invalid SL pips or balance for lot calculation")
        return config.MIN_LOT

    risk_amount   = balance * (risk_pct / 100)
    pip_value_lot = pip_value * contract_size
    sl_value      = sl_pips * pip_value_lot

    if sl_value <= 0:
        logger.warning("SL value is zero, using minimum lot")
        return config.MIN_LOT

    raw_lot = risk_amount / sl_value
    lot     = round(raw_lot, 2)

    # Clamp to allowed range
    lot = max(config.MIN_LOT, min(config.MAX_LOT, lot))

    logger.debug(
        f"Lot calc: balance={balance:.2f}, risk={risk_pct}%, "
        f"SL={sl_pips}pips, pip_val={pip_value_lot:.5f} → lot={lot}"
    )
    return lot


# ─────────────────────────────────────────────────────────────────────────────
# SL / TP PRICE CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

def calculate_sl_tp(
    action:    str,
    price:     float,
    sl_pips:   int,
    tp_pips:   int,
    pip_value: float,
) -> Tuple[float, float]:
    """
    Calculate absolute SL and TP price levels.

    Args:
        action:    "BUY" or "SELL"
        price:     Entry price
        sl_pips:   Stop loss in pips
        tp_pips:   Take profit in pips
        pip_value: Size of 1 pip

    Returns:
        (sl_price, tp_price) as floats
    """
    sl_distance = sl_pips * pip_value
    tp_distance = tp_pips * pip_value

    if action == "BUY":
        sl_price = round(price - sl_distance, 5)
        tp_price = round(price + tp_distance, 5)
    else:  # SELL
        sl_price = round(price + sl_distance, 5)
        tp_price = round(price - tp_distance, 5)

    return sl_price, tp_price


# ─────────────────────────────────────────────────────────────────────────────
# RISK MANAGER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class RiskManager:
    """
    Central risk management controller.
    Validates trades and enforces risk rules before execution.
    """

    def __init__(self):
        self.stats = SessionStats()
        self.news_filter = NewsFilter()

    # ── TRADE VALIDATION ─────────────────────────────────────────────────────

    def can_trade(self, symbol: str, open_positions_count: int, indicators: Dict, trade_memory=None, acct_settings=None) -> Tuple[bool, str]:
        """
        Run all pre-trade checks.

        Returns:
            (allowed: bool, reason: str)
        """
        # 0. Check cooling off period
        if trade_memory:
            is_cooling, reason = trade_memory.is_cooling_off(symbol)
            if is_cooling:
                return False, reason
                
            # 0.5 Check entry spacing (10 mins) for layering
            active_trades = trade_memory.data.get("active_trades", {})
            for t_id, state in active_trades.items():
                if state.get("symbol") == symbol:
                    opened_at_str = state.get("timestamp")
                    if opened_at_str:
                        try:
                            opened_at = datetime.fromisoformat(opened_at_str)
                            now_time = datetime.now(timezone.utc) if opened_at.tzinfo else datetime.now()
                            if (now_time - opened_at).total_seconds() < 600: # 10 minutes
                                return False, f"Entry spacing: Must wait 10 minutes after last {symbol} trade"
                        except ValueError:
                            pass

        # 1. Check if trading is halted
        if self.stats.trading_halted:
            return False, f"Trading halted: {self.stats.halt_reason}"

        # 2. Check for existing positions (Layering limit)
        if open_positions_count >= config.MAX_TRADES_PER_PAIR:
            return False, f"Max layered trades ({config.MAX_TRADES_PER_PAIR}) reached for {symbol}"

        # 3. Check volatility
        if not indicators.get("sufficient_volatility", True):
            return False, "Insufficient market volatility"

        # 4. Avoid extreme RSI (already overbought/oversold)
        rsi = indicators.get("m15_rsi", 50)
        if rsi > 80 or rsi < 20:
            return False, f"Extreme RSI {rsi:.1f} — avoiding trade"
            
        # 5. Check News Events
        if acct_settings and not acct_settings.trade_during_events:
            safe, reason = self.news_filter.is_safe_to_trade(symbol)
            if not safe:
                return False, reason

        return True, "Risk checks passed"

    def validate_signal(self, signal: Dict) -> Tuple[bool, str]:
        """
        Validate AI signal before execution.

        Returns:
            (valid: bool, reason: str)
        """
        action     = signal.get("action", "HOLD")
        confidence = signal.get("confidence", 0.0)

        # Must be actionable
        if action == "HOLD":
            return False, "Signal is HOLD"

        # Minimum confidence filter
        if confidence < config.MIN_CONFIDENCE:
            return False, f"Confidence {confidence:.2f} below threshold {config.MIN_CONFIDENCE}"

        return True, f"Signal valid: {action} @ {confidence:.2f}"

    # ── POSITION SIZING ──────────────────────────────────────────────────────

    def get_trade_params(
        self,
        symbol:        str,
        action:        str,
        price:         float,
        balance:       float,
        pip_value:     float,
        contract_size: float,
        indicators:    Dict = None,
        trade_style:   str = "INTRADAY",
    ) -> Dict:
        """
        Calculate all parameters needed to place a trade.

        Uses per-style per-symbol parameters from style_params when dynamic
        SL is enabled, otherwise falls back to config.SL_PIPS / TP_PIPS.

        Returns dict with: lot, sl, tp, sl_pips, tp_pips, trade_style
        """
        from style_params import get_style_params

        style_p = get_style_params(trade_style, symbol)

        sl_pips = config.SL_PIPS
        tp_pips = config.TP_PIPS
        risk_pct = style_p["risk_percent"]

        if config.USE_DYNAMIC_SL and indicators and "atr" in indicators:
            atr = indicators["atr"]
            pip_multiplier = 10000
            if "XAU" in symbol or "XAG" in symbol:
                pip_multiplier = 100
            elif "JPY" in symbol:
                pip_multiplier = 100

            atr_pips = atr * pip_multiplier

            # Use per-style ATR multipliers instead of global config values
            dynamic_sl = int(atr_pips * style_p["sl_atr_multi"])
            dynamic_tp = int(atr_pips * style_p["tp_atr_multi"])

            # Clamp SL within per-style min/max bounds
            sl_pips = max(style_p["min_sl_pips"], min(style_p["max_sl_pips"], dynamic_sl))
            tp_pips = max(dynamic_tp, sl_pips)  # TP should never be less than SL

            logger.debug(
                f"Style-aware SL/TP: style={trade_style}, ATR={atr_pips:.0f}pips, "
                f"SL={sl_pips}pips (multi={style_p['sl_atr_multi']}), "
                f"TP={tp_pips}pips (multi={style_p['tp_atr_multi']}), "
                f"risk={risk_pct}%"
            )

        lot = calculate_lot_size(
            balance       = balance,
            risk_pct      = risk_pct,
            sl_pips       = sl_pips,
            symbol        = symbol,
            pip_value     = pip_value,
            contract_size = contract_size,
        )

        pip_size = config.get_pip_multiplier(symbol)

        if action == "BUY":
            sl_price = price - (sl_pips * pip_size)
            tp_price = price + (tp_pips * pip_size)
        else:
            sl_price = price + (sl_pips * pip_size)
            tp_price = price - (tp_pips * pip_size)

        return {
            "lot":         lot,
            "sl":          round(sl_price, 5),
            "tp":          round(tp_price, 5),
            "sl_pips":     sl_pips,
            "tp_pips":     tp_pips,
            "trade_style": trade_style,
        }

    # ── R:R RATIO VALIDATION ─────────────────────────────────────────────────

    @staticmethod
    def validate_rr_ratio(
        sl_pips: int,
        tp_pips: int,
        trade_style: str,
        symbol: str,
    ) -> tuple:
        """
        Check if the risk-reward ratio meets the minimum for this style.

        Returns (valid: bool, reason: str).
        """
        from style_params import get_style_params

        params = get_style_params(trade_style, symbol)
        min_rr = params.get("min_rr", 1.0)

        if sl_pips <= 0:
            return True, "SL is zero — skipping R:R check"

        rr = round(tp_pips / sl_pips, 2)
        if rr < min_rr:
            return False, (
                f"R:R {rr} below minimum {min_rr} for {trade_style} "
                f"(SL={sl_pips}, TP={tp_pips})"
            )
        return True, f"R:R {rr} OK (min: {min_rr})"

    # ── SESSION VALIDATION ───────────────────────────────────────────────────

    @staticmethod
    def validate_session(trade_style: str, symbol: str) -> tuple:
        """
        Check if the current session allows this trade style.

        Returns (allowed: bool, reason: str).
        """
        from style_params import is_session_allowed
        return is_session_allowed(trade_style, symbol)

    # ── DAILY LIMITS & SPREAD VALIDATION ─────────────────────────────────────

    def check_daily_limits(self, connector, acct_settings) -> Tuple[bool, str]:
        max_dd_pct = acct_settings.max_daily_drawdown_pct
        target_pct = acct_settings.daily_profit_target_pct

        if max_dd_pct <= 0 and target_pct <= 0:
            return True, "No daily limits set"

        acc_info = connector.get_account_info()
        balance = acc_info.get("balance", 0)
        if balance <= 0:
            return True, "Balance 0, skipping limit check"

        # Closed profit today
        trades = connector.get_trade_history(days=1)
        today = datetime.now().date()
        closed_profit = 0.0
        for t in trades:
            if t["time"].date() == today:
                closed_profit += t["profit"] + t["commission"] + t["swap"]

        # Floating profit
        positions = connector.get_open_positions() or []
        floating_profit = sum(p.get("profit", 0) + p.get("swap", 0) for p in positions)

        total_pnl = closed_profit + floating_profit
        pnl_pct = (total_pnl / balance) * 100

        if max_dd_pct > 0 and pnl_pct <= -max_dd_pct:
            return False, f"Daily Drawdown {pnl_pct:.2f}% exceeds max -{max_dd_pct}%"
        
        if target_pct > 0 and pnl_pct >= target_pct:
            return False, f"Daily Profit {pnl_pct:.2f}% hit target +{target_pct}%"

        return True, f"Daily PnL: {pnl_pct:.2f}%"

    @staticmethod
    def validate_spread(connector, symbol: str, max_spread_points: int) -> Tuple[bool, str]:
        if max_spread_points <= 0:
            return True, "Spread limit disabled"
            
        tick = connector.get_tick(symbol)
        if not tick:
            return False, "Cannot get tick for spread"
            
        if connector.demo_mode:
            point = 0.01 if "XAU" in symbol else 0.00001
        else:
            import MetaTrader5 as mt5
            info = mt5.symbol_info(symbol)
            point = info.point if info else (0.01 if "XAU" in symbol else 0.00001)
            
        spread_points = (tick["ask"] - tick["bid"]) / point
        if spread_points > max_spread_points:
            return False, f"Spread {spread_points:.0f} pts exceeds {max_spread_points} pts limit"
            
        return True, f"Spread {spread_points:.0f} pts OK"

    # ── MIN ATR VALIDATION (SCALPING) ────────────────────────────────────────

    @staticmethod
    def validate_min_atr(
        trade_style: str,
        symbol: str,
        indicators: Dict,
    ) -> tuple:
        """
        For SCALPING, reject if ATR is below the minimum threshold.

        Returns (allowed: bool, reason: str).
        """
        from style_params import get_style_params

        params = get_style_params(trade_style, symbol)
        min_atr = params.get("min_atr_pips")
        if min_atr is None:
            return True, "No ATR minimum for this style"

        atr = indicators.get("atr", 0)
        pip_multiplier = 10000
        if "XAU" in symbol.upper() or "XAG" in symbol.upper():
            pip_multiplier = 100
        elif "JPY" in symbol.upper():
            pip_multiplier = 100

        atr_pips = atr * pip_multiplier
        if atr_pips < min_atr:
            return False, (
                f"ATR {atr_pips:.0f} pips below minimum {min_atr} "
                f"for {trade_style} {symbol}"
            )
        return True, f"ATR {atr_pips:.0f} pips OK (min: {min_atr})"

    # ── RESULT RECORDING ─────────────────────────────────────────────────────

    def record_trade_result(self, profit: float):
        """Update session stats after a trade closes."""
        if profit >= 0:
            self.stats.record_win(profit)
            logger.info(f"✅ Win recorded | Profit: +{profit:.2f} | Wins: {self.stats.trades_win}")
        else:
            self.stats.record_loss(profit)
            logger.warning(
                f"❌ Loss recorded | Loss: {profit:.2f} | "
                f"Consecutive losses: {self.stats.consecutive_losses}/{config.MAX_CONSECUTIVE_LOSSES}"
            )

    def get_session_summary(self) -> Dict:
        """Return current session performance summary."""
        return {
            "session_start":        self.stats.session_start.isoformat(),
            "trades_total":         self.stats.trades_total,
            "trades_win":           self.stats.trades_win,
            "trades_loss":          self.stats.trades_loss,
            "win_rate_pct":         self.stats.win_rate,
            "consecutive_losses":   self.stats.consecutive_losses,
            "total_pnl":            round(self.stats.total_pnl, 2),
            "trading_halted":       self.stats.trading_halted,
            "halt_reason":          self.stats.halt_reason,
        }
