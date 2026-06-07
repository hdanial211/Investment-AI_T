# AI Trading Bot - Cloud AI + MetaTrader 5

A production-ready algorithmic trading system that combines:
- **MetaTrader 5** for live market data and trade execution
- **OpenRouter / Hugging Face** cloud AI for main signal and fallback
- Optional second-model risk review after a valid signal
- Full **risk management**, **logging**, and terminal dashboard

---

## 📁 Project Structure

```
Investment-AI_T-master/
├── start_bot.bat        <- one-click launcher
├── ecosystem_manager.py <- live multi-account manager
├── Bot Engine/          <- trading scripts & master analyzer
├── Dashboard/           <- Supabase/Vercel read-only monitor
├── Setup/               <- env setup + requirements
├── Penting/             <- planning, docs, system flow
└── TESTING DATA SETAHUN/ <- historical backtest workflow
```

---

## ⚙️ System Requirements

| Requirement | Detail |
|---|---|
| OS | **Windows 10/11** (MetaTrader5 Python package is Windows-only) |
| Python | **3.10 or higher** |
| MetaTrader 5 | Terminal installed and logged in |
| Cloud AI | OpenRouter API key, optional Hugging Face token |
| RAM | 8GB+ recommended |

---

## 🚀 Step-by-Step Setup

### Step 1 — Install Python dependencies

Open a terminal in the repo root:

```bash
pip install -r "Setup/requirements.txt"
```

> **Note:** `MetaTrader5` package only works on Windows. On other OS it installs in demo mode.

---

### Step 2 — Prepare cloud AI keys

1. Create / use an OpenRouter API key.
2. Optional: create a Hugging Face token for fallback.
3. Do not commit real keys. Put them in local `Bot Engine/.env` only.

---

### Step 3 — Connect MetaTrader 5

1. Download and install MT5 from your broker
2. Log into your trading account in the MT5 terminal
3. Enable **AutoTrading** (green button in MT5 toolbar)
4. Go to `Tools → Options → Expert Advisors` and check:
   - ✅ Allow automated trading
   - ✅ Allow DLL imports

---

### Step 4 — Configure the bot

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp "Setup/.env.example" "Bot Engine/.env"
```

Edit `.env`:
```ini
MT5_LOGIN=12345678           # Your MT5 account number
MT5_PASSWORD=YourPassword    # Your MT5 password
MT5_SERVER=YourBroker-Live   # Your broker's server (shown in MT5 login screen)

SYMBOLS=XAUUSD               # Symbols to trade (100% Gold Only)
LOOP_INTERVAL=10             # Seconds between execution cycles
MAX_RISK_PERCENT=2.0         # Risk % per trade
MIN_CONFIDENCE=0.60          # Minimum AI confidence to trade

AI_PROVIDER=openrouter
AI_FALLBACK_PROVIDER=huggingface
OPENROUTER_API_KEY=local_only
HF_TOKEN=optional_local_only
AI_MAIN_MODEL=openai/gpt-oss-20b:free
AI_RISK_MODEL=openai/gpt-oss-120b:free
ENABLE_RISK_REVIEW=True       # Risk AI is used only after a valid trade signal
AI_TEMPERATURE=0.1
AI_MAX_TOKENS=256
```

AI calls are blocking and protected by a single in-process lock: the main AI must finish before the risk AI starts, and the risk AI must finish before the bot continues to order placement.

Or edit `config.py` directly if you prefer not using `.env`.

---

### Step 5 — Run the bot

Recommended on Windows:

```bat
start_bot.bat
```

On first run, the launcher will create a local `.env` by asking for your MT5 login, password, server, symbols, OpenRouter API key, optional Hugging Face token, and model choices. The `.env` file is ignored by Git so your trading credentials and API keys are not pushed to GitHub.

After setup, the launcher validates the cloud AI config, checks Python, starts the trading engine, then opens the terminal dashboard. No Ollama server, local model pull, or local warm-up is required.

You can also run the first-time setup manually:

```bat
Setup\setup_env.bat
```

To enable/update two-model cloud AI mode on an existing `.env`:

```bat
Setup\enable_dual_ai.bat
```

Manual run:

```bash
# Make sure you're in the repo root directory
# Run the multi-account trading bot
python ecosystem_manager.py
```

Expected startup output:
```
============================================================
  AI TRADING BOT — STARTUP CHECKS
============================================================
Checking MT5 connection...
✔ MT5 connected
Checking cloud AI (openrouter / openai/gpt-oss-20b:free)...
✔ Cloud AI main model ready
✔ Symbol XAUUSD: Bid=1952.45000
✔ Account: Balance=10000.00 USD | Leverage=1:100
============================================================
Trading symbols: ['XAUUSD']
Loop interval:   10s
Risk per trade:  2.0%
Min confidence:  0.6
Bot is LIVE. Press Ctrl+C to stop.
```

---

### Step 6 — Open the Dashboard (optional)

The launcher opens `dashboard.py` automatically in the foreground.

Remote read-only monitor production URL:

```text
https://investment-ai-t.vercel.app
```

Vercel is connected to GitHub, so it should follow the latest pushed version. Run `Setup/supabase_schema.sql` once in Supabase project `Investment_AI` (`https://kusyjtpcjyflxgfcqenb.supabase.co`). The browser dashboard uses only `SUPABASE_ANON_KEY`; never paste `SUPABASE_SERVICE_ROLE_KEY` into Vercel or frontend code.

To enable bot-side Supabase writes on the laptop:

```bat
Setup\enable_supabase_sync.bat
```

To run offline safety smoke tests before live MT5 testing:

```bat
Setup\run_smoke_tests.bat
```

---

## 📊 Trading Logic Flow

```
Master Analyzer:
┌─────────────────────────────────────────┐
│ 1. Get tick for XAUUSD                  │
│ 2. Check timers (10m, 30m, 1h)          │
│ 3. Pattern Engine analysis              │
│ 4. AI Prompt -> "BUY/SELL/HOLD"         │
│ 5. Save to latest_signals.json          │
└─────────────────────────────────────────┘

Executor Bot (per account):
┌─────────────────────────────────────────┐
│ 1. Read latest_signals.json             │
│ 2. Pre-trade risk & session checks      │
│ 3. Validate with Risk AI                │
│ 4. Execute order in MT5                 │
│ 5. Virtual SL/TP & Trailing Stop        │
└─────────────────────────────────────────┘
```

---

## 🛑 Risk Management Rules

| Rule | Value |
|---|---|
| Max risk per trade | 2% of balance |
| Max consecutive losses | 3 (then halt) |
| Min AI confidence | 0.60 |
| Virtual Stop Loss | 50 pips default / dynamic ATR when enabled |
| Virtual Take Profit | 100 pips default / dynamic ATR when enabled |
| Max lot size | 1.0 |
| Max layered trades per pair | 10 |

By default, broker-side SL/TP is disabled:

```ini
USE_BROKER_SL_TP=False
USE_VIRTUAL_SL_TP=True
USE_VIRTUAL_TRAILING_STOP=True
```

The bot stores hidden exit levels in `logs/trade_memory.json` and closes the MT5 ticket itself when a virtual trigger is hit. This means the laptop, MT5 terminal, and internet connection must stay online for virtual exits to execute.

When 3 consecutive losses occur, the bot **halts automatically** and logs:
```
🛑 TRADING HALTED: Max consecutive losses reached (3). Manual review required.
```

Restart the bot after reviewing your configuration.

---

## 📡 AI Prompt Format

The bot sends structured market context to the selected cloud AI model:

```
Symbol: XAUUSD
Current Price: 1952.45
EMA 9: 1951.20
EMA 21: 1948.80
EMA Cross: golden_cross
RSI (14): 58.3 [neutral]
MACD Line: 0.00234
MACD Signal: 0.00198
MACD Histogram: 0.00036 [bullish]
ATR: 1.24
Market Trend: bullish
Price Change: 0.12%
Bid: 1952.10 | Ask: 1952.45 | Spread: 0.35
```

Expected response (strict JSON):
```json
{"action": "BUY", "confidence": 0.74, "reason": "Bullish EMA cross with rising MACD"}
```

---

## 🔧 VSCode Setup

1. Open the repo root folder in VSCode
2. Install the **Python extension** (ms-python.python)
3. Select your Python interpreter: `Ctrl+Shift+P → Python: Select Interpreter`
4. Recommended extensions:
   - Python
   - Pylance
   - Rainbow CSV (for viewing trades.csv)

`.vscode/settings.json` (optional):
```json
{
  "python.defaultInterpreterPath": "./venv/Scripts/python.exe",
  "editor.formatOnSave": true,
  "python.formatting.provider": "black"
}
```

---

## 📝 Logs & Output

| File | Contents |
|---|---|
| `logs/bot.log` | Full application log with timestamps |
| `logs/trades.csv` | One row per trade cycle (all decisions) |

### CSV Columns
`timestamp, symbol, action, lot, entry_price, sl, tp, ai_confidence, ai_reason, ticket, status, profit, rsi, trend, ...`

---

## ⚠️ Important Warnings

- **Always test on a DEMO account first** before using real money
- This bot is for **educational purposes** — trading involves real financial risk
- AI signals are **not guaranteed** to be profitable
- Monitor the bot during initial runs
- The `MetaTrader5` package **only works on Windows**

---

## 🐛 Troubleshooting

| Issue | Fix |
|---|---|
| `MT5 initialize failed` | Make sure MT5 terminal is open and logged in |
| `OPENROUTER_API_KEY missing` | Add key to local `Bot Engine/.env` |
| `HF_TOKEN missing` | Add token or set `AI_FALLBACK_ENABLED=False` |
| `Cloud AI provider unreachable` | Check internet/API limits/model availability |
| `Invalid symbol` | Add symbol to MT5 Market Watch manually |
| `Order failed: retcode=10014` | Invalid lot size — check broker's min lot |
| `Order failed: retcode=10019` | Not enough margin/balance |
