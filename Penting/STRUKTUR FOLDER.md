# Struktur Folder Investment-AI_T

Root folder sengaja dibiarkan ringkas.

```text
Investment-AI_T-master/
  start_bot.bat
  Bot Engine/
  Dashboard/
  Setup/
  Penting/
  TESTING DATA SETAHUN/
```

## start_bot.bat

Fail utama yang user tekan. Ia memanggil multi-account launcher:

```text
ecosystem_manager.py
```

## Bot Engine

Tempat script yang menjalankan logika trading dan ecosystem:

```text
master_analyzer.py
executor_bot.py
entry_terminal.py
account_settings.py
style_params.py
mt5_connector.py
risk_manager.py
strategy.py
pattern_helpers.py
xauusd_pattern_engine.py
logger.py
trade_memory.py
trade_management/
ai_clients/
```

## Setup

Tempat file setup dan konfigurasi template:

```text
setup_env.bat
setup_env.ps1
enable_dual_ai.bat
enable_dual_ai.ps1
enable_supabase_sync.bat
enable_supabase_sync.ps1
run_smoke_tests.bat
run_smoke_tests.py
requirements.txt
.env.example
supabase_schema.sql
```

Setup akan tulis `.env` ke dalam `Bot Engine/`.

## Dashboard

Tempat dashboard static untuk deploy ke Vercel:

```text
index.html
```

Dashboard ini read-only. Ia baca Supabase guna anon key dan tunjuk heartbeat, active trades, virtual SL/TP, pattern usage, dan trade timeline.

## Penting

Tempat dokumen planning dan flow sistem:

```text
planning
system running.html
README.md
STRUKTUR FOLDER.md
```

## TESTING DATA SETAHUN

Tempat semua file backtest setahun:

```text
run_yearly_backtest.bat
run_yearly_backtest.py
tutorial testing setahun data.md
research/
reports/
storage/
```

`storage/` di-ignore daripada Git sebab data MT5/backtest boleh jadi besar.
