"""
dashboard.py - Real-Time Trading Bot Dashboard (Streamlit)

Run with:
    streamlit run dashboard.py

Features:
- Live session stats (win rate, P&L, trades)
- Trade history table from CSV
- Indicator chart
- Bot status
- Performance metrics
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

import config
from logger import generate_performance_report

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title  = "AI Trading Bot Dashboard",
    page_icon   = "📈",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🤖 AI Trading Bot")
    st.markdown("---")
    refresh_rate = st.slider("Refresh interval (s)", 2, 30, config.DASHBOARD_REFRESH)
    symbol_filter = st.multiselect(
        "Filter by symbol",
        options=config.SYMBOLS,
        default=config.SYMBOLS,
    )
    status_filter = st.multiselect(
        "Filter by status",
        options=["FILLED", "SKIPPED", "REJECTED"],
        default=["FILLED"],
    )
    st.markdown("---")
    st.caption(f"Bot config: {config.PRIMARY_SYMBOL}")
    st.caption(f"Model: {config.OLLAMA_MODEL}")
    st.caption(f"Risk: {config.MAX_RISK_PERCENT}%/trade")

# ─────────────────────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=refresh_rate)
def load_trades() -> pd.DataFrame:
    """Load trade CSV with caching."""
    if not os.path.exists(config.TRADE_LOG_FILE):
        return pd.DataFrame()
    try:
        df = pd.read_csv(config.TRADE_LOG_FILE, parse_dates=["timestamp"])
        return df
    except Exception:
        return pd.DataFrame()


def load_performance() -> dict:
    return generate_performance_report()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

st.title("📈 AI Trading Bot — Live Dashboard")
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

df_all    = load_trades()
perf      = load_performance()

# ── KPI METRICS ROW ──────────────────────────────────────────────────────────
col1, col2, col3, col4, col5, col6 = st.columns(6)

filled_trades = 0
if not df_all.empty:
    filled_df = df_all[df_all["status"] == "FILLED"]
    filled_trades = len(filled_df)

col1.metric("Total Cycles",   perf.get("total_cycles", 0))
col2.metric("Filled Trades",  perf.get("filled_trades", 0))
col3.metric("Win Rate",       f"{perf.get('win_rate_pct', 0)}%")
col4.metric(
    "Total P&L",
    f"{perf.get('total_profit', 0):+.2f}",
    delta=f"{perf.get('total_profit', 0):+.2f}",
)
col5.metric("Profit Factor",  perf.get("profit_factor", "N/A"))
col6.metric("Avg Confidence", f"{perf.get('avg_confidence', 0):.2f}")

st.markdown("---")

# ── CHARTS ROW ───────────────────────────────────────────────────────────────
if not df_all.empty and "profit" in df_all.columns:
    left_col, right_col = st.columns(2)

    with left_col:
        st.subheader("Cumulative P&L")
        filled_only = df_all[df_all["status"] == "FILLED"].copy()
        if not filled_only.empty:
            filled_only["profit"] = pd.to_numeric(filled_only["profit"], errors="coerce").fillna(0)
            filled_only = filled_only.sort_values("timestamp")
            filled_only["cumulative_pnl"] = filled_only["profit"].cumsum()
            st.line_chart(
                filled_only.set_index("timestamp")[["cumulative_pnl"]],
                use_container_width=True,
            )
        else:
            st.info("No filled trades yet")

    with right_col:
        st.subheader("Win / Loss Distribution")
        if not df_all.empty:
            status_counts = df_all["status"].value_counts()
            st.bar_chart(status_counts, use_container_width=True)

    # RSI & Confidence over time
    st.subheader("AI Confidence & RSI Over Time")
    chart_df = df_all[df_all["status"] != "SKIPPED"].copy()
    if not chart_df.empty:
        chart_df = chart_df.sort_values("timestamp")
        chart_df["ai_confidence"] = pd.to_numeric(chart_df["ai_confidence"], errors="coerce")
        chart_df["rsi"]           = pd.to_numeric(chart_df["rsi"],           errors="coerce")
        chart_data = chart_df.set_index("timestamp")[["ai_confidence", "rsi"]].dropna()
        if not chart_data.empty:
            st.line_chart(chart_data, use_container_width=True)

st.markdown("---")

# ── TRADE TABLE ───────────────────────────────────────────────────────────────
st.subheader("Trade History")

if df_all.empty:
    st.info(f"No trade data found in `{config.TRADE_LOG_FILE}`")
else:
    display_df = df_all.copy()

    # Apply filters
    if symbol_filter:
        display_df = display_df[display_df["symbol"].isin(symbol_filter)]
    if status_filter:
        display_df = display_df[display_df["status"].isin(status_filter)]

    # Select columns to display
    show_cols = [
        "timestamp", "symbol", "action", "status",
        "lot", "entry_price", "sl", "tp",
        "ai_confidence", "ai_reason",
        "profit", "rsi", "trend", "ticket",
    ]
    show_cols = [c for c in show_cols if c in display_df.columns]

    # Color rows
    def color_row(row):
        if row.get("status") == "FILLED" and row.get("profit", 0) > 0:
            return ["background-color: #0d2b0d"] * len(row)
        elif row.get("status") == "FILLED" and row.get("profit", 0) < 0:
            return ["background-color: #2b0d0d"] * len(row)
        return [""] * len(row)

    styled = (
        display_df[show_cols]
        .tail(100)
        .sort_values("timestamp", ascending=False)
        .style
        .apply(color_row, axis=1)
        .format({
            "profit":         "{:+.2f}",
            "ai_confidence":  "{:.2f}",
            "entry_price":    "{:.5f}",
            "sl":             "{:.5f}",
            "tp":             "{:.5f}",
        }, na_rep="—")
    )

    st.dataframe(styled, use_container_width=True, height=400)
    st.caption(f"Showing last 100 records from {config.TRADE_LOG_FILE}")

st.markdown("---")

# ── PERFORMANCE BREAKDOWN ─────────────────────────────────────────────────────
st.subheader("Performance Breakdown")
if "error" not in perf:
    p_col1, p_col2, p_col3 = st.columns(3)
    with p_col1:
        st.metric("Best Trade",  f"{perf.get('best_trade', 0):+.2f}")
        st.metric("Avg Win",     f"{perf.get('avg_win', 0):+.2f}")
    with p_col2:
        st.metric("Worst Trade", f"{perf.get('worst_trade', 0):+.2f}")
        st.metric("Avg Loss",    f"{perf.get('avg_loss', 0):+.2f}")
    with p_col3:
        st.metric("Total Wins",   perf.get("wins", 0))
        st.metric("Total Losses", perf.get("losses", 0))

    st.caption(f"Symbols traded: {', '.join(perf.get('symbols_traded', []))}")
else:
    st.warning(perf["error"])

# ── AUTO REFRESH ──────────────────────────────────────────────────────────────
time.sleep(0.1)
st.rerun() if hasattr(st, "rerun") else st.experimental_rerun()
