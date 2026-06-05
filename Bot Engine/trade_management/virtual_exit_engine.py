"""Virtual SL/TP and hidden trailing-stop logic.

The broker does not receive these levels when USE_BROKER_SL_TP=False. They are
stored locally and acted on by the bot while it is running.
"""

from typing import Dict, Optional
from datetime import datetime

import config


def _round_price(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 5)
    except (TypeError, ValueError):
        return None


def _as_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class VirtualExitEngine:
    """Calculates hidden exit levels and detects virtual exit triggers."""

    def seed_state(
        self,
        *,
        ticket: int,
        symbol: str,
        action: str,
        entry_price: float,
        lot: float,
        virtual_sl: float,
        virtual_tp: float,
        reason: str,
        trade_style: str = "INTRADAY",
        pattern_snapshot: Optional[Dict] = None,
    ) -> Dict:
        return {
            "ticket": int(ticket),
            "symbol": symbol,
            "action": action,
            "direction": action,
            "trade_style": trade_style,
            "entry_price": _round_price(entry_price),
            "lot": float(lot or 0),
            "reason": reason,
            "target": _round_price(virtual_tp),
            "virtual_sl": _round_price(virtual_sl),
            "virtual_tp": _round_price(virtual_tp),
            "virtual_trailing_stop": None,
            "profit_lock_level": None,
            "max_favorable_price": _round_price(entry_price),
            "max_drawdown": 0.0,
            "floating_profit": 0.0,
            "current_status": "OPEN",
            "exit_reason": None,
            "pattern_snapshot": pattern_snapshot or {},
            "timestamp": datetime.now().isoformat(),
        }

    def update_state(
        self,
        state: Dict,
        position: Dict,
        indicators: Dict,
    ) -> Dict:
        direction = state.get("action") or position.get("direction")
        entry = _as_float(state.get("entry_price"), _as_float(position.get("price_open"), 0.0))
        current = _as_float(position.get("price_current"), entry)
        profit = _as_float(position.get("profit"), 0.0) or 0.0
        atr = _as_float(indicators.get("atr"), None) if indicators else None

        state["last_price"] = _round_price(current)
        state["floating_profit"] = round(profit, 2)

        if direction == "BUY":
            max_favorable = max(_as_float(state.get("max_favorable_price"), entry), current)
            drawdown = max(0.0, entry - current)
        else:
            max_favorable = min(_as_float(state.get("max_favorable_price"), entry), current)
            drawdown = max(0.0, current - entry)

        state["max_favorable_price"] = _round_price(max_favorable)
        state["max_drawdown"] = max(_as_float(state.get("max_drawdown"), 0.0), round(drawdown, 5))

        if config.USE_VIRTUAL_TRAILING_STOP and atr and atr > 0:
            self._update_trailing_state(state, direction, entry, current, atr)

        state["current_status"] = "MANAGED"
        return state

    def _update_trailing_state(
        self,
        state: Dict,
        direction: str,
        entry: float,
        current: float,
        atr: float,
    ) -> None:
        # Use per-style trailing parameters from style_params
        trade_style = state.get("trade_style", "INTRADAY")
        symbol = state.get("symbol", "")

        try:
            from style_params import get_style_params
            params = get_style_params(trade_style, symbol).copy()
        except Exception:
            # Fallback to original hardcoded values
            params = {
                "trail_stage1": 0.5,
                "trail_stage2": 1.5,
                "trail_distance": 1.0,
            }

        # Override with individual trailing settings from dashboard if available
        try:
            from account_settings import AccountSettings
            acct = AccountSettings(getattr(config, 'ACCOUNT_ID', 'acc_1'))
            dashboard_trailing = acct.get_trailing_settings(trade_style)
            
            # If dashboard returned None or 0, the user left it empty to DISABLE trailing.
            for key in ["trail_stage1", "trail_stage2", "trail_distance"]:
                if key in dashboard_trailing:
                    val = dashboard_trailing[key]
                    if val in (None, 0, 0.0):
                        params[key] = None
                    else:
                        params[key] = val
        except Exception as e:
            pass

        # If trailing is disabled for this style (e.g. EUR/USD scalping or user disabled it)
        if params.get("trail_stage1") is None or params.get("trail_stage2") is None:
            return

        # Check if it's a manual trade. If so, respect manage_manual_be setting.
        is_manual = state.get("reason") in ("Adopted open broker position", "Manual Trade (Auto-managed)")
        if is_manual:
            try:
                from account_settings import AccountSettings
                acct = AccountSettings(getattr(config, 'ACCOUNT_ID', 'acc_1'))
                if not acct.manage_manual_be:
                    return
            except Exception:
                pass

        stage1_distance = params["trail_stage1"] * atr
        stage2_distance = params["trail_stage2"] * atr
        trail_distance = params["trail_distance"] * atr

        # Provide a helpful string to the dashboard showing activation price
        if state.get("virtual_trailing_stop") is None:
            if direction == "BUY":
                state["virtual_trailing_stop"] = f"start: {_round_price(entry + stage2_distance)}"
            else:
                state["virtual_trailing_stop"] = f"start: {_round_price(entry - stage2_distance)}"

        if direction == "BUY":
            profit_distance = current - entry
            if profit_distance > stage1_distance:
                pip_size = config.get_pip_multiplier(state.get("symbol", ""))
                be_plus = 2 * pip_size  # 2 pips BE+
                # Only update profit_lock_level if we are improving it
                new_lock = _round_price(entry + be_plus)
                old_lock = _as_float(state.get("profit_lock_level"), None)
                if old_lock is None or new_lock > old_lock:
                    state["profit_lock_level"] = new_lock

            if profit_distance > stage2_distance:
                candidate = current - trail_distance
                pip_size = config.get_pip_multiplier(state.get("symbol", ""))
                min_lock = entry + (2 * pip_size)
                candidate = max(candidate, min_lock)
                old_trail = _as_float(state.get("virtual_trailing_stop"), None)
                if old_trail is None or candidate > old_trail:
                    state["virtual_trailing_stop"] = _round_price(candidate)
        else:
            profit_distance = entry - current
            if profit_distance > stage1_distance:
                pip_size = config.get_pip_multiplier(state.get("symbol", ""))
                be_plus = 2 * pip_size  # 2 pips BE+
                new_lock = _round_price(entry - be_plus)
                old_lock = _as_float(state.get("profit_lock_level"), None)
                if old_lock is None or new_lock < old_lock:
                    state["profit_lock_level"] = new_lock

            if profit_distance > stage2_distance:
                candidate = current + trail_distance
                pip_size = config.get_pip_multiplier(state.get("symbol", ""))
                max_lock = entry - (2 * pip_size)
                candidate = min(candidate, max_lock)
                old_trail = _as_float(state.get("virtual_trailing_stop"), None)
                if old_trail is None or candidate < old_trail:
                    state["virtual_trailing_stop"] = _round_price(candidate)

    def get_exit_trigger(self, state: Dict, position: Dict) -> Optional[str]:
        if not config.USE_VIRTUAL_SL_TP and not config.USE_VIRTUAL_TRAILING_STOP:
            return None

        direction = state.get("action") or position.get("direction")
        current = _as_float(position.get("price_current"), None)
        if current is None:
            return None

        virtual_sl = _as_float(state.get("virtual_sl"), None)
        virtual_tp = _as_float(state.get("virtual_tp"), None)
        profit_lock = _as_float(state.get("profit_lock_level"), None)
        trailing = _as_float(state.get("virtual_trailing_stop"), None)

        if direction == "BUY":
            if config.USE_VIRTUAL_SL_TP and virtual_sl is not None and current <= virtual_sl:
                return "virtual_sl"
            if config.USE_VIRTUAL_SL_TP and virtual_tp is not None and current >= virtual_tp:
                return "virtual_tp"
            if config.USE_VIRTUAL_TRAILING_STOP and trailing is not None and current <= trailing:
                return "virtual_trailing_stop"
            if config.USE_VIRTUAL_TRAILING_STOP and profit_lock is not None and current <= profit_lock:
                return "profit_lock"
        else:
            if config.USE_VIRTUAL_SL_TP and virtual_sl is not None and current >= virtual_sl:
                return "virtual_sl"
            if config.USE_VIRTUAL_SL_TP and virtual_tp is not None and current <= virtual_tp:
                return "virtual_tp"
            if config.USE_VIRTUAL_TRAILING_STOP and trailing is not None and current >= trailing:
                return "virtual_trailing_stop"
            if config.USE_VIRTUAL_TRAILING_STOP and profit_lock is not None and current >= profit_lock:
                return "profit_lock"

        return None
