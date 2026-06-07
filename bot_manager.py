"""
bot_manager.py — Process Manager (Pengurus Induk) untuk Cloud-Native V4 Hybrid

This is the single entry point for the Python Brain. Run this script once, and it will:
  1. Spawn 1 Master Analyzer process.
  2. Monitor the process: auto-restart on crash within 5 seconds.
  
Note: Execution is now handled entirely by the MQL5 EA (InvestmentAI_Executor.mq5)
running inside client MT5 terminals.

Usage: python bot_manager.py
"""

import logging
import os
import sys
import time
import signal
import subprocess

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
BOT_ENGINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Bot Engine")
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
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    global _shutdown_requested

    logger.info("=" * 70)
    logger.info("  🚀 BOT MANAGER — 100% Cloud-Native Hybrid Architecture")
    logger.info("=" * 70)
    logger.info(f"  Python: {PYTHON_EXE}")
    logger.info(f"  Bot Engine: {BOT_ENGINE_DIR}")
    logger.info("=" * 70)

    # ── 1. Start Master Analyzer ──
    analyzer = ManagedProcess(
        name="Master Analyzer (The Brain)",
        cmd=[PYTHON_EXE, "master_analyzer.py"],
        cwd=BOT_ENGINE_DIR,
    )
    analyzer.start()

    logger.info(f"\n{'─'*70}")
    logger.info(f"  Running: 1 Analyzer (AI Brain & Supabase Writer)")
    logger.info(f"  Executors: Running natively in MQL5 terminals.")
    logger.info(f"{'─'*70}\n")

    # ── 2. Main monitoring loop ──
    while not _shutdown_requested:
        analyzer.check_and_restart()
        time.sleep(2)

    # ── SHUTDOWN ──
    logger.info(f"\n{'='*70}")
    logger.info("  BOT MANAGER SHUTTING DOWN — Stopping all processes...")
    logger.info(f"{'='*70}")
    analyzer.stop()
    logger.info("✅ All processes stopped. Goodbye!")

if __name__ == "__main__":
    main()
