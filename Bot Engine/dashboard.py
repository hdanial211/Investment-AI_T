"""
dashboard.py - Terminal User Interface (TUI) Dashboard
Run with: python dashboard.py

Features:
- Live session stats (win rate, P&L, trades)
- Active Trade Memory monitoring
- Trade history table
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer, Static, DataTable, Label

import config
from logger import load_trades, generate_performance_report

class ActiveMemoryTable(DataTable):
    def on_mount(self):
        self.cursor_type = "row"
        self.add_columns(
            "Ticket",
            "Symbol",
            "Action",
            "Pattern",
            "Virtual SL",
            "Virtual TP",
            "Trail",
            "P/L",
            "Status",
        )
        
    def refresh_data(self):
        self.clear()
        memory_file = os.path.join(config.LOG_DIR, "trade_memory.json")
        if os.path.exists(memory_file):
            try:
                with open(memory_file, "r") as f:
                    data = json.load(f)
                active = data.get("active_trades", {})
                for tkt, info in active.items():
                    action = info.get("action") or info.get("direction") or ""
                    action_color = "green" if action == "BUY" else "red"
                    snapshot = info.get("pattern_snapshot") or {}
                    profit = float(info.get("floating_profit") or 0)
                    profit_color = "green" if profit >= 0 else "red"
                    self.add_row(
                        tkt, 
                        str(info.get("symbol", "")),
                        f"[{action_color} bold]{action}[/]",
                        str(snapshot.get("primary_pattern", "No pattern"))[:34],
                        _fmt_price(info.get("virtual_sl")),
                        _fmt_price(info.get("virtual_tp")),
                        _fmt_price(info.get("virtual_trailing_stop")),
                        f"[{profit_color}]{profit:+.2f}[/{profit_color}]",
                        str(info.get("current_status", "")),
                    )
            except Exception:
                pass


class PatternUsageTable(DataTable):
    def on_mount(self):
        self.cursor_type = "row"
        self.add_columns("Pattern", "Symbol", "TF", "Used", "Open", "W/L", "Win %", "Net P/L")

    def refresh_data(self):
        self.clear()
        memory_file = os.path.join(config.LOG_DIR, "trade_memory.json")
        if not os.path.exists(memory_file):
            return
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            stats = list((data.get("pattern_usage_stats") or {}).values())
            stats.sort(key=lambda x: float(x.get("net_profit", 0) or 0), reverse=True)
            for item in stats[:20]:
                net = float(item.get("net_profit", 0) or 0)
                net_color = "green" if net >= 0 else "red"
                wins = int(item.get("win_count", 0) or 0)
                losses = int(item.get("loss_count", 0) or 0)
                self.add_row(
                    str(item.get("pattern_name", ""))[:36],
                    str(item.get("symbol", "")),
                    str(item.get("timeframe", "")),
                    str(item.get("used_count", 0)),
                    str(item.get("open_trade_count", 0)),
                    f"{wins}/{losses}",
                    f"{float(item.get('win_rate', 0) or 0):.1f}%",
                    f"[{net_color}]{net:+.2f}[/{net_color}]",
                )
        except Exception:
            pass

class CoolingOffTable(DataTable):
    def on_mount(self):
        self.cursor_type = "row"
        self.add_columns("Symbol", "Remaining Time", "Status")
        
    def refresh_data(self):
        self.clear()
        memory_file = os.path.join(config.LOG_DIR, "trade_memory.json")
        if os.path.exists(memory_file):
            try:
                with open(memory_file, "r") as f:
                    data = json.load(f)
                cooling = data.get("cooling_off", {})
                for sym, info in cooling.items():
                    if isinstance(info, dict):
                        ts = info.get("timestamp")
                        dur = info.get("duration", 15)
                    else:
                        ts = info
                        dur = 15
                        
                    from datetime import timedelta
                    time_passed = datetime.now() - datetime.fromisoformat(ts)
                    remaining = timedelta(minutes=dur) - time_passed
                    
                    if remaining.total_seconds() > 0:
                        mins = int(remaining.total_seconds() // 60)
                        secs = int(remaining.total_seconds() % 60)
                        self.add_row(sym, f"{mins}m {secs}s", "[yellow]COOLING OFF[/yellow]")
                    else:
                        self.add_row(sym, "0m 0s", "[green]READY[/green]")
            except Exception:
                pass

class TradeHistoryTable(DataTable):
    def on_mount(self):
        self.cursor_type = "row"
        self.add_columns("Time", "Symbol", "Action", "Profit", "Reason")
        
    def refresh_data(self, df):
        self.clear()
        if not df.empty:
            recent = df.tail(30).sort_values("timestamp", ascending=False)
            for _, row in recent.iterrows():
                profit_str = ""
                profit_val = row.get("profit", 0)
                if pd.notnull(profit_val) and profit_val != 0:
                    color = "green" if float(profit_val) > 0 else "red"
                    profit_str = f"[{color}]{float(profit_val):+.2f}[/{color}]"
                
                action_color = "green" if row["action"] == "BUY" else "red" if row["action"] == "SELL" else "white"
                
                self.add_row(
                    str(row["timestamp"])[:19],
                    str(row["symbol"]),
                    f"[{action_color}]{str(row['action'])}[/{action_color}]",
                    profit_str,
                    str(row.get("ai_reason", ""))[:60] + "..." if len(str(row.get("ai_reason", ""))) > 60 else str(row.get("ai_reason", ""))
                )

class TradingDashboard(App):
    CSS = """
    Screen {
        background: $surface;
    }
    #kpi-container {
        height: 3;
        dock: top;
        content-align: center middle;
        background: $panel;
        margin: 1;
        border: solid green;
    }
    #tables-container {
        height: 100%;
        layout: vertical;
        margin: 1;
    }
    DataTable {
        height: 1fr;
        border: solid cyan;
    }
    """
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="kpi-container")
        with Vertical(id="tables-container"):
            yield Label("🧠 [bold cyan]Active Trade Memory[/bold cyan]")
            yield ActiveMemoryTable()

            yield Label("🧬 [bold green]Pattern Usage Stats[/bold green]")
            yield PatternUsageTable()
            
            yield Label("🧊 [bold yellow]Cooling-Off Periods[/bold yellow]")
            yield CoolingOffTable()
            
            yield Label("📊 [bold magenta]Trade History[/bold magenta]")
            yield TradeHistoryTable()
            
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Investment AI - Advanced Terminal Dashboard"
        self.update_dashboard()
        self.set_interval(2.0, self.update_dashboard)

    def update_dashboard(self) -> None:
        try:
            perf = generate_performance_report()
            df = load_trades()
            
            kpi = self.query_one("#kpi-container", Static)
            kpi.update(f"[bold green]Total P&L:[/bold green] {perf.get('total_profit', 0):+.2f} | "
                       f"[bold]Win Rate:[/bold] {perf.get('win_rate_pct', 0)}% | "
                       f"[bold]Filled Trades:[/bold] {perf.get('filled_trades', 0)} | "
                       f"[bold]Profit Factor:[/bold] {perf.get('profit_factor', 'N/A')}")
                       
            self.query_one(ActiveMemoryTable).refresh_data()
            self.query_one(PatternUsageTable).refresh_data()
            self.query_one(CoolingOffTable).refresh_data()
            self.query_one(TradeHistoryTable).refresh_data(df)
        except Exception as e:
            pass


def _fmt_price(value) -> str:
    try:
        if value is None or value == "":
            return "-"
        return f"{float(value):.5f}"
    except (TypeError, ValueError):
        return "-"


if __name__ == "__main__":
    app = TradingDashboard()
    app.run()
