"""Pattern usage snapshots and lightweight performance stats."""

from datetime import datetime
from typing import Dict, List, Optional

import config


def _priority_rank(value) -> int:
    text = str(value or "").strip().upper()
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(text, 0)


def _pattern_score(pattern: Dict) -> float:
    confidence = float(pattern.get("confidence", 0) or 0)
    return (_priority_rank(pattern.get("priority")) * 10) + confidence


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def build_pattern_snapshot(indicators: Dict, symbol: str, action: str) -> Dict:
    """Create a compact pattern snapshot to attach to an opened trade."""
    patterns = indicators.get("detected_patterns") or []
    sorted_patterns = sorted(patterns, key=_pattern_score, reverse=True)
    selected = sorted_patterns[: max(1, config.PATTERN_CONFLUENCE_LIMIT)]
    primary = selected[0] if selected else {}

    names = [str(p.get("name", "Unknown")) for p in selected]
    categories = [str(p.get("category", "")) for p in selected]
    timeframes = [str(p.get("timeframe", "")) for p in selected]
    confidences = [float(p.get("confidence", 0) or 0) for p in selected]

    return {
        "symbol": symbol,
        "direction": action,
        "primary_pattern": primary.get("name", "No primary pattern"),
        "primary_category": primary.get("category", ""),
        "primary_timeframe": primary.get("timeframe", ""),
        "pattern_names": names,
        "pattern_categories": categories,
        "pattern_timeframes": timeframes,
        "confluence_combo": " + ".join(names[: config.PATTERN_CONFLUENCE_LIMIT]),
        "pattern_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "pattern_count": len(patterns),
        "patterns": selected,
    }


def build_usage_rows(
    ticket: int,
    snapshot: Dict,
    *,
    trade_status: str = "open",
    profit: Optional[float] = None,
    exit_reason: str = "",
) -> List[Dict]:
    rows = []
    patterns = snapshot.get("patterns") or []
    opened_at = snapshot.get("opened_at") or snapshot.get("timestamp")
    if not patterns:
        row = {
            "ticket": ticket,
            "symbol": snapshot.get("symbol"),
            "direction": snapshot.get("direction"),
            "trade_opened_at": opened_at,
            "pattern_name": "No primary pattern",
            "category": "",
            "timeframe": "",
            "direction_bias": "",
            "confidence": 0.0,
            "priority": "",
            "is_primary": True,
            "trade_status": trade_status,
            "exit_reason": exit_reason,
            "profit": profit,
            "updated_at": _utc_now(),
        }
        row["id"] = _usage_row_id(ticket, row)
        rows.append(row)
        return rows

    primary_name = snapshot.get("primary_pattern")
    for pattern in patterns:
        name = str(pattern.get("name", "Unknown"))
        row = {
            "ticket": ticket,
            "symbol": snapshot.get("symbol"),
            "direction": snapshot.get("direction"),
            "trade_opened_at": opened_at,
            "pattern_name": name,
            "category": pattern.get("category", ""),
            "timeframe": pattern.get("timeframe", ""),
            "direction_bias": pattern.get("direction", ""),
            "confidence": float(pattern.get("confidence", 0) or 0),
            "priority": pattern.get("priority", ""),
            "is_primary": name == primary_name,
            "trade_status": trade_status,
            "exit_reason": exit_reason,
            "profit": profit,
            "updated_at": _utc_now(),
        }
        row["id"] = _usage_row_id(ticket, row)
        rows.append(row)
    return rows


def update_stats_on_open(stats: Dict, ticket: int, snapshot: Dict) -> Dict:
    stats = stats or {}

    for row in build_usage_rows(ticket, snapshot):
        key = _stats_key(row)
        item = stats.get(key, {})
        item.setdefault("id", key)
        item.setdefault("symbol", row.get("symbol"))
        item.setdefault("timeframe", row.get("timeframe"))
        item.setdefault("pattern_name", row.get("pattern_name"))
        item.setdefault("category", row.get("category"))
        item["detected_count"] = int(item.get("detected_count", 0)) + 1
        item["used_count"] = int(item.get("used_count", 0)) + 1
        item["open_trade_count"] = int(item.get("open_trade_count", 0)) + 1
        item["avg_confidence"] = _rolling_avg(
            float(item.get("avg_confidence", 0) or 0),
            int(item.get("used_count", 1)),
            float(row.get("confidence", 0) or 0),
        )
        item["updated_at"] = _utc_now()
        stats[key] = item

    return stats


def update_stats_on_close(
    stats: Dict,
    snapshot: Dict,
    profit: float,
    exit_reason: str = "",
) -> Dict:
    stats = stats or {}
    profit = float(profit or 0.0)

    for row in build_usage_rows(
        int(snapshot.get("ticket", 0) or 0),
        snapshot,
        trade_status="closed",
        profit=profit,
        exit_reason=exit_reason,
    ):
        key = _stats_key(row)
        item = stats.get(key, {})
        item.setdefault("id", key)
        item.setdefault("symbol", row.get("symbol"))
        item.setdefault("timeframe", row.get("timeframe"))
        item.setdefault("pattern_name", row.get("pattern_name"))
        item.setdefault("category", row.get("category"))
        item["open_trade_count"] = max(0, int(item.get("open_trade_count", 0)) - 1)
        item["closed_trade_count"] = int(item.get("closed_trade_count", 0)) + 1
        if profit >= 0:
            item["win_count"] = int(item.get("win_count", 0)) + 1
        else:
            item["loss_count"] = int(item.get("loss_count", 0)) + 1
        item["net_profit"] = round(float(item.get("net_profit", 0) or 0) + profit, 2)

        closed = int(item.get("closed_trade_count", 0))
        wins = int(item.get("win_count", 0))
        item["win_rate"] = round((wins / closed) * 100, 2) if closed else 0.0
        item["avg_profit"] = round(float(item.get("net_profit", 0) or 0) / closed, 2) if closed else 0.0
        item["last_exit_reason"] = exit_reason
        item["updated_at"] = _utc_now()
        stats[key] = item

    return stats


def _stats_key(row: Dict) -> str:
    return "|".join([
        str(row.get("symbol", "")),
        str(row.get("timeframe", "")),
        str(row.get("pattern_name", "")),
    ])


def _usage_row_id(ticket: int, row: Dict) -> str:
    return "|".join([
        str(ticket),
        str(row.get("timeframe", "")),
        str(row.get("pattern_name", "")),
    ])


def _rolling_avg(previous_avg: float, count_after: int, new_value: float) -> float:
    if count_after <= 1:
        return round(new_value, 4)
    previous_count = count_after - 1
    return round(((previous_avg * previous_count) + new_value) / count_after, 4)
