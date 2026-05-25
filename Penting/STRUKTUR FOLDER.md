# Struktur Folder Investment-AI_T

Root folder sengaja dibiarkan ringkas.

```text
Investment-AI_T-master/
  start_bot.bat
  Bot Engine/
  Setup/
  Penting/
  TESTING DATA SETAHUN/
```

## start_bot.bat

Fail utama yang user tekan.

Ia cuma panggil launcher sebenar:

```text
Bot Engine/start_bot.bat
```

## Bot Engine

Tempat code yang menjalankan bot live:

```text
main.py
dashboard.py
config.py
ai_engine.py
mt5_connector.py
risk_manager.py
strategy.py
eurusd_pattern_engine.py
xauusd_pattern_engine.py
logger.py
trade_memory.py
start_bot.bat
```

## Setup

Tempat file setup dan konfigurasi template:

```text
setup_env.bat
setup_env.ps1
enable_dual_ai.bat
enable_dual_ai.ps1
requirements.txt
.env.example
```

Setup akan tulis `.env` ke dalam `Bot Engine/`.

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
