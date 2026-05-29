"""
generate_ai_report.py - Generate AI-Readable Backtest Analysis Report
=====================================================================
Run selepas backtest selesai untuk generate fail markdown yang boleh
dicopy-paste ke mana-mana AI (ChatGPT, Claude, Gemini, dll).

Usage:
    python generate_ai_report.py                    # Auto-detect latest report
    python generate_ai_report.py report.json        # Specific JSON file
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

TESTING_ROOT = Path(__file__).resolve().parent
REPORTS_DIR  = TESTING_ROOT / "reports"
STORAGE_DIR  = TESTING_ROOT / "storage"


# ── Load latest backtest JSON ──────────────────────────────────────────────────

def find_latest_json() -> Path | None:
    jsons = sorted(REPORTS_DIR.glob("backtest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsons[0] if jsons else None


def load_results(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── Format helpers ─────────────────────────────────────────────────────────────

def pct(v): return f"{v:+.1f}%"
def usd(v): return f"${v:,.2f}"
def sign(v): return f"+{v:.2f}" if v >= 0 else f"{v:.2f}"


# ── Build the markdown report ──────────────────────────────────────────────────

def build_report(data: dict) -> str:
    now       = datetime.now().strftime("%Y-%m-%d %H:%M")
    gen_at    = data.get("generated_at", "unknown")
    symbols   = data.get("symbols", [])
    styles    = data.get("styles", [])
    s_date    = data.get("start_date", "")[:10]
    e_date    = data.get("end_date", "")[:10]
    balance   = data.get("start_balance", 10000)
    dyn_lot   = data.get("use_dynamic_lot", True)
    results   = data.get("results", {})

    lines = []
    lines.append("# Investment-AI_T — Backtest Analysis Report")
    lines.append(f"> Generated: {now}  |  Backtest run: {gen_at[:16]}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📋 Tujuan Fail Ini")
    lines.append("")
    lines.append("Fail ini adalah ringkasan lengkap hasil backtesting bot trading Investment-AI_T.")
    lines.append("Ia direka untuk dikongsi dengan mana-mana AI (ChatGPT, Claude, Gemini, dll)")
    lines.append("supaya AI tersebut boleh:")
    lines.append("- Menganalisis kelemahan strategi")
    lines.append("- Mencadangkan parameter yang lebih baik")
    lines.append("- Memperbaiki logik entry/exit")
    lines.append("- Membandingkan gaya trading (Scalping vs Intraday vs Swing)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── SYSTEM OVERVIEW ──────────────────────────────────────────────────────
    lines.append("## 🤖 Sistem & Strategi Semasa")
    lines.append("")
    lines.append("### Rekabentuk Bot")
    lines.append("- **Nama:** Investment-AI_T — AI-powered MT5 trading bot")
    lines.append("- **Bahasa:** Python (backend) + HTML/JS (dashboard)")
    lines.append("- **Broker:** MetaTrader 5 (MT5)")
    lines.append("- **Signal Engine:** Gemini AI + deterministic pattern engine (EMA, ADX, RSI)")
    lines.append("- **Exits:** Virtual SL/TP/Trailing (hidden dari broker)")
    lines.append("")
    lines.append("### Signal Logic (Backtest — tanpa AI call)")
    lines.append("| Style | Timeframe | Signal |")
    lines.append("|-------|-----------|--------|")
    lines.append("| SCALPING | H1 | EMA9 cross EMA21 |")
    lines.append("| INTRADAY | H1 | EMA stack (9 > 21 > 50) + RSI + ADX > 20 |")
    lines.append("| SWING | H4 | Golden/Death Cross EMA50/200 |")
    lines.append("")
    lines.append("### SL/TP Parameters")
    lines.append("| Style | Symbol | SL ATR mult | TP ATR mult | SL range (pips) | Min R:R |")
    lines.append("|-------|--------|-------------|-------------|-----------------|---------|")
    lines.append("| SCALPING | XAUUSD | 1.0× | 1.5× | 20-80 | 1.0 |")
    lines.append("| SCALPING | EURUSD | 1.0× | 2.0× | 5-10 | 1.0 |")
    lines.append("| INTRADAY | XAUUSD | 1.5× | 3.0× | 50-250 | 2.0 |")
    lines.append("| INTRADAY | EURUSD | 1.5× | 3.0× | 20-40 | 2.0 |")
    lines.append("| SWING | XAUUSD | 2.5× | 5.0× | 150-300 | 2.0 |")
    lines.append("| SWING | EURUSD | 2.0× | 4.0× | 80-150 | 2.0 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── BACKTEST CONFIG ───────────────────────────────────────────────────────
    lines.append("## ⚙️ Konfigurasi Backtest")
    lines.append("")
    lines.append(f"| Parameter | Nilai |")
    lines.append(f"|-----------|-------|")
    lines.append(f"| Symbols | {', '.join(symbols)} |")
    lines.append(f"| Styles | {', '.join(styles)} |")
    lines.append(f"| Tempoh | {s_date} → {e_date} |")
    lines.append(f"| Starting Balance | {usd(balance)} |")
    lines.append(f"| Lot Mode | {'Dynamic (risk-based)' if dyn_lot else 'Fixed lot'} |")
    lines.append(f"| Data Source | Yahoo Finance (1h interval) |")
    lines.append(f"| Signal Min Confidence | 0.55 |")
    lines.append(f"| Max Open Trades/Symbol | 3 |")
    lines.append(f"| Min Bars Between Entries | 3 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── RESULTS PER SYMBOL ───────────────────────────────────────────────────
    lines.append("## 📊 Keputusan Backtest")
    lines.append("")

    all_stats = []

    for sym, sym_data in results.items():
        lines.append(f"### Symbol: {sym}")
        lines.append("")

        sym_styles = sym_data.get("styles", {})

        # Summary table
        lines.append("| Style | Trades | Win% | Net P&L | Return | Profit Factor | Max DD | Avg R |")
        lines.append("|-------|--------|------|---------|--------|---------------|--------|-------|")

        for style, sdata in sym_styles.items():
            s = sdata.get("stats", {})
            wins     = s.get("wins", 0)
            losses   = s.get("losses", 0)
            total    = s.get("total_trades", 0)
            wr       = s.get("win_rate", 0)
            profit   = s.get("total_profit", 0)
            ret      = s.get("return_pct", 0)
            pf       = s.get("profit_factor", 0)
            dd       = s.get("max_drawdown", 0)
            avgr     = s.get("avg_r", 0)

            pf_str   = "∞" if pf >= 999 else f"{pf:.2f}"
            lines.append(f"| {style} | {total} ({wins}W/{losses}L) | {wr}% | {sign(profit)} | {pct(ret)} | {pf_str} | {dd:.1f}% | {avgr:.2f}R |")
            all_stats.append({"sym": sym, "style": style, "stats": s})

        lines.append("")

        # Detail per style
        for style, sdata in sym_styles.items():
            s = sdata.get("stats", {})
            trades = sdata.get("trades", [])

            lines.append(f"#### {style} — Detail")
            lines.append("")
            lines.append(f"- Total Trades: **{s.get('total_trades', 0)}**")
            lines.append(f"- Win Rate: **{s.get('win_rate', 0)}%** ({s.get('wins',0)} wins / {s.get('losses',0)} losses)")
            lines.append(f"- Net P&L: **{usd(s.get('total_profit',0))}** ({pct(s.get('return_pct',0))})")
            lines.append(f"- End Balance: **{usd(s.get('end_balance', balance))}**")
            lines.append(f"- Profit Factor: **{s.get('profit_factor',0):.2f}**")
            lines.append(f"- Max Drawdown: **{s.get('max_drawdown',0):.1f}%**")
            lines.append(f"- Avg R-Multiple: **{s.get('avg_r',0):.2f}R**")
            lines.append(f"- Best Trade: **+{usd(s.get('best_trade',0))}**")
            lines.append(f"- Worst Trade: **{usd(s.get('worst_trade',0))}**")
            lines.append(f"- Sharpe Ratio: **{s.get('sharpe',0):.2f}**")
            lines.append("")

            # Session breakdown
            if trades:
                sessions: dict[str, dict] = {}
                days: dict[str, dict]     = {}
                exits: dict[str, int]     = {}

                for t in trades:
                    # Sessions
                    sess = t.get("session") or "Unknown"
                    if sess not in sessions:
                        sessions[sess] = {"wins": 0, "total": 0, "profit": 0.0}
                    sessions[sess]["total"] += 1
                    p = t.get("profit") or 0
                    sessions[sess]["profit"] += p
                    if p > 0:
                        sessions[sess]["wins"] += 1

                    # Days
                    et = t.get("entry_time")
                    if et:
                        try:
                            day = datetime.fromisoformat(et).strftime("%a")
                        except Exception:
                            day = "?"
                        if day not in days:
                            days[day] = {"profit": 0.0, "total": 0}
                        days[day]["profit"] += p
                        days[day]["total"] += 1

                    # Exit reasons
                    ex = t.get("exit_reason") or "unknown"
                    exits[ex] = exits.get(ex, 0) + 1

                lines.append(f"**Session Breakdown ({style} / {sym}):**")
                lines.append("")
                lines.append("| Session | Trades | Win% | Net P&L |")
                lines.append("|---------|--------|------|---------|")
                for sess, sv in sorted(sessions.items()):
                    wr_s = round(sv["wins"] / sv["total"] * 100, 1) if sv["total"] else 0
                    lines.append(f"| {sess} | {sv['total']} | {wr_s}% | {sign(sv['profit'])} |")
                lines.append("")

                lines.append(f"**Exit Reason Breakdown:**")
                lines.append("")
                lines.append("| Exit | Count |")
                lines.append("|------|-------|")
                for ex, cnt in sorted(exits.items(), key=lambda x: -x[1]):
                    lines.append(f"| {ex} | {cnt} |")
                lines.append("")

                lines.append(f"**Day of Week Breakdown:**")
                lines.append("")
                lines.append("| Day | Trades | Net P&L |")
                lines.append("|-----|--------|---------|")
                day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                for day in day_order:
                    if day in days:
                        dv = days[day]
                        lines.append(f"| {day} | {dv['total']} | {sign(dv['profit'])} |")
                lines.append("")

                # Sample trades (first 5 + last 5)
                lines.append(f"**Sample Trades (first 5 + last 5):**")
                lines.append("")
                lines.append("| # | Entry | Action | Entry Price | Exit Price | P&L | R | Exit |")
                lines.append("|---|-------|--------|-------------|------------|-----|---|------|")
                sample = (trades[:5] + trades[-5:]) if len(trades) > 10 else trades
                for idx, t in enumerate(sample, 1):
                    ep   = t.get("entry_time","")[:16] if t.get("entry_time") else "—"
                    act  = t.get("action","—")
                    enp  = t.get("entry_price",0)
                    exp  = t.get("exit_price",0) or 0
                    p    = t.get("profit",0) or 0
                    r    = t.get("r_multiple",0) or 0
                    ex   = t.get("exit_reason","—")
                    lines.append(f"| {idx} | {ep} | {act} | {enp:.5f} | {exp:.5f} | {sign(p)} | {r:.2f}R | {ex} |")
                lines.append("")

    lines.append("---")
    lines.append("")

    # ── OVERALL ANALYSIS ─────────────────────────────────────────────────────
    lines.append("## 🔍 Analisis Keseluruhan")
    lines.append("")

    # Best/worst style
    if all_stats:
        best  = max(all_stats, key=lambda x: x["stats"].get("total_profit", -9e9))
        worst = min(all_stats, key=lambda x: x["stats"].get("total_profit", 9e9))
        highest_wr = max(all_stats, key=lambda x: x["stats"].get("win_rate", 0))

        lines.append(f"- 🏆 **Gaya terbaik:** {best['style']} on {best['sym']} (P&L: {sign(best['stats'].get('total_profit',0))})")
        lines.append(f"- ❌ **Gaya terburuk:** {worst['style']} on {worst['sym']} (P&L: {sign(worst['stats'].get('total_profit',0))})")
        lines.append(f"- 🎯 **Win rate tertinggi:** {highest_wr['style']} on {highest_wr['sym']} ({highest_wr['stats'].get('win_rate',0)}%)")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── PROMPT FOR AI ────────────────────────────────────────────────────────
    lines.append("## 💬 Soalan Untuk AI")
    lines.append("")
    lines.append("Salin bahagian di bawah dan hantar kepada AI bersama-sama dengan data di atas:")
    lines.append("")
    lines.append("```")
    lines.append("Saya ada bot trading MT5 bernama Investment-AI_T yang menggunakan AI (Gemini)")
    lines.append("untuk generate signal trading XAUUSD dan EURUSD.")
    lines.append("")
    lines.append("Di atas adalah hasil backtesting selama 1 tahun untuk 3 gaya trading:")
    lines.append("SCALPING (EMA cross), INTRADAY (EMA stack), dan SWING (Golden Cross).")
    lines.append("")
    lines.append("Berdasarkan data backtest ini, tolong:")
    lines.append("")
    lines.append("1. ANALISIS - Kenapa sesetengah gaya perform lebih baik dari yang lain?")
    lines.append("2. PARAMETER - Cadangkan parameter SL/TP/ATR yang lebih optimal")
    lines.append("3. SIGNAL - Adakah EMA crossover cukup atau perlu tambah indicator lain?")
    lines.append("4. SESSION - Bilakah waktu terbaik untuk trade berdasarkan data?")
    lines.append("5. PERBAIKAN - 3 perubahan konkrit yang boleh improve win rate & profit factor")
    lines.append("6. RISIKO - Drawdown maksimum terlalu tinggi? Camne nak kurangkan?")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📁 Fail-Fail Penting Bot")
    lines.append("")
    lines.append("| Fail | Fungsi |")
    lines.append("|------|--------|")
    lines.append("| `Bot Engine/style_params.py` | Parameter SL/TP/risk per style — **UBAH DI SINI** |")
    lines.append("| `Bot Engine/ai_engine.py` | Prompt untuk Gemini AI |")
    lines.append("| `Bot Engine/strategy.py` | Kira indicators (EMA, ATR, ADX, RSI) |")
    lines.append("| `Bot Engine/risk_manager.py` | Validate signal, kira lot size |")
    lines.append("| `Bot Engine/main.py` | Main loop bot |")
    lines.append("| `TESTING DATA SETAHUN/backtest_engine.py` | Backtest engine (standalone) |")
    lines.append("")
    lines.append("---")
    lines.append(f"*Report ini dijana secara automatik oleh Investment-AI_T Backtest System pada {now}*")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Find JSON source
    if len(sys.argv) > 1:
        json_path = Path(sys.argv[1])
    else:
        json_path = find_latest_json()

    if json_path is None or not json_path.exists():
        print("[ERROR] Tiada backtest JSON ditemui dalam reports/")
        print("Jalankan backtest dahulu dengan run_backtest.bat")
        sys.exit(1)

    print(f"[INFO] Loading: {json_path.name}")
    data = load_results(json_path)

    # Build report
    md = build_report(data)

    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS_DIR / f"AI_REPORT_{ts}.md"
    out_path.write_text(md, encoding="utf-8")

    print(f"\n✅ AI Report dijana: {out_path}")
    print(f"   Saiz: {len(md):,} chars")
    print(f"\n📋 Cara guna:")
    print(f"   1. Buka fail: {out_path.name}")
    print(f"   2. Salin SEMUA kandungan")
    print(f"   3. Paste ke ChatGPT / Claude / Gemini")
    print(f"   4. Tanya soalan yang ada di bahagian bawah fail")


if __name__ == "__main__":
    main()
