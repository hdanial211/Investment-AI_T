# 🤖 AI Trading Bot — Ollama + MetaTrader 5

A production-ready algorithmic trading system that combines:
- **MetaTrader 5** for live market data and trade execution
- **Ollama AI** (`qwen2.5:7b`) as the main decision engine
- Optional **DeepSeek-R1** (`deepseek-r1:8b`) risk-review model
- Full **risk management**, **logging**, and **Streamlit dashboard**

---

## 📁 Project Structure

```
trading_bot/
├── main.py              ← Entry point, trading loop
├── config.py            ← All settings (edit this first)
├── mt5_connector.py     ← MT5 connection & trade execution
├── ai_engine.py         ← Ollama API integration
├── strategy.py          ← RSI, EMA, MACD indicators
├── risk_manager.py      ← Position sizing, risk rules
├── logger.py            ← CSV trade journal, performance report
├── dashboard.py         ← Streamlit live dashboard
├── requirements.txt     ← Python dependencies
├── .env.example         ← Environment variable template
└── logs/
    ├── trades.csv       ← Trade journal (auto-created)
    └── bot.log          ← Application log (auto-created)
```

---

## ⚙️ System Requirements

| Requirement | Detail |
|---|---|
| OS | **Windows 10/11** (MetaTrader5 Python package is Windows-only) |
| Python | **3.10 or higher** |
| MetaTrader 5 | Terminal installed and logged in |
| Ollama | Running locally on port 11434 |
| RAM | 8GB+ recommended (AI model uses ~10GB) |

---

## 🚀 Step-by-Step Setup

### Step 1 — Install Python dependencies

Open a terminal in the `trading_bot/` folder:

```bash
pip install -r requirements.txt
```

> **Note:** `MetaTrader5` package only works on Windows. On other OS it installs in demo mode.

---

### Step 2 — Install and start Ollama

1. Download Ollama from [https://ollama.com](https://ollama.com)
2. Install and run:

```bash
# Start Ollama server (keep this terminal open)
ollama serve

# In another terminal, pull the main model
ollama pull qwen2.5:7b

# Optional: pull the second-opinion risk reviewer
ollama pull deepseek-r1:8b

# Verify model is available
ollama list
```

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
cp .env.example .env
```

Edit `.env`:
```ini
MT5_LOGIN=12345678          # Your MT5 account number
MT5_PASSWORD=YourPassword   # Your MT5 password
MT5_SERVER=YourBroker-Live  # Your broker's server (shown in MT5 login screen)

SYMBOLS=XAUUSD,EURUSD       # Symbols to trade
LOOP_INTERVAL=10             # Seconds between cycles
MAX_RISK_PERCENT=2.0         # Risk % per trade
MIN_CONFIDENCE=0.60          # Minimum AI confidence to trade

OLLAMA_MODEL=qwen2.5:7b
OLLAMA_RISK_MODEL=deepseek-r1:8b
ENABLE_RISK_REVIEW=False     # Set True after pulling deepseek-r1:8b
OLLAMA_NUM_CTX=4096
OLLAMA_TEMPERATURE=0.1
```

Or edit `config.py` directly if you prefer not using `.env`.

---

### Step 5 — Run the bot

Recommended on Windows:

```bat
start_bot.bat
```

On first run, the launcher will create a local `.env` by asking for your MT5 login, password, server, symbols, and Ollama model. The `.env` file is ignored by Git so your trading credentials are not pushed to GitHub.

After setup, the launcher will start Ollama, read `OLLAMA_MODEL` from `.env`, pull the model if needed, warm it up, start the trading engine, then open the terminal dashboard.

You can also run the first-time setup manually:

```bat
setup_env.bat
```

Manual run:

```bash
# Make sure you're in the trading_bot/ directory
cd trading_bot

# Run the trading bot
python main.py
```

Expected startup output:
```
============================================================
  AI TRADING BOT — STARTUP CHECKS
============================================================
Checking MT5 connection...
✔ MT5 connected
Checking Ollama (qwen2.5:7b)...
✔ Ollama AI ready
✔ Symbol XAUUSD: Bid=1952.45000
✔ Account: Balance=10000.00 USD | Leverage=1:100
============================================================
Trading symbols: ['XAUUSD', 'EURUSD']
Loop interval:   10s
Risk per trade:  2.0%
Min confidence:  0.6
Bot is LIVE. Press Ctrl+C to stop.
```

---

### Step 6 — Open the Dashboard (optional)

In a second terminal:

```bash
streamlit run dashboard.py
```

Opens at `http://localhost:8501` — shows live P&L, trade history, AI confidence chart.

---

## 📊 Trading Logic Flow

```
Every 10 seconds:
┌─────────────────────────────────────────┐
│ 1. Get tick (bid/ask) from MT5          │
│ 2. Fetch 100 OHLCV bars                 │
│ 3. Calculate RSI, EMA9, EMA21, MACD     │
│ 4. Pre-trade risk checks                │
│    ├─ Trading halted? → SKIP            │
│    ├─ Open position exists? → SKIP      │
│    └─ Low volatility? → SKIP            │
│ 5. Build prompt → Send to Ollama AI     │
│ 6. Parse JSON response                  │
│    ├─ action: BUY/SELL/HOLD             │
│    ├─ confidence: 0.0–1.0               │
│    └─ reason: explanation               │
│ 7. Validate signal                      │
│    ├─ HOLD → SKIP                       │
│    └─ confidence < 0.6 → SKIP          │
│ 8. Calculate lot size (2% risk rule)    │
│ 9. Calculate SL and TP prices           │
│10. Execute market order in MT5          │
│11. Log to trades.csv                    │
└─────────────────────────────────────────┘
```

---

## 🛑 Risk Management Rules

| Rule | Value |
|---|---|
| Max risk per trade | 2% of balance |
| Max consecutive losses | 3 (then halt) |
| Min AI confidence | 0.60 |
| Stop Loss | 50 pips |
| Take Profit | 100 pips |
| Max lot size | 1.0 |
| One position per symbol | Enforced |

When 3 consecutive losses occur, the bot **halts automatically** and logs:
```
🛑 TRADING HALTED: Max consecutive losses reached (3). Manual review required.
```

Restart the bot after reviewing your configuration.

---

## 📡 AI Prompt Format

The bot sends this to Ollama each cycle:

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

1. Open the `trading_bot/` folder in VSCode
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
| `Cannot connect to Ollama` | Run `ollama serve` in a terminal |
| `Model not found` | Run `ollama pull qwen2.5:7b` |
| `Risk review model not found` | Run `ollama pull deepseek-r1:8b` or set `ENABLE_RISK_REVIEW=False` |
| `Invalid symbol` | Add symbol to MT5 Market Watch manually |
| `Order failed: retcode=10014` | Invalid lot size — check broker's min lot |
| `Order failed: retcode=10019` | Not enough margin/balance |
