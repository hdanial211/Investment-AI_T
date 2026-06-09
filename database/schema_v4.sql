-- schema_v4.sql
-- V4 Architecture Database Schema for Investment-AI_T

-- 1. Table: active_trades
-- Menyimpan status live (OPEN). Dibaca oleh MQL5 EA untuk melukis garisan dan execute Layer/Grid/Trailing.
CREATE TABLE active_trades (
  id bigint generated always as identity primary key,
  ticket bigint not null unique,
  account_id text not null,
  symbol text not null,
  direction text not null,  -- BUY / SELL
  lot double precision not null,
  trade_style text,         -- SCALPING / INTRADAY / SWING
  virtual_sl double precision,
  virtual_tp double precision,
  be_trigger_pips double precision,  -- Pencetus Breakeven (Trigger)
  be_offset_pips double precision,   -- Breakeven Offset
  trail_start_pips double precision, -- Jarak Trailing
  trail_dist_pips double precision,
  entry_price double precision,
  average_entry_price double precision,
  layer_index int default 1,
  basket_id text,
  magic_number bigint,
  current_profit double precision,
  closing_requested boolean default false,
  close_requested_by text,
  close_requested_at timestamptz,
  updated_at timestamptz default now(),
  opened_at timestamptz default now(),
  current_status text default 'OPEN',
  signal_id text, -- ID Isyarat Asal
  CONSTRAINT unique_account_signal UNIQUE (account_id, signal_id) -- Halang Duplicate Entry
);

-- 2. Table: closed_trades
-- Struktur arkib sejarah untuk membolehkan Web App menjana carta prestasi harian
CREATE TABLE closed_trades (
  id bigint generated always as identity primary key,
  ticket bigint not null unique,
  account_id text not null,
  symbol text not null,
  direction text not null,
  lot double precision,
  trade_style text,
  pnl double precision,
  close_reason text,  -- Hit TP, Hit SL, AI Close
  closed_at timestamptz default now()
);

-- 3. Table: account_settings
-- Menyimpan API Keys, Drawdown limit, % target harian, status bot (Enabled/Disabled)
CREATE TABLE IF NOT EXISTS account_settings (
    id bigint generated always as identity primary key,
    account_id text not null unique,
    enabled boolean default true,
    max_risk_percent double precision default 2.0,
    max_trades_per_pair int default 10,
    last_seen_bot timestamptz default now() -- Heartbeat
);

-- 4. Table: system_settings
-- Menyimpan senarai pair dan konfigurasi global
CREATE TABLE IF NOT EXISTS system_settings (
    id bigint generated always as identity primary key,
    key_name text not null unique,
    key_value jsonb not null
);

-- 5. Table: signals
-- Peti surat peribadi bagi setiap akaun
CREATE TABLE IF NOT EXISTS signals (
    id bigint generated always as identity primary key,
    signal_id text not null unique,
    account_id text not null,
    symbol text not null,
    direction text not null,
    trade_style text not null,
    confidence double precision,
    is_active boolean default true,
    created_at timestamptz default now()
);

-- 6. Table: market_signals
-- Arkib signal mentah dari AI
CREATE TABLE IF NOT EXISTS market_signals (
    id bigint generated always as identity primary key,
    symbol text not null,
    direction text not null,
    trade_style text not null,
    raw_ai_response jsonb,
    created_at timestamptz default now()
);
