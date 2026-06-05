# Investment-AI_T: Project Rules & Architecture

These rules must be strictly followed when generating or modifying code for this project.

## 1. System Architecture (Split Terminal)
Sistem ini menggunakan senibina "Split Terminal" yang diuruskan oleh Watchdog (`desktop_launcher.py`).
- **`master_analyzer.py`**: Berfungsi sebagai "otak". Mempunyai akaun MT5 khasnya sendiri (bukan akaun klien). Ia membaca data pasaran, menganalisis dengan AI, dan menulis isyarat ke dalam `latest_signals.json`. Ia **TIDAK** membuka atau menguruskan trade.
- **`trade_monitor.py`**: Berjalan 24/7 untuk setiap akaun yang aktif. Tugasnya **HANYA** menguruskan *floating trades* (Virtual SL, TP, Trailing Stop, Break Even). Ia **TIDAK** membaca isyarat AI dan **TIDAK** membuka trade baru.
- **`entry_terminal.py`**: Terminal pakai-buang (*ephemeral*). Hanya dihidupkan oleh Watchdog apabila `latest_signals.json` dikemaskini. Ia membaca isyarat, menyemak margin (Risk Manager), membuka posisi di MT5, dan **terus mematikan dirinya (exit)**.
- **`desktop_launcher.py` (Watchdog)**: Antaramuka utama (GUI). Ia sentiasa memantau pangkalan data dan fail `latest_signals.json` untuk melancarkan terminal-terminal di atas.

## 2. Supabase is the Single Source of Truth
- **JANGAN** gunakan fail konfigurasi tempatan seperti `.env` (kecuali untuk perkara dasar sistem yang diarahkan oleh pengguna).
- Segala tetapan (Settings) **MESTI** dibaca dan disimpan di dalam Supabase:
  - Kekunci API & Model AI -> `system_settings`
  - Maklumat MT5 Master Analyzer -> `system_settings`
  - Maklumat MT5 Akaun & Tetapan Trading (Lot, TP, SL) -> `account_settings`
- Ini untuk mengelakkan percanggahan maklumat ("dua benda berlaku dalam satu masa").

## 3. UI/UX & Dashboard
- Dashboard dibina menggunakan HTML/Vanilla CSS. **JANGAN** gunakan TailwindCSS melainkan diarahkan.
- Pengguna mahu melihat semua pergerakan (log) terminal di dalam GUI `desktop_launcher.py`. Jangan sorokkan output terminal menggunakan `subprocess.DEVNULL` secara kekal jika ia menghalang pengguna dari melihat status (contoh: log dari `entry_terminal.py` mesti dipaparkan di tetingkap GUI).

## 4. Bahasa Komunikasi
- Pengguna (Hakim) berkomunikasi dalam Bahasa Melayu. Sentiasa balas penjelasan dan laporan kemaskini dalam Bahasa Melayu yang santai tetapi profesional. Gunakan istilah rasmi pengekodan/trading dalam Bahasa Inggeris jika perlu (contoh: *floating loss*, *margin*, *spawn*, *background process*).

## 5. Deployment / Sinkronisasi
- Bot beroperasi di peranti Windows pengguna, manakala Dashboard berada di web/peranti lain.
- Pastikan kod tidak bergantung kepada OS secara spesifik (contoh: sentiasa gunakan `os.path.join`).
- Sentiasa pastikan untuk membuat `git commit` dan arahkan pengguna melakukan `git pull` di peranti Windows mereka selepas membuat kemaskini penting.
