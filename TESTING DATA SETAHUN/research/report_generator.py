"""Generate the one-year HTML backtest report."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from research.backtest_config import BacktestConfig


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _money(value) -> str:
    try:
        value = float(value)
    except Exception:
        value = 0.0
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def _money_plain(value) -> str:
    try:
        value = float(value)
    except Exception:
        value = 0.0
    return f"${value:,.2f}"


def _pct(value) -> str:
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "0.00%"


def _num(value, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except Exception:
        return "0"


def _max_drawdown(balance_series: pd.Series, start_balance: float) -> float:
    if balance_series.empty:
        return 0.0
    equity = pd.concat([pd.Series([start_balance]), pd.to_numeric(balance_series, errors="coerce").dropna()])
    peaks = equity.cummax()
    drawdown = equity - peaks
    return float(drawdown.min())


def _overall(df: pd.DataFrame, start_balance: float) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_profit": 0.0,
            "final_balance": start_balance,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
        }

    profit = pd.to_numeric(df.get("profit", pd.Series(dtype=float)), errors="coerce").fillna(0)
    wins = profit[profit > 0]
    losses = profit[profit < 0]
    gross_loss = abs(float(losses.sum()))
    return {
        "trades": int(len(df)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": round(len(wins) / len(df) * 100, 2) if len(df) else 0.0,
        "net_profit": round(float(profit.sum()), 2),
        "final_balance": round(start_balance + float(profit.sum()), 2),
        "max_drawdown": round(_max_drawdown(df.get("balance_after", pd.Series(dtype=float)), start_balance), 2),
        "profit_factor": round(float(wins.sum()) / gross_loss, 2) if gross_loss > 0 else 0.0,
        "best_trade": round(float(profit.max()), 2) if len(profit) else 0.0,
        "worst_trade": round(float(profit.min()), 2) if len(profit) else 0.0,
    }


def _table(df: pd.DataFrame, columns: list[str], limit: int = 20) -> str:
    if df.empty:
        return '<div class="empty">No verified rows yet.</div>'

    visible = df.head(limit).copy()
    header = "".join(f"<th>{html.escape(col.replace('_', ' ').title())}</th>" for col in columns)
    rows = []
    for _, row in visible.iterrows():
        cells = []
        for col in columns:
            value = row.get(col, "")
            cells.append(f"<td>{html.escape(str(value))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _best_by(df: pd.DataFrame, column: str) -> str:
    if df.empty or column not in df.columns:
        return "No verified data"
    grouped = df.groupby(column)["profit"].sum().sort_values(ascending=False)
    if grouped.empty:
        return "No verified data"
    return f"{grouped.index[0]} ({_money(grouped.iloc[0])})"


def _load_summary(cfg: BacktestConfig) -> dict:
    path = cfg.backtests_dir / "backtest_summary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def generate_report(cfg: BacktestConfig, pending_reason: Optional[str] = None) -> Path:
    cfg.ensure_dirs()
    fixed = _read_csv(cfg.backtests_dir / "trades_fixed_lot.csv")
    risk = _read_csv(cfg.backtests_dir / "trades_config_risk.csv")
    pattern_ranking = _read_csv(cfg.backtests_dir / "pattern_ranking.csv")
    combo_ranking = _read_csv(cfg.backtests_dir / "pattern_combo_ranking.csv")
    audit = _read_csv(cfg.backtests_dir / "decision_audit.csv")
    summary = _load_summary(cfg)

    verified = not fixed.empty or not risk.empty
    status = "Verified Backtest Result" if verified else "Pending / No verified result yet"
    if pending_reason:
        status = f"{status}: {pending_reason}"

    fixed_overall = _overall(fixed, cfg.start_balance)
    risk_overall = _overall(risk, cfg.start_balance)
    all_trades = pd.concat([fixed, risk], ignore_index=True) if verified else pd.DataFrame()

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    method_notes = summary.get("notes") or [
        "MT5 historical data is the main data source.",
        "SL/TP/trailing are simulated virtually, not broker-side.",
        "Same-candle SL/TP ambiguity is handled conservatively by counting SL first.",
    ]
    method_html = "".join(f"<li>{html.escape(str(note))}</li>" for note in method_notes)

    pattern_columns = [
        "symbol", "timeframe", "pattern_name", "category", "detected_count",
        "used_in_trade_count", "win_count", "loss_count", "win_rate_pct",
        "net_profit", "avg_r", "avg_confidence",
    ]
    combo_columns = ["mode", "symbol", "combo", "used_in_trade_count", "win_count", "loss_count", "win_rate_pct", "net_profit", "avg_r"]
    audit_columns = ["mode", "event", "count"]

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Investment-AI_T - 1 Year Backtest Result</title>
  <style>
    :root {{
      --bg: #101417;
      --panel: #182026;
      --panel-2: #202b33;
      --text: #eff6ef;
      --muted: #9fb0a7;
      --line: rgba(255,255,255,.1);
      --good: #79d98b;
      --bad: #ff7f73;
      --gold: #e6bd65;
      --blue: #80c7ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, 'Times New Roman', serif;
      background:
        radial-gradient(circle at 12% 0%, rgba(230,189,101,.18), transparent 30%),
        linear-gradient(135deg, #0c1013 0%, #18242b 55%, #151210 100%);
      color: var(--text);
    }}
    .wrap {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 42px 0 64px; }}
    .hero {{ border: 1px solid var(--line); background: rgba(24,32,38,.86); border-radius: 28px; padding: 34px; box-shadow: 0 30px 80px rgba(0,0,0,.28); }}
    .eyebrow {{ color: var(--gold); letter-spacing: .16em; text-transform: uppercase; font: 700 12px Arial, sans-serif; }}
    h1 {{ margin: 12px 0 8px; font-size: clamp(34px, 5vw, 66px); line-height: .94; max-width: 980px; }}
    h2 {{ margin: 0; font-size: 28px; }}
    h3 {{ margin: 0 0 8px; font-size: 18px; }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .status {{ display: inline-flex; margin-top: 18px; padding: 10px 14px; border-radius: 999px; background: rgba(230,189,101,.14); color: var(--gold); border: 1px solid rgba(230,189,101,.32); font: 700 13px Arial, sans-serif; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-top: 22px; }}
    .card {{ background: rgba(32,43,51,.88); border: 1px solid var(--line); border-radius: 22px; padding: 20px; }}
    .metric .label {{ color: var(--muted); font: 700 12px Arial, sans-serif; text-transform: uppercase; letter-spacing: .08em; }}
    .metric .value {{ display: block; margin-top: 8px; font-size: 28px; font-weight: 800; }}
    .good {{ color: var(--good); }} .bad {{ color: var(--bad); }} .gold {{ color: var(--gold); }} .blue {{ color: var(--blue); }}
    section {{ margin-top: 24px; }}
    .section-head {{ display: flex; justify-content: space-between; align-items: end; gap: 18px; margin: 34px 0 14px; }}
    .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 16px; background: rgba(24,32,38,.78); border: 1px solid var(--line); }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; font: 13px Arial, sans-serif; vertical-align: top; }}
    th {{ color: var(--gold); background: rgba(230,189,101,.08); text-transform: uppercase; letter-spacing: .06em; font-size: 11px; }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{ padding: 22px; border: 1px dashed var(--line); border-radius: 18px; color: var(--muted); }}
    .method {{ background: rgba(128,199,255,.08); border: 1px solid rgba(128,199,255,.22); border-radius: 22px; padding: 20px; }}
    li {{ margin: 8px 0; color: var(--muted); }}
    code {{ color: var(--gold); }}
    @media (max-width: 860px) {{ .grid, .two {{ grid-template-columns: 1fr; }} .hero {{ padding: 24px; }} table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
  <main class="wrap">
    <header class="hero">
      <div class="eyebrow">Investment-AI_T historical result</div>
      <h1>1-Year Backtest Result + Pattern Analytics</h1>
      <p>
        Range: <strong>{cfg.start:%d %b %Y}</strong> to <strong>{cfg.end:%d %b %Y}</strong>.
        Symbols: <strong>{html.escape(', '.join(cfg.symbols))}</strong>.
        Timeframes: <strong>{html.escape(', '.join(cfg.timeframes))}</strong>.
      </p>
      <span class="status">{html.escape(status)}</span>
      <div class="grid">
        <div class="card metric"><span class="label">Fixed Lot Net P/L</span><span class="value {'good' if fixed_overall['net_profit'] >= 0 else 'bad'}">{_money(fixed_overall['net_profit'])}</span></div>
        <div class="card metric"><span class="label">Config Risk Net P/L</span><span class="value {'good' if risk_overall['net_profit'] >= 0 else 'bad'}">{_money(risk_overall['net_profit'])}</span></div>
        <div class="card metric"><span class="label">Pattern Detections</span><span class="value gold">{_num(summary.get('pattern_detections', 0), 0)}</span></div>
        <div class="card metric"><span class="label">Generated</span><span class="value blue" style="font-size:18px">{generated_at}</span></div>
      </div>
    </header>

    <section>
      <div class="section-head"><h2>Overall Result</h2><p>Two views: neutral fixed lot and realistic config-risk sizing.</p></div>
      <div class="two">
        <div class="card">
          <h3>Fixed Lot Report</h3>
          <p>Default lot: <code>{cfg.fixed_lot}</code>. This shows pattern quality without compounding noise.</p>
          <div class="grid" style="grid-template-columns: repeat(2, minmax(0, 1fr));">
            <div class="metric"><span class="label">Trades</span><span class="value">{fixed_overall['trades']}</span></div>
            <div class="metric"><span class="label">Win Rate</span><span class="value">{_pct(fixed_overall['win_rate'])}</span></div>
            <div class="metric"><span class="label">Profit Factor</span><span class="value">{_num(fixed_overall['profit_factor'])}</span></div>
            <div class="metric"><span class="label">Max Drawdown</span><span class="value bad">{_money(fixed_overall['max_drawdown'])}</span></div>
          </div>
        </div>
        <div class="card">
          <h3>Config Risk Report</h3>
          <p>Start balance: <code>${cfg.start_balance:,.2f}</code>. Uses configured risk sizing and compounding.</p>
          <div class="grid" style="grid-template-columns: repeat(2, minmax(0, 1fr));">
            <div class="metric"><span class="label">Final Balance</span><span class="value">{_money_plain(risk_overall['final_balance'])}</span></div>
            <div class="metric"><span class="label">Win Rate</span><span class="value">{_pct(risk_overall['win_rate'])}</span></div>
            <div class="metric"><span class="label">Best Trade</span><span class="value good">{_money(risk_overall['best_trade'])}</span></div>
            <div class="metric"><span class="label">Worst Trade</span><span class="value bad">{_money(risk_overall['worst_trade'])}</span></div>
          </div>
        </div>
      </div>
    </section>

    <section>
      <div class="section-head"><h2>Pattern Result Table</h2><p>Berapa banyak pattern muncul, digunakan, menang, kalah, dan net P/L.</p></div>
      {_table(pattern_ranking, pattern_columns, limit=30)}
    </section>

    <section>
      <div class="section-head"><h2>Confluence Combos</h2><p>Combo pattern yang paling membantu atau merugikan.</p></div>
      {_table(combo_ranking, combo_columns, limit=24)}
    </section>

    <section>
      <div class="section-head"><h2>Market Behavior</h2><p>Best session, day, timeframe, symbol, dan pattern focus.</p></div>
      <div class="grid">
        <div class="card"><h3>Best Symbol</h3><p class="value gold">{html.escape(_best_by(all_trades, 'symbol'))}</p></div>
        <div class="card"><h3>Best Session</h3><p class="value gold">{html.escape(_best_by(all_trades, 'session'))}</p></div>
        <div class="card"><h3>Best Day</h3><p class="value gold">{html.escape(_best_by(all_trades, 'day_of_week'))}</p></div>
        <div class="card"><h3>Best Timeframe</h3><p class="value gold">{html.escape(_best_by(all_trades, 'timeframe'))}</p></div>
      </div>
    </section>

    <section>
      <div class="section-head"><h2>Decision Audit</h2><p>Signal BUY/SELL/HOLD, skipped reason, risk blocked, dan exit reason.</p></div>
      {_table(audit, audit_columns, limit=60)}
    </section>

    <section>
      <div class="section-head"><h2>Methodology</h2><p>Ringkasan cara result dikira supaya kita boleh percaya report ini.</p></div>
      <div class="method">
        <ul>{method_html}</ul>
        <p>
          Output files: <code>TESTING DATA SETAHUN/storage/history/</code>,
          <code>TESTING DATA SETAHUN/storage/features/</code>,
          <code>TESTING DATA SETAHUN/storage/backtests/trades_fixed_lot.csv</code>,
          <code>TESTING DATA SETAHUN/storage/backtests/trades_config_risk.csv</code>,
          <code>TESTING DATA SETAHUN/storage/backtests/pattern_ranking.csv</code>, and
          <code>TESTING DATA SETAHUN/storage/backtests/pattern_combo_ranking.csv</code>.
        </p>
      </div>
    </section>
  </main>
</body>
</html>
"""

    tmp_path = cfg.report_path.with_suffix(cfg.report_path.suffix + ".tmp")
    tmp_path.write_text(html_text, encoding="utf-8")
    tmp_path.replace(cfg.report_path)
    return cfg.report_path
