-- Migration Script for V4 100% Cloud-Native Hybrid Architecture
-- Run this in Supabase SQL Editor

-------------------------------------------------------------------------------
-- 1. ACCOUNT SETTINGS (Updating existing table with new MQL5 params)
-------------------------------------------------------------------------------

DO $$
BEGIN
  -- GRID RECOVERY
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='grid_enabled') THEN ALTER TABLE public.account_settings ADD COLUMN grid_enabled boolean DEFAULT true; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='grid_distance_atr') THEN ALTER TABLE public.account_settings ADD COLUMN grid_distance_atr numeric DEFAULT 1.0; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='grid_lot_multiplier') THEN ALTER TABLE public.account_settings ADD COLUMN grid_lot_multiplier numeric DEFAULT 1.5; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='max_grid_steps') THEN ALTER TABLE public.account_settings ADD COLUMN max_grid_steps integer DEFAULT 3; END IF;

  -- TRAILING STOP & BE
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='scalping_be_trigger') THEN ALTER TABLE public.account_settings ADD COLUMN scalping_be_trigger numeric DEFAULT 1.0; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='scalping_trail_start') THEN ALTER TABLE public.account_settings ADD COLUMN scalping_trail_start numeric DEFAULT 1.5; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='scalping_trail_dist') THEN ALTER TABLE public.account_settings ADD COLUMN scalping_trail_dist numeric DEFAULT 0.5; END IF;
  
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='intraday_be_trigger') THEN ALTER TABLE public.account_settings ADD COLUMN intraday_be_trigger numeric DEFAULT 1.5; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='intraday_trail_start') THEN ALTER TABLE public.account_settings ADD COLUMN intraday_trail_start numeric DEFAULT 2.0; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='intraday_trail_dist') THEN ALTER TABLE public.account_settings ADD COLUMN intraday_trail_dist numeric DEFAULT 1.0; END IF;
  
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='swing_be_trigger') THEN ALTER TABLE public.account_settings ADD COLUMN swing_be_trigger numeric DEFAULT 2.0; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='swing_trail_start') THEN ALTER TABLE public.account_settings ADD COLUMN swing_trail_start numeric DEFAULT 3.0; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='swing_trail_dist') THEN ALTER TABLE public.account_settings ADD COLUMN swing_trail_dist numeric DEFAULT 1.5; END IF;

  -- GLOBAL LIMITS
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='max_daily_drawdown_pct') THEN ALTER TABLE public.account_settings ADD COLUMN max_daily_drawdown_pct numeric DEFAULT 5.0; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='daily_profit_target_pct') THEN ALTER TABLE public.account_settings ADD COLUMN daily_profit_target_pct numeric DEFAULT 2.0; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='min_ai_confidence') THEN ALTER TABLE public.account_settings ADD COLUMN min_ai_confidence integer DEFAULT 70; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='max_spread_points') THEN ALTER TABLE public.account_settings ADD COLUMN max_spread_points integer DEFAULT 30; END IF;

  -- NEWS & SESSION FILTERS
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='block_news') THEN ALTER TABLE public.account_settings ADD COLUMN block_news boolean DEFAULT false; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='close_profit_on_news') THEN ALTER TABLE public.account_settings ADD COLUMN close_profit_on_news boolean DEFAULT false; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='block_asia_session') THEN ALTER TABLE public.account_settings ADD COLUMN block_asia_session boolean DEFAULT false; END IF;

  -- HEDGING
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='allow_hedging') THEN ALTER TABLE public.account_settings ADD COLUMN allow_hedging boolean DEFAULT true; END IF;

  -- MANUAL TRADE MANAGEMENT
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='bot_urus_sl_manual') THEN ALTER TABLE public.account_settings ADD COLUMN bot_urus_sl_manual boolean DEFAULT true; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='bot_urus_tp_manual') THEN ALTER TABLE public.account_settings ADD COLUMN bot_urus_tp_manual boolean DEFAULT true; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='account_settings' AND column_name='bot_urus_be_manual') THEN ALTER TABLE public.account_settings ADD COLUMN bot_urus_be_manual boolean DEFAULT true; END IF;
END $$;


-------------------------------------------------------------------------------
-- 2. SIGNALS TABLE
-------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.signals (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    signal_id text UNIQUE NOT NULL,
    account_id text NOT NULL,
    symbol text NOT NULL,
    action text NOT NULL, -- BUY, SELL
    sl float8 NOT NULL,
    tp float8 NOT NULL,
    entry_min float8,
    entry_max float8,
    confidence integer,
    style text,
    regime text,
    reason text,
    pattern text,
    generated_at timestamptz DEFAULT now(),
    is_active boolean DEFAULT true
);

ALTER TABLE public.signals ENABLE ROW LEVEL SECURITY;
-- MQL5 (anon) reads only its own signals
DROP POLICY IF EXISTS "EA read own signals" ON public.signals;
CREATE POLICY "EA read own signals" ON public.signals FOR SELECT TO anon USING (true);
-- Python (service_role) writes
DROP POLICY IF EXISTS "Python full access signals" ON public.signals;
CREATE POLICY "Python full access signals" ON public.signals FOR ALL TO service_role USING (true) WITH CHECK (true);


-------------------------------------------------------------------------------
-- 3. SL_TP_UPDATES TABLE
-------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.sl_tp_updates (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    signal_id text NOT NULL,
    account_id text NOT NULL,
    ticket bigint,
    new_sl float8,
    new_tp float8,
    updated_at timestamptz DEFAULT now(),
    applied boolean DEFAULT false
);

ALTER TABLE public.sl_tp_updates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "EA read own updates" ON public.sl_tp_updates;
CREATE POLICY "EA read own updates" ON public.sl_tp_updates FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS "EA update own updates" ON public.sl_tp_updates;
CREATE POLICY "EA update own updates" ON public.sl_tp_updates FOR UPDATE TO anon USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "Python full access updates" ON public.sl_tp_updates;
CREATE POLICY "Python full access updates" ON public.sl_tp_updates FOR ALL TO service_role USING (true) WITH CHECK (true);


-------------------------------------------------------------------------------
-- 4. CLOSED TRADES TABLE
-------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.closed_trades (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ticket bigint NOT NULL,
    account_id text NOT NULL,
    signal_id text,
    symbol text,
    direction text,
    lot numeric,
    style text,
    pattern text,
    open_price numeric,
    close_price numeric,
    pl numeric,
    reason text,
    opened_at timestamptz,
    closed_at timestamptz DEFAULT now()
);

ALTER TABLE public.closed_trades ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "EA write closed trades" ON public.closed_trades;
CREATE POLICY "EA write closed trades" ON public.closed_trades FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS "Python full access closed trades" ON public.closed_trades;
CREATE POLICY "Python full access closed trades" ON public.closed_trades FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "Dashboard read closed trades" ON public.closed_trades;
CREATE POLICY "Dashboard read closed trades" ON public.closed_trades FOR SELECT TO anon USING (true);


-------------------------------------------------------------------------------
-- 5. ACTIVE TRADES (Update existing table for MQL5 Virtual SL/TP access)
-------------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='active_trades' AND column_name='signal_id') THEN
    ALTER TABLE public.active_trades ADD COLUMN signal_id text;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='active_trades' AND column_name='grid_step') THEN
    ALTER TABLE public.active_trades ADD COLUMN grid_step integer DEFAULT 0;
  END IF;
END $$;

-- Fix MQL5 anon permissions to INSERT, UPDATE, DELETE active_trades
DROP POLICY IF EXISTS "EA insert active trades" ON public.active_trades;
CREATE POLICY "EA insert active trades" ON public.active_trades FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS "EA update active trades" ON public.active_trades;
CREATE POLICY "EA update active trades" ON public.active_trades FOR UPDATE TO anon USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "EA delete active trades" ON public.active_trades;
CREATE POLICY "EA delete active trades" ON public.active_trades FOR DELETE TO anon USING (true);


-------------------------------------------------------------------------------
-- 6. SYSTEM CONFIG (Ensure Python can read/write API Keys)
-------------------------------------------------------------------------------
-- The `system_settings` table already exists. We just ensure `bot_full_access` policy.
-- Python will read OpenRouter API keys from here.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='system_settings' AND column_name='master_mt5_login') THEN
    ALTER TABLE public.system_settings ADD COLUMN master_mt5_login text;
    ALTER TABLE public.system_settings ADD COLUMN master_mt5_password text;
    ALTER TABLE public.system_settings ADD COLUMN master_mt5_server text;
  END IF;
END $$;
