#!/usr/bin/env bash
cd "$(dirname "$0")"

echo "============================================================"
echo "  Investment-AI_T V4 — 100% Cloud-Native Hybrid"
echo "  Master Analyzer (Otak AI) - Supabase DB"
echo "============================================================"
echo

echo "[1/2] Mendapatkan update terbaru dari GitHub..."
git pull 2>/dev/null
echo

echo "[2/2] Memulakan Master Analyzer & MT5..."
echo "  - Cuba membuka tetingkap MT5 secara automatik..."
open -a "MetaTrader 5" 2>/dev/null || open -a "XM MT5" 2>/dev/null || echo "  ⚠️ Gagal auto-buka MT5 (Sila buka secara manual jika ia belum terbuka)"
echo "  - Membaca market dan menghantar signal ke Supabase"
echo "  - Menilai (Evaluate) Active Trades setiap 10 minit"
echo "  - (Executor / MT5 berjalan berasingan di terminal klien)"
echo
echo "============================================================"
echo "  Tekan Ctrl+C untuk hentikan Master Analyzer."
echo "============================================================"
echo

python3 bot_manager.py
