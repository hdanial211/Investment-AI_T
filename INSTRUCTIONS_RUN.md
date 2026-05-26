# Panduan Menjalankan Sistem AI Trading Bot (Investment-AI_T)

Sistem ini terdiri daripada dua bahagian utama:
1. **Dashboard (Frontend Vercel)**: Boleh dibuka dan dipantau dari mana-mana peranti termasuk macOS/iPhone (melalui pelayar web).
2. **Bot Engine (Backend Python)**: Memerlukan persekitaran **Windows** kerana library `MetaTrader5` adalah eksklusif untuk sistem operasi Windows.

---

## 💻 Keperluan Sistem & OS (Sangat Penting)

Oleh kerana anda menggunakan **Mac (macOS)**, anda mempunyai tiga pilihan untuk menjalankan **Bot Engine**:
*   **Pilihan A (Terbaik untuk 24/7)**: Jalankan bot di **Windows VPS** (Virtual Private Server). Ini memastikan bot sentiasa berjalan walaupun laptop anda ditutup.
*   **Pilihan B (Percuma di Mac)**: Guna **Windows Virtual Machine (VM)** pada Mac anda menggunakan perisian seperti **Parallels Desktop**, **VMware Fusion**, atau **UTM** (percuma).
*   **Pilihan C**: Jalankan pada PC/Laptop Windows fizikal yang berasingan.

---

## 🚀 Langkah Demi Langkah Untuk Menjalankan Bot

Ikuti langkah-langkah di bawah pada persekitaran **Windows** anda:

### Langkah 1: Persediaan MetaTrader 5 (MT5)
1. Muat turun dan pasang **MetaTrader 5** dari broker anda (cth: RoboForex, XM, etc.).
2. Log masuk (Login) ke akaun trading anda (Demo digalakkan dahulu!).
3. Aktifkan butang **AutoTrading** di bahagian atas toolbar (pastikan ikon menjadi hijau).
4. Pergi ke menu `Tools → Options → Expert Advisors` dan tanda (✅) pada:
   *   `Allow automated trading`
   *   `Allow DLL imports`

### Langkah 2: Muat Turun Kod Projek
Klon atau salin folder projek `Investment-AI_T-master` ke dalam persekitaran Windows anda.

### Langkah 3: Jalankan Setup Pertama Kali (Automatic Setup)
1. Buka folder projek di Windows.
2. Klik dua kali (double-click) fail **`start_bot.bat`** di root folder.
3. Jika ini adalah kali pertama anda menjalankannya, skrip interaktif akan bermula secara automatik untuk membina fail `.env` tempatan anda.
4. Anda akan diminta untuk memasukkan maklumat berikut:
   *   **MT5 Login**: Nombor akaun MT5 anda.
   *   **MT5 Password**: Kata laluan akaun MT5 anda.
   *   **MT5 Server**: Nama server broker anda (cth: `RoboForex-Demo`).
   *   **OpenRouter API Key**: Kunci API dari OpenRouter (bermula dengan `sk-or-v1...`). Anda boleh dapatkan kunci ini secara percuma/berbayar di [openrouter.ai](https://openrouter.ai).
   *   **Hugging Face Token**: (Pilihan / Optional) Boleh tekan Enter untuk langkau.

Setelah selesai, fail konfigurasi sulit `.env` akan dicipta di dalam folder `Bot Engine/.env`. Fail ini tidak akan dimasukkan ke GitHub demi keselamatan akaun anda.

### Langkah 4: Aktifkan Supabase Sync (Untuk Sambungan Dashboard Vercel)
Untuk membolehkan Dashboard Vercel anda membaca tetapan dan memaparkan statistik perdagangan secara langsung (real-time) dari bot:
1. Buka terminal (PowerShell / Command Prompt) di dalam folder projek.
2. Jalankan skrip ini:
   ```cmd
   Setup\enable_supabase_sync.bat
   ```
3. Masukkan maklumat Supabase anda (boleh didapati di dashboard project Supabase anda):
   *   **Supabase URL**: `https://kusyjtpcjyflxgfcqenb.supabase.co`
   *   **Supabase Anon Key**: Kunci awam anon.
   *   **Supabase Service Role Key**: Kunci keselamatan tinggi (hanya disimpan secara tempatan pada komputer bot, jangan dedahkan di Vercel/Frontend).

### Langkah 5: Mulakan Bot!
Selepas semua konfigurasi selesai, anda hanya perlu klik dua kali fail:
👉 **`start_bot.bat`**

**Apa yang akan berlaku selepas anda klik?**
1. Sistem akan mengesahkan konfigurasi AI awan anda.
2. Memeriksa versi Python (memerlukan Python 3.10+).
3. Memasang dependensi yang diperlukan secara automatik dari `Setup/requirements.txt`.
4. Memulakan **Bot Engine** di latar belakang (background).
5. Membuka **Terminal UI Dashboard** secara langsung di skrin Windows anda untuk memaparkan log dan status perdagangan semasa!

---

## ⚙️ Menguruskan Tetapan Melalui Pelayar Web (Dashboard Vercel)

1. Buka dashboard anda di **Vercel** (pelayar web Mac atau telefon anda).
2. Pergi ke tab **Settings**.
3. Sekarang anda boleh mengubah parameter seperti Lot Size, membolehkan/menghalang gaya trading tertentu (Scalping, Intraday, Swing), dan had maksimum trade.
4. Klik **Save Settings**.
5. Bot yang sedang berjalan di Windows akan memuat turun tetapan terbaru ini secara automatik dari Supabase setiap **60 saat** dan melaraskannya tanpa perlu anda restart bot!

---

## 🛠️ Langkah Penyelesaian Masalah (Troubleshooting)

*   **Error: `MT5 initialize failed`**
    *   *Sebab*: Aplikasi MetaTrader 5 belum dibuka atau anda belum log masuk ke akaun.
    *   *Penyelesaian*: Buka MT5 terminal secara manual dan pastikan status sambungan di bucu bawah kanan menunjukkan warna hijau/biru (bersambung).
*   **Error: `OPENROUTER_API_KEY missing`**
    *   *Sebab*: Fail `.env` belum diisi dengan betul.
    *   *Penyelesaian*: Edit fail `Bot Engine/.env` secara manual menggunakan Notepad dan masukkan OpenRouter API key yang betul.
*   **Error: `Not enough margin` (retcode=10019)**
    *   *Sebab*: Baki akaun terlalu kecil untuk lot size yang dipilih.
    *   *Penyelesaian*: Kecilkan Lot Size di settings dashboard atau tambah baki akaun Demo anda.
