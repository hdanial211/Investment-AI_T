"""
bot_manager.py — Process Manager (Pengurus Induk) & Supabase Watcher untuk Cloud-Native V4
 
Tanggungjawab:
  1. Melancarkan 1 Master Analyzer (untuk cari signal).
  2. Menyemak 'Account Active' di Supabase setiap 15 saat.
  3. Melancarkan / Mematikan 'Trade Evaluator' untuk setiap akaun secara dinamik (Multi-Processing).
"""

import logging
import os
import sys
import time
import signal
import subprocess

# Tambah 'Bot Engine' ke path supaya boleh import SupabaseSync
BOT_ENGINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Bot Engine")
sys.path.append(BOT_ENGINE_DIR)

from trade_management.supabase_sync import SupabaseSync

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("BotManager")

# ─────────────────────────────────────────────────────────────────────────────
# GRACEFUL SHUTDOWN
# ─────────────────────────────────────────────────────────────────────────────
_shutdown_requested = False

def _signal_handler(signum, frame):
    global _shutdown_requested
    logger.info("Shutdown signal received. Stopping all processes...")
    _shutdown_requested = True

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ─────────────────────────────────────────────────────────────────────────────
# PROCESS WRAPPER
# ─────────────────────────────────────────────────────────────────────────────
PYTHON_EXE = sys.executable

class ManagedProcess:
    def __init__(self, name: str, cmd: list, cwd: str):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.process = None
        self.restart_count = 0
        self.last_start = 0
        self.max_restarts = 50

    def start(self):
        if self.process and self.process.poll() is None:
            return

        self.last_start = time.time()
        try:
            self.process = subprocess.Popen(
                self.cmd,
                cwd=self.cwd
            )
            logger.info(f"✅ [{self.name}] Started (PID: {self.process.pid})")
        except Exception as e:
            logger.error(f"❌ [{self.name}] Failed to start: {e}")

    def is_alive(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def stop(self):
        if self.process and self.is_alive():
            logger.info(f"🛑 [{self.name}] Stopping (PID: {self.process.pid})...")
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(f"⚠ [{self.name}] Force killing...")
                self.process.kill()
                self.process.wait()
            except Exception as e:
                logger.error(f"Error stopping [{self.name}]: {e}")

    def check_and_restart(self) -> bool:
        if self.is_alive():
            return False

        if self.process is not None:
            exit_code = self.process.returncode
            logger.warning(
                f"⚠ [{self.name}] Process died (exit code: {exit_code}). "
                f"Restart #{self.restart_count + 1}..."
            )

        if self.restart_count >= self.max_restarts:
            logger.error(f"❌ [{self.name}] Max restarts ({self.max_restarts}) reached. Giving up.")
            return False

        time.sleep(5)
        self.restart_count += 1
        self.start()
        return True

# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────
def main():
    global _shutdown_requested

    logger.info("=" * 70)
    logger.info("  🚀 BOT MANAGER & SUPABASE WATCHER — Multi-Process Hybrid")
    logger.info("=" * 70)
    logger.info(f"  Python: {PYTHON_EXE}")
    logger.info(f"  Bot Engine: {BOT_ENGINE_DIR}")
    logger.info("=" * 70)

    supabase = SupabaseSync()
    if not supabase.enabled:
        logger.error("Supabase tidak aktif. Sila semak .env")
        return

    # ── 1. Start Master Analyzer ──
    analyzer = ManagedProcess(
        name="Master Analyzer (The Brain)",
        cmd=[PYTHON_EXE, "master_analyzer.py"],
        cwd=BOT_ENGINE_DIR,
    )
    analyzer.start()

    logger.info(f"\n{'─'*70}")
    logger.info(f"  Running: 1 Analyzer (AI Brain)")
    logger.info(f"  Running: X Trade Evaluators (berdasarkan status di Supabase)")
    logger.info(f"{'─'*70}\n")

    # Penyimpan rekod proses Trade Evaluator yang sedang berjalan
    evaluators = {}  # { "acc_1": ManagedProcess, ... }
    last_sync_time = 0
    last_settings_hash = hash(str(supabase.fetch_system_settings()))

    # ── 2. Main monitoring & watcher loop ──
    while not _shutdown_requested:
        now = time.time()

        # Semak kesihatan proses (Auto-Restart)
        analyzer.check_and_restart()
        for acc_id, eval_proc in evaluators.items():
            eval_proc.check_and_restart()

        # Supabase Watcher Loop (Setiap 15 Saat)
        if now - last_sync_time >= 15:
            try:
                # 1. Semak perubahan System Settings (API Key, etc)
                current_settings_hash = hash(str(supabase.fetch_system_settings()))
                if current_settings_hash != last_settings_hash:
                    logger.warning("🔄 Supabase Watcher: Perubahan System Settings / API Key dikesan! Melakukan Global Restart...")
                    analyzer.stop()
                    for acc_id, eval_proc in evaluators.items():
                        eval_proc.stop()
                    evaluators.clear()
                    last_settings_hash = current_settings_hash
                    analyzer.start()
                    # Skip evaluator spawn in this cycle, will naturally spawn in next code block
                    
                # 2. Semak perubahan Akaun Individu (On/Off)
                enabled_accounts = set(supabase.fetch_all_enabled_accounts())
                current_running = set(evaluators.keys())

                # A. Akaun baharu di-ON-kan -> Mula Trade Evaluator
                accounts_to_start = enabled_accounts - current_running
                for acc_id in accounts_to_start:
                    logger.info(f"🔄 Supabase Watcher: Mengesan akaun AKTIF baharu: {acc_id}. Membuka proses Evaluator...")
                    proc = ManagedProcess(
                        name=f"Evaluator ({acc_id})",
                        cmd=[PYTHON_EXE, "trade_evaluator.py", acc_id],
                        cwd=BOT_ENGINE_DIR
                    )
                    proc.start()
                    evaluators[acc_id] = proc

                # B. Akaun di-OFF-kan -> Matikan Trade Evaluator
                accounts_to_stop = current_running - enabled_accounts
                for acc_id in accounts_to_stop:
                    logger.info(f"🔄 Supabase Watcher: Mengesan akaun {acc_id} telah di-OFF. Mematikan proses Evaluator...")
                    evaluators[acc_id].stop()
                    del evaluators[acc_id]

            except Exception as e:
                logger.error(f"Ralat semasa Watcher menyemak Supabase: {e}")

            last_sync_time = now

        time.sleep(2)

    # ── SHUTDOWN ──
    logger.info(f"\n{'='*70}")
    logger.info("  BOT MANAGER SHUTTING DOWN — Stopping all processes...")
    logger.info(f"{'='*70}")
    
    analyzer.stop()
    for acc_id, eval_proc in evaluators.items():
        eval_proc.stop()
        
    logger.info("✅ All processes stopped. Goodbye!")

if __name__ == "__main__":
    main()
