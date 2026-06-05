"""
bot_manager.py — Process Manager (Pengurus Induk)

This is the single entry point. Run this script once, and it will:
  1. Read enabled accounts from Supabase
  2. Spawn 1 Master Analyzer process
  3. Spawn N Executor Bot processes (1 per enabled account)
  4. Monitor all processes: auto-restart on crash within 5 seconds
  5. Dynamically add/remove executors when accounts change in Supabase

Usage: python bot_manager.py
"""

import logging
import os
import sys
import time
import signal
import subprocess
from datetime import datetime

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
PYTHON_EXE = sys.executable  # Use the same Python that started this script


class ManagedProcess:
    """Wrapper around a subprocess with auto-restart capability."""

    def __init__(self, name: str, cmd: list, cwd: str):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.process = None
        self.restart_count = 0
        self.last_start = 0
        self.max_restarts = 50  # Safety limit

    def start(self):
        """Start or restart the process."""
        if self.process and self.process.poll() is None:
            return  # Already running

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
        """Check if the process is still running."""
        if self.process is None:
            return False
        return self.process.poll() is None

    def stop(self):
        """Gracefully stop the process."""
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
        """Check if process died and restart it. Returns True if restarted."""
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

        # Wait 5 seconds before restart to avoid rapid cycling
        time.sleep(5)
        self.restart_count += 1
        self.start()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

ACCOUNT_REFRESH_INTERVAL = 120  # Check for new/removed accounts every 2 minutes


def get_enabled_accounts() -> list:
    """Fetch enabled accounts from Supabase."""
    try:
        # Add Bot Engine to path so we can import
        if BOT_ENGINE_DIR not in sys.path:
            sys.path.insert(0, BOT_ENGINE_DIR)

        import config
        from account_settings import get_all_enabled_accounts
        accounts = get_all_enabled_accounts()
        return [a for a in accounts if a != "master"]
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        return []


def main():
    global _shutdown_requested

    logger.info("=" * 70)
    logger.info("  🚀 BOT MANAGER — Investment-AI_T Decoupled Architecture")
    logger.info("=" * 70)
    logger.info(f"  Python: {PYTHON_EXE}")
    logger.info(f"  Bot Engine: {BOT_ENGINE_DIR}")
    logger.info("=" * 70)

    # ── 1. Start Master Analyzer ──
    analyzer = ManagedProcess(
        name="Master Analyzer",
        cmd=[PYTHON_EXE, "master_analyzer.py"],
        cwd=BOT_ENGINE_DIR,
    )
    analyzer.start()

    # ── 2. Get enabled accounts and start Executor Bots ──
    executors = {}  # account_id -> ManagedProcess
    last_account_check = 0

    def sync_executors():
        """Start/stop executors based on enabled accounts."""
        accounts = get_enabled_accounts()
        current_ids = set(executors.keys())
        desired_ids = set(accounts)

        # Start new executors
        for acc_id in desired_ids - current_ids:
            proc = ManagedProcess(
                name=f"Executor [{acc_id}]",
                cmd=[PYTHON_EXE, "executor_bot.py", acc_id],
                cwd=BOT_ENGINE_DIR,
            )
            proc.start()
            executors[acc_id] = proc
            logger.info(f"📦 New executor spawned for account: {acc_id}")

        # Stop removed executors
        for acc_id in current_ids - desired_ids:
            executors[acc_id].stop()
            del executors[acc_id]
            logger.info(f"🗑️ Executor removed for account: {acc_id}")

    sync_executors()
    last_account_check = time.time()

    logger.info(f"\n{'─'*70}")
    logger.info(f"  Running: 1 Analyzer + {len(executors)} Executor(s)")
    logger.info(f"  Accounts: {list(executors.keys())}")
    logger.info(f"{'─'*70}\n")

    # ── 3. Main monitoring loop ──
    while not _shutdown_requested:
        # Check Analyzer
        analyzer.check_and_restart()

        # Check all Executors
        for acc_id, proc in list(executors.items()):
            proc.check_and_restart()

        # Periodically refresh account list
        now = time.time()
        if now - last_account_check > ACCOUNT_REFRESH_INTERVAL:
            sync_executors()
            last_account_check = now

        time.sleep(2)

    # ── SHUTDOWN ──
    logger.info(f"\n{'='*70}")
    logger.info("  BOT MANAGER SHUTTING DOWN — Stopping all processes...")
    logger.info(f"{'='*70}")

    # Stop all executors first
    for acc_id, proc in executors.items():
        proc.stop()

    # Stop analyzer last
    analyzer.stop()

    logger.info("✅ All processes stopped. Goodbye!")


if __name__ == "__main__":
    main()
