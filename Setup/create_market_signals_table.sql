-- ============================================================
-- market_signals table
-- Stores the latest AI signal per symbol, broadcast by Master Analyzer.
-- Account Terminals read from this table to decide whether to trade.
-- One row per symbol (upserted on conflict = symbol).
-- ============================================================

CREATE TABLE IF NOT EXISTS public.market_signals (
    symbol          TEXT PRIMARY KEY,
    action          TEXT,               -- BUY / SELL / HOLD
    confidence      DOUBLE PRECISION,   -- 0.0 – 1.0
    trade_style     TEXT,               -- SCALPING / INTRADAY / SWING
    reason          TEXT,
    market_regime   TEXT,               -- TRENDING / RANGING / VOLATILE
    indicators_snapshot JSONB,          -- h4_trend, rsi, adx, patterns, etc.
    vision_bias     TEXT,               -- bullish / bearish / sideways / null
    bid             DOUBLE PRECISION,
    ask             DOUBLE PRECISION,
    atr             DOUBLE PRECISION,
    signal_id       TEXT,               -- short UUID to track freshness
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Allow anon / service role to read (Dashboard reads via anon key)
ALTER TABLE public.market_signals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anon read market_signals"
    ON public.market_signals
    FOR SELECT
    USING (true);

CREATE POLICY "Allow service_role full access to market_signals"
    ON public.market_signals
    FOR ALL
    USING (auth.role() = 'service_role');

-- Grant
GRANT SELECT ON public.market_signals TO anon;
GRANT ALL    ON public.market_signals TO service_role;
