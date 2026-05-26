"""Offline smoke tests for Investment-AI_T.

These tests avoid MT5 and real AI/API calls. They validate the core safety
paths that should work before running the bot on a Windows laptop.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "Bot Engine"
sys.path.insert(0, str(BOT_DIR))


def _reload_ai_engine():
    import ai_engine

    return importlib.reload(ai_engine)


def test_json_parser_and_signal_validation():
    ai_engine = _reload_ai_engine()

    parsed = ai_engine._extract_json('```json\n{"action":"BUY","confidence":0.83,"reason":"valid setup"}\n```')
    signal = ai_engine._validate_signal(parsed)

    assert signal["action"] == "BUY"
    assert signal["confidence"] == 0.83
    assert signal["reason"] == "valid setup"

    invalid = ai_engine._validate_signal({"action": "MOON", "confidence": 9, "reason": "bad"})
    assert invalid["action"] == "HOLD"
    assert invalid["confidence"] == 1.0


def test_ai_timeout_becomes_hold():
    ai_engine = _reload_ai_engine()
    indicators = _fake_indicators("XAUUSD")

    with patch.object(ai_engine, "query_ai_provider", return_value=None):
        signal = ai_engine.get_ai_signal(indicators, 2300.0, 2300.2, symbol="XAUUSD")

    assert signal["action"] == "HOLD"
    assert "unreachable" in signal["reason"].lower() or "timed out" in signal["reason"].lower()


def test_invalid_json_becomes_hold():
    ai_engine = _reload_ai_engine()
    indicators = _fake_indicators("EURUSD")

    with patch.object(ai_engine, "query_ai_provider", return_value="not-json"):
        signal = ai_engine.get_ai_signal(indicators, 1.1, 1.1002, symbol="EURUSD")

    assert signal["action"] == "HOLD"
    assert signal["reason"] == "Invalid JSON response"


def test_risk_review_timeout_rejects_trade():
    ai_engine = _reload_ai_engine()
    with patch.object(ai_engine.config, "ENABLE_RISK_REVIEW", True):
        with patch.object(ai_engine, "query_ai_provider", return_value=None):
            review = ai_engine.review_trade_risk(
                {"action": "BUY", "confidence": 0.8, "reason": "test"},
                {"symbol": "XAUUSD", "detected_patterns": [], "pattern_bias": {}},
                {"lot": 0.01, "sl": 2290, "tp": 2330, "sl_pips": 50, "tp_pips": 150},
                "XAUUSD",
            )

    assert review["approved"] is False
    assert "unreachable" in review["reason"].lower() or "timed out" in review["reason"].lower()


def test_virtual_exit_triggers():
    from trade_management.virtual_exit_engine import VirtualExitEngine

    engine = VirtualExitEngine()
    state = engine.seed_state(
        ticket=1,
        symbol="XAUUSD",
        action="BUY",
        entry_price=2300.0,
        lot=0.01,
        virtual_sl=2295.0,
        virtual_tp=2310.0,
        reason="test",
    )

    assert engine.get_exit_trigger(state, {"direction": "BUY", "price_current": 2294.9}) == "virtual_sl"
    assert engine.get_exit_trigger(state, {"direction": "BUY", "price_current": 2310.1}) == "virtual_tp"

    updated = engine.update_state(state, {"direction": "BUY", "price_current": 2305.0, "profit": 2.0}, {"atr": 2.0})
    assert updated["virtual_trailing_stop"] is not None
    assert engine.get_exit_trigger(updated, {"direction": "BUY", "price_current": updated["virtual_trailing_stop"] - 0.01}) in {
        "virtual_trailing_stop",
        "profit_lock",
    }


def test_pattern_usage_open_close_stats():
    from trade_management.pattern_usage_tracker import (
        build_pattern_snapshot,
        update_stats_on_close,
        update_stats_on_open,
    )

    indicators = {
        "detected_patterns": [
            {
                "name": "Bullish Engulfing",
                "category": "candlestick",
                "timeframe": "M5",
                "direction": "bullish",
                "confidence": 0.88,
                "priority": "HIGH",
            }
        ]
    }
    snapshot = build_pattern_snapshot(indicators, "XAUUSD", "BUY")
    stats = update_stats_on_open({}, 1001, snapshot)

    snapshot["ticket"] = 1001
    stats = update_stats_on_close(stats, snapshot, 12.5, "virtual_tp")
    item = next(iter(stats.values()))

    assert snapshot["primary_pattern"] == "Bullish Engulfing"
    assert item["used_count"] == 1
    assert item["closed_trade_count"] == 1
    assert item["win_count"] == 1
    assert item["win_rate"] == 100.0
    assert item["net_profit"] == 12.5


def test_supabase_disabled_never_raises():
    from trade_management.supabase_sync import SupabaseSync

    sync = SupabaseSync()
    sync.upsert_heartbeat(cycle=1, message="smoke")
    sync.upsert_active_trade({"ticket": 1, "symbol": "XAUUSD", "pattern_snapshot": {}})
    sync.upsert_pattern_stats({})
    sync.insert_trade_event(1, "smoke", "disabled")


def test_vercel_dashboard_contains_live_trade_and_manual_fallback_widgets():
    html = (ROOT / "Dashboard" / "index.html").read_text(encoding="utf-8")

    required_fragments = [
        'id="manualMode"',
        "heartbeat stale",
        "<th>Opened</th>",
        "${safe(r.primary_pattern)}",
        "${safe(r.confluence_combo)}",
        "${price(r.virtual_sl)}",
        "${price(r.virtual_tp)}",
        "${price(r.virtual_trailing_stop)}",
        "formatAge(ageSeconds)",
        "active_trades?select=*",
        "pattern_usage_stats?select=*",
        "trade_events?select=*",
        "styleTag(r.trade_style)",
        "visionTag(r.vision_bias)",
        "<th>Style</th>",
        "<th>Vision</th>",
    ]

    for fragment in required_fragments:
        assert fragment in html, f"Dashboard missing fragment: {fragment}"


def test_screenshot_failure_becomes_hold():
    """When screenshot capture fails, vision AI should return HOLD."""
    import vision_engine

    # Empty chart_paths simulates capture failure
    result = vision_engine.get_vision_signal(
        symbol="XAUUSD",
        current_price=2300.0,
        indicators=_fake_indicators("XAUUSD"),
        chart_paths={},
        trade_memory=None,
    )
    assert result["action"] == "HOLD"
    assert result["confidence"] == 0.0


def test_invalid_vision_json_becomes_hold():
    """When vision AI returns invalid JSON, extraction should return None → HOLD."""
    import vision_engine

    result = vision_engine._extract_vision_json("this is not json at all")
    assert result is None

    result = vision_engine._extract_vision_json('{"action": invalid}')
    assert result is None

    # Valid JSON but nonsense action
    validated = vision_engine._validate_vision_signal({"action": "MOON", "confidence": 5})
    assert validated["action"] == "HOLD"
    assert validated["confidence"] == 1.0


def test_conflicting_text_image_decision_becomes_hold():
    """When text AI says BUY and vision AI says SELL, merger should HOLD."""
    ai_engine = _reload_ai_engine()

    text_signal = {
        "action": "BUY",
        "confidence": 0.85,
        "trade_style": "INTRADAY",
        "reason": "text says buy",
    }
    vision_signal = {
        "action": "SELL",
        "confidence": 0.80,
        "trade_style": "INTRADAY",
        "image_bias": "bearish",
        "support": [2290.0],
        "resistance": [2310.0],
        "reason": "vision says sell",
    }
    pattern_bias = {"bias": "none"}

    merged = ai_engine.merge_decisions(text_signal, vision_signal, pattern_bias)
    assert merged["action"] == "HOLD", f"Expected HOLD but got {merged['action']}"
    assert merged["confidence"] == 0.0


def test_valid_merged_decision_keeps_trade_style():
    """When text and vision agree, trade_style from text AI is preserved."""
    ai_engine = _reload_ai_engine()

    text_signal = {
        "action": "BUY",
        "confidence": 0.85,
        "trade_style": "SWING",
        "reason": "text says buy",
    }
    vision_signal = {
        "action": "BUY",
        "confidence": 0.80,
        "trade_style": "INTRADAY",
        "image_bias": "bullish",
        "support": [2290.0],
        "resistance": [2310.0],
        "reason": "vision agrees buy",
    }
    pattern_bias = {"bias": "bullish"}

    merged = ai_engine.merge_decisions(text_signal, vision_signal, pattern_bias)
    assert merged["action"] == "BUY"
    assert merged["trade_style"] == "SWING"  # from text AI
    assert merged["image_bias"] == "bullish"
    assert merged["confidence"] > 0


def test_supabase_disabled_does_not_crash_with_new_fields():
    """Supabase disabled mode should not crash with new trade_style/vision_bias fields."""
    from trade_management.supabase_sync import SupabaseSync

    sync = SupabaseSync()
    sync.upsert_active_trade({
        "ticket": 9999,
        "symbol": "XAUUSD",
        "pattern_snapshot": {},
        "trade_style": "SCALPING",
        "vision_bias": "bullish",
        "image_bias": "bullish",
    })
    # If we get here without exception, the test passes


def run_all():
    tests = [
        test_json_parser_and_signal_validation,
        test_ai_timeout_becomes_hold,
        test_invalid_json_becomes_hold,
        test_risk_review_timeout_rejects_trade,
        test_virtual_exit_triggers,
        test_pattern_usage_open_close_stats,
        test_supabase_disabled_never_raises,
        test_vercel_dashboard_contains_live_trade_and_manual_fallback_widgets,
        test_screenshot_failure_becomes_hold,
        test_invalid_vision_json_becomes_hold,
        test_conflicting_text_image_decision_becomes_hold,
        test_valid_merged_decision_keeps_trade_style,
        test_supabase_disabled_does_not_crash_with_new_fields,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} tests passed.")
    if failed:
        print(f"{failed} test(s) FAILED.")
        return 1
    print("All offline smoke tests passed.")
    return 0


def _fake_indicators(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "price": 2300.0 if "XAU" in symbol else 1.1,
        "market_regime": "trending",
        "adx": 28,
        "h4_trend": "bullish",
        "h1_resistance": 2310.0 if "XAU" in symbol else 1.105,
        "h1_support": 2290.0 if "XAU" in symbol else 1.095,
        "h1_macd_trend": "bullish",
        "m15_rsi": 55,
        "m15_liquidity_sweep": "none",
        "m15_pattern": "none",
        "m5_liquidity_sweep": "none",
        "m5_pattern": "none",
        "pattern_bias": {},
        "detected_patterns": [],
        "atr": 1.5 if "XAU" in symbol else 0.0008,
    }


if __name__ == "__main__":
    run_all()
