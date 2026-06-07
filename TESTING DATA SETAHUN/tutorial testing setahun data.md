# Tutorial Testing Data Setahun - Investment-AI_T

Fail ini ialah panduan utama untuk run backtest / testing data setahun. Semua benda berkaitan testing setahun sekarang dikumpulkan dalam folder:

```text
TESTING DATA SETAHUN/
```

Tujuan dia supaya root project tidak bersepah dan awak tak lupa file mana perlu tekan.

---

## 1. Struktur Folder

```text
TESTING DATA SETAHUN/
  README.md
  tutorial testing setahun data.md
  run_yearly_backtest.py
  run_yearly_backtest.bat

  research/
    backtest_config.py
    backtest_state.py
    historical_data_collector.py
    virtual_exit_backtester.py
    report_generator.py

  reports/
    data setahun dari 25may2026.html

  storage/
    history/
    features/
    backtests/
    live/
```

Maksud folder:

```text
reports/
  Tempat report HTML final. Buka file HTML ini untuk tengok result.

storage/history/
  Data candle MT5 setahun: XAUUSD M5/M15/H1/H4.

storage/features/
  Dataset indicator + pattern yang dikesan.

storage/backtests/
  CSV result trade, pattern ranking, combo ranking, lock file, dan state file.

storage/live/
  Checkpoint data live/realtime. Ini penting supaya test setahun tidak ulang data yang bot live sudah cover.
```

---

## 2. Cara Run Paling Senang

Di laptop Windows:

```text
Double click:
TESTING DATA SETAHUN/run_yearly_backtest.bat
```

Atau guna terminal:

```bash
cd "TESTING DATA SETAHUN"
python run_yearly_backtest.py
```

Report akan keluar dekat:

```text
TESTING DATA SETAHUN/reports/data setahun dari 25may2026.html
```

---

## 3. Logic Tarikh Backtest

### First Run

Contoh awak tekan pada:

```text
25 May 2026
```

Sistem akan test:

```text
25 May 2025 -> 25 May 2026
```

Selepas siap, sistem simpan state:

```text
TESTING DATA SETAHUN/storage/backtests/yearly_backtest_state.json
```

### Kalau Tekan Lagi Ketika Bot Live Running 24 Jam

Kalau bot memang running dan data realtime sudah cover selepas last test, sistem tidak ulang backtest.

Result:

```text
0 historical days
No duplicate result
```

### Kalau Lama Tidak Buka Bot / Laptop

Contoh last test:

```text
25 May 2026
```

Awak buka semula:

```text
20 Jun 2026
```

Kalau live data tidak cover gap itu, sistem sambung:

```text
25 May 2026 -> 20 Jun 2026
```

Dia tidak ulang:

```text
20 Jun 2025 -> 20 Jun 2026
```

Ini memang untuk elak duplicate data.

---

## 4. Duplicate Protection

Kalau awak tertekan button 2 atau 3 kali, sistem buat lock file:

```text
TESTING DATA SETAHUN/storage/backtests/yearly_backtest.lock
```

Run pertama berjalan.

Run kedua akan stop dengan mesej:

```text
Yearly backtest already running
No duplicate run started
```

Kalau laptop crash dan lock file tertinggal, guna:

```bash
python run_yearly_backtest.py --force-unlock
```

Gunakan command ini hanya kalau yakin tiada backtest sedang running.

---

## 5. Command Penting

Run normal:

```bash
python run_yearly_backtest.py
```

Generate report sahaja tanpa run test:

```bash
python run_yearly_backtest.py --report-only
```

Paksa full-year semula:

```bash
python run_yearly_backtest.py --full-year
```

Paksa test gap dari last tested/live data sampai hari ini:

```bash
python run_yearly_backtest.py --include-gap
```

Skip gap walaupun lama tidak buka:

```bash
python run_yearly_backtest.py --skip-gap
```

Buang stale lock selepas crash:

```bash
python run_yearly_backtest.py --force-unlock
```

---

## 6. Apa Yang Report Akan Tunjuk

Report HTML akan tunjuk:

```text
Overall Result
  - total profit/loss
  - final balance
  - win rate
  - max drawdown
  - profit factor
  - best trade
  - worst trade

Pattern Result Table
  - pattern name
  - symbol
  - timeframe
  - detected count
  - used in trade count
  - win count
  - loss count
  - win rate
  - net profit/loss
  - average R
  - average confidence

Confluence Combos
  - combo pattern paling kuat
  - combo pattern paling lemah

Decision Audit
  - BUY / SELL / HOLD count
  - risk blocked
  - low confidence
  - virtual SL hit
  - virtual TP hit
  - trailing stop hit
  - reverse signal exit
```

---

## 7. Live Data Checkpoint

Untuk elak backtest ulang data yang bot live sudah cover, sistem boleh baca:

```text
TESTING DATA SETAHUN/storage/live/live_data_state.json
```

Format contoh:

```json
{
  "covered_until": "2026-06-20T10:00:00",
  "last_realtime_data_at": "2026-06-20T10:00:00",
  "last_seen_at": "2026-06-20T10:00:00"
}
```

Kalau file ini menunjukkan live data sudah cover sampai hari ini, yearly backtest akan jadi no-op.

Kalau file ini tiada atau tarikh dia sudah lama, backtest akan sambung dari last tested date.

---

## 8. Output File Yang Akan Terhasil

Selepas backtest berjaya, file biasanya ada di:

```text
TESTING DATA SETAHUN/storage/backtests/
  trades_fixed_lot.csv
  trades_config_risk.csv
  pattern_ranking.csv
  pattern_combo_ranking.csv
  decision_audit.csv
  backtest_summary.json
  yearly_backtest_state.json
```

Feature dataset:

```text
TESTING DATA SETAHUN/storage/features/
  pattern_dataset.csv
  pattern_detections.csv
```

History data:

```text
TESTING DATA SETAHUN/storage/history/
  XAUUSD_M5_*.csv
  XAUUSD_M15_*.csv
  XAUUSD_H1_*.csv
  XAUUSD_H4_*.csv
```

---

## 9. Important Notes

- Backtest ini tidak hantar order live ke MT5.
- Dia hanya ambil historical data dan simulate trade.
- SL/TP/trailing stop adalah virtual dalam simulation.
- Kalau SL dan TP kena dalam candle yang sama, sistem kira SL dulu untuk conservative result.
- Report tidak akan reka profit/loss. Kalau MT5/dependency/data belum ada, report tulis `Pending / No verified result yet`.
- Folder `storage/` di-ignore oleh Git supaya data besar tidak ter-commit ke GitHub.

---

## 10. Ringkasnya

Kalau nak test setahun:

```text
1. Buka folder TESTING DATA SETAHUN
2. Double click run_yearly_backtest.bat
3. Tunggu selesai
4. Buka reports/data setahun dari 25may2026.html
5. Tengok result profit/loss + pattern analytics
```
