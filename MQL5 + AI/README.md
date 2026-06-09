# InvestmentAI Brain v5.0 — MQL5 + AI Standalone

EA ini adalah sistem trading AI yang **100% standalone** — ia memanggil Groq API terus dari dalam MetaTrader 5 **tanpa memerlukan Python, Supabase Python bot, atau mana-mana proses luar**.

---

## 📁 Struktur Folder

```
MQL5 + AI/
├── Experts/
│   └── InvestmentAI_Brain.mq5      ← EA UTAMA
├── Include/
│   └── AIBrain/
│       ├── JsonParser.mqh           ← Parser JSON
│       ├── HttpClient.mqh           ← WebRequest wrapper (retry)
│       ├── SupabaseClient.mqh       ← Supabase REST client
│       ├── MarketData.mqh           ← OHLC + indicators + format JSON
│       ├── AIProvider.mqh           ← Groq API caller (3-key rotation)
│       ├── RiskGuard.mqh            ← Filter risiko
│       ├── TradeExecutor.mqh        ← Buka/tutup order
│       └── VirtualManager.mqh      ← Virtual SL/TP/Trailing
└── README.md                        ← Ini
```

---

## ⚙️ Cara Setup

### Langkah 1: Copy Fail ke MT5

1. Copy folder **`MQL5 + AI`** ini ke mana-mana lokasi pilihan anda
2. Atau copy kandungannya terus ke dalam directory MT5 anda:
   - `Experts/` → `C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\...\MQL5\Experts\`
   - `Include/AIBrain/` → `C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\...\MQL5\Include\AIBrain\`

### Langkah 2: Whitelist URL dalam MT5

Buka **MT5 → Tools → Options → Expert Advisors** dan tambah URL berikut:

```
https://api.groq.com
https://kusyjtpcjyflxgfcqenb.supabase.co
```

### Langkah 3: Compile EA

1. Buka **MetaEditor** (F4 dalam MT5)
2. Buka fail `InvestmentAI_Brain.mq5`
3. Tekan **F7** (Compile)
4. Pastikan tiada error (warning OK)

### Langkah 4: Pasang EA pada Chart

1. Drag EA `InvestmentAI_Brain` ke chart `XAUUSDc`
2. Isi parameter berikut:

| Parameter | Nilai |
|---|---|
| `Inp_AccountID` | Account ID awak (contoh: `Ammar`) |
| `Inp_SupabaseURL` | `https://kusyjtpcjyflxgfcqenb.supabase.co` |
| `Inp_SupabaseAnon` | Anon key Supabase awak |
| `Inp_GroqKey1` | Groq API Key #1 |
| `Inp_GroqKey2` | Groq API Key #2 (backup) |
| `Inp_GroqKey3` | Groq API Key #3 (backup) |
| `Inp_Symbol` | `XAUUSDc` (atau `XAUUSD` ikut broker) |

---

## 🧠 Cara Kerja

```
Setiap 5 minit   → SCALPING analysis (Groq AI)
Setiap 1 jam     → INTRADAY analysis (Groq AI)  
Setiap 2 jam     → SWING analysis (Groq AI)

Semua interval bermula dari 12:00 pagi (tengah malam) server time.
```

### Aliran Lengkap:
1. `OnTimer()` semak jika masa analisis sudah tiba
2. `BuildMarketDataJson()` kumpul EMA9/21, RSI14, MACD, ATR dari MT5
3. Data dihantar ke Groq API sebagai JSON prompt
4. AI menjawab: `BUY/SELL/HOLD`, confidence, SL, TP, alasan
5. `RiskGuard` semak: confidence, spread, drawdown, sesi, max trades
6. Jika lulus → `TradeExecutor` buka order (auto detect filling mode)
7. `VirtualManager` pantau SL/TP setiap tick → tutup bila hit
8. Semua trades sync ke Supabase → boleh pantau dari Dashboard

---

## 🔑 Groq API Keys

- Dapatkan keys percuma di: https://console.groq.com
- 3 keys digunakan secara bergilir (round-robin) supaya quota tak habis
- Jika satu key gagal/quota habis, EA akan cuba key seterusnya secara automatik

---

## 📊 Dashboard

Walaupun EA standalone, ia tetap sync ke Supabase:
- `active_trades` — trade yang sedang buka
- `closed_trades` — trade yang sudah tutup dengan P&L
- `signals` — log setiap keputusan AI
- `bot_heartbeat` — status EA (online/offline)

Boleh pantau dari **Dashboard Next.js** seperti biasa!

---

## ⚠️ Nota Penting

- **Satu EA = Satu akaun** — untuk 3 akaun, attach EA pada 3 terminal berbeza
- Pastikan `Account ID` betul supaya Supabase dapat bezakan data tiap akaun
- EA menggunakan **Virtual SL/TP** (tiada SL/TP diset di broker) untuk "stealth mode"
- Jika MT5 restart, EA akan **tidak** restore positions dari Supabase — akan tunggu analisis seterusnya

---

## 🆚 Perbezaan vs EA Lama (InvestmentAI_Executor)

| | EA Lama | EA Baru (Brain) |
|---|---|---|
| Buat analisis AI sendiri | ❌ | ✅ |
| Perlukan Python bot | ✅ | ❌ |
| Perlukan signal dari Supabase | ✅ | ❌ |
| Filling mode auto | ❌ | ✅ |
| 3 API key rotation | ❌ | ✅ |
| Sync dashboard | ✅ | ✅ |
