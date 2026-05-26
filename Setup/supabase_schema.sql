-- Investment-AI_T Supabase schema
-- Run this once in Supabase SQL Editor before enabling SUPABASE_SYNC_ENABLED=True.
-- Backend bot writes with SUPABASE_SERVICE_ROLE_KEY.
-- Vercel/read-only dashboard should use SUPABASE_ANON_KEY only.

create table if not exists public.bot_heartbeat (
  machine_id text primary key,
  status text not null default 'online',
  last_seen_at timestamptz,
  current_cycle bigint default 0,
  message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.active_trades (
  ticket bigint primary key,
  symbol text,
  direction text,
  lot numeric,
  entry_price numeric,
  floating_profit numeric,
  virtual_sl numeric,
  virtual_tp numeric,
  virtual_trailing_stop numeric,
  profit_lock_level numeric,
  last_price numeric,
  max_drawdown numeric,
  primary_pattern text,
  pattern_names jsonb,
  pattern_categories jsonb,
  pattern_timeframes jsonb,
  confluence_combo text,
  pattern_confidence numeric,
  pattern_count integer,
  current_status text,
  original_thesis text,
  exit_reason text,
  trade_style text,
  vision_bias text,
  opened_at timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists public.trade_pattern_usage (
  id text primary key,
  ticket bigint,
  symbol text,
  direction text,
  trade_opened_at timestamptz,
  pattern_name text,
  category text,
  timeframe text,
  direction_bias text,
  confidence numeric,
  priority text,
  is_primary boolean default false,
  trade_status text,
  exit_reason text,
  profit numeric,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.pattern_usage_stats (
  id text primary key,
  symbol text,
  timeframe text,
  pattern_name text,
  category text,
  detected_count integer default 0,
  used_count integer default 0,
  open_trade_count integer default 0,
  closed_trade_count integer default 0,
  win_count integer default 0,
  loss_count integer default 0,
  win_rate numeric default 0,
  net_profit numeric default 0,
  avg_profit numeric default 0,
  avg_confidence numeric default 0,
  last_exit_reason text,
  updated_at timestamptz not null default now()
);

create table if not exists public.trade_events (
  id bigint generated always as identity primary key,
  ticket bigint,
  event_type text,
  reason text,
  created_at timestamptz not null default now()
);

alter table public.bot_heartbeat enable row level security;
alter table public.active_trades enable row level security;
alter table public.trade_pattern_usage enable row level security;
alter table public.pattern_usage_stats enable row level security;
alter table public.trade_events enable row level security;

-- Anon (Vercel/browser dashboard) can only READ
drop policy if exists "dashboard read bot heartbeat" on public.bot_heartbeat;
drop policy if exists "dashboard read active trades" on public.active_trades;
drop policy if exists "dashboard read trade pattern usage" on public.trade_pattern_usage;
drop policy if exists "dashboard read pattern usage stats" on public.pattern_usage_stats;
drop policy if exists "dashboard read trade events" on public.trade_events;

create policy "dashboard read bot heartbeat"
  on public.bot_heartbeat for select
  to anon
  using (true);

create policy "dashboard read active trades"
  on public.active_trades for select
  to anon
  using (true);

create policy "dashboard read trade pattern usage"
  on public.trade_pattern_usage for select
  to anon
  using (true);

create policy "dashboard read pattern usage stats"
  on public.pattern_usage_stats for select
  to anon
  using (true);

create policy "dashboard read trade events"
  on public.trade_events for select
  to anon
  using (true);

-- Service role (backend bot) can write all tables
-- Note: service_role bypasses RLS by default in Supabase,
-- but explicit policies ensure correct behavior if RLS is enforced.
drop policy if exists "bot writes heartbeat" on public.bot_heartbeat;
drop policy if exists "bot writes active trades" on public.active_trades;
drop policy if exists "bot writes trade pattern usage" on public.trade_pattern_usage;
drop policy if exists "bot writes pattern usage stats" on public.pattern_usage_stats;
drop policy if exists "bot writes trade events" on public.trade_events;

create policy "bot writes heartbeat"
  on public.bot_heartbeat for all
  to service_role
  using (true)
  with check (true);

create policy "bot writes active trades"
  on public.active_trades for all
  to service_role
  using (true)
  with check (true);

create policy "bot writes trade pattern usage"
  on public.trade_pattern_usage for all
  to service_role
  using (true)
  with check (true);

create policy "bot writes pattern usage stats"
  on public.pattern_usage_stats for all
  to service_role
  using (true)
  with check (true);

create policy "bot writes trade events"
  on public.trade_events for all
  to service_role
  using (true)
  with check (true);

-- Migration helper: add new columns if table already exists
do $$
begin
  if not exists (select 1 from information_schema.columns where table_name='active_trades' and column_name='trade_style') then
    alter table public.active_trades add column trade_style text;
  end if;
  if not exists (select 1 from information_schema.columns where table_name='active_trades' and column_name='vision_bias') then
    alter table public.active_trades add column vision_bias text;
  end if;
end $$;

