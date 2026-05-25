"""Collect and load historical OHLCV data for backtesting."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

from research.backtest_config import BacktestConfig


HistoryBundle = Dict[str, Dict[str, pd.DataFrame]]


def history_csv_path(cfg: BacktestConfig, symbol: str, timeframe: str) -> Path:
    return cfg.history_dir / f"{symbol.upper()}_{timeframe.upper()}_{cfg.date_token}.csv"


def history_parquet_path(cfg: BacktestConfig, symbol: str, timeframe: str) -> Path:
    return cfg.history_dir / f"{symbol.upper()}_{timeframe.upper()}_{cfg.date_token}.parquet"


def _normalize_rates(rates) -> pd.DataFrame:
    df = pd.DataFrame(rates)
    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    if "spread" not in df.columns:
        df["spread"] = 0

    columns = ["time", "open", "high", "low", "close", "volume", "spread"]
    return df[columns].sort_values("time").reset_index(drop=True)


def _write_history(df: pd.DataFrame, cfg: BacktestConfig, symbol: str, timeframe: str) -> None:
    csv_path = history_csv_path(cfg, symbol, timeframe)
    df.to_csv(csv_path, index=False)

    # Parquet is faster, but pyarrow/fastparquet may not be installed.
    try:
        df.to_parquet(history_parquet_path(cfg, symbol, timeframe), index=False)
    except Exception:
        pass


def collect_mt5_history(cfg: BacktestConfig) -> HistoryBundle:
    """
    Pull historical bars from the user's MT5 terminal.

    This refuses demo/synthetic data by default so the report never pretends
    fake data is a verified one-year result.
    """
    cfg.ensure_dirs()
    try:
        from mt5_connector import MT5Connector, MT5_AVAILABLE, TF_MAP, mt5
    except Exception as exc:
        raise RuntimeError(f"MT5 connector dependencies are unavailable: {exc}") from exc

    if not MT5_AVAILABLE or mt5 is None:
        raise RuntimeError("MetaTrader5 Python package is not available on this machine.")

    connector = MT5Connector()
    connected = connector.connect()
    if not connected or connector.demo_mode:
        if not cfg.allow_demo_data:
            raise RuntimeError("MT5 real history is unavailable. Backtest report remains Pending.")

    bundle: HistoryBundle = {}
    for symbol in cfg.symbols:
        bundle[symbol] = {}
        if mt5 is not None:
            mt5.symbol_select(symbol, True)

        for timeframe in cfg.timeframes:
            tf_value = TF_MAP.get(timeframe)
            if tf_value is None:
                raise RuntimeError(f"Unsupported timeframe for MT5 history: {timeframe}")

            rates = mt5.copy_rates_range(symbol, tf_value, cfg.start, cfg.end)
            if rates is None or len(rates) == 0:
                raise RuntimeError(f"No MT5 history returned for {symbol} {timeframe}.")

            df = _normalize_rates(rates)
            _write_history(df, cfg, symbol, timeframe)
            bundle[symbol][timeframe] = df

    connector.disconnect()
    return bundle


def load_history(cfg: BacktestConfig, symbols: Optional[Iterable[str]] = None) -> HistoryBundle:
    """Load previously collected history CSV files."""
    wanted_symbols = tuple(symbols or cfg.symbols)
    bundle: HistoryBundle = {}

    for symbol in wanted_symbols:
        symbol = symbol.upper()
        bundle[symbol] = {}
        for timeframe in cfg.timeframes:
            csv_path = history_csv_path(cfg, symbol, timeframe)
            if not csv_path.exists():
                continue
            df = pd.read_csv(csv_path)
            if "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"])
            bundle[symbol][timeframe] = df.sort_values("time").reset_index(drop=True)

    return bundle


def missing_history(cfg: BacktestConfig, bundle: HistoryBundle) -> list[str]:
    missing: list[str] = []
    for symbol in cfg.symbols:
        for timeframe in cfg.timeframes:
            df = bundle.get(symbol, {}).get(timeframe)
            if df is None or df.empty:
                missing.append(f"{symbol} {timeframe}")
    return missing
