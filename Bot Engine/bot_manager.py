"""
bot_manager.py - V4 Orchestrator & Ghost Buster

Responsibilities:
- Runs every 15 seconds.
- Fetches all enabled accounts from Supabase.
- Launches or monitors trade_evaluator.py for each account (or runs the logic directly).
- Ghost Buster: Cleans up orphaned trades or ghost signals.
"""

import time
import logging
import signal
import sys
import subprocess
from trade_management.supabase_sync import SupabaseSync
import system_settings
from logger import setup_logging

logger = setup_logging()

_shutdown = False
def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Bot Manager shutting down...")
    _shutdown = True

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

def ghost_buster(supabase: SupabaseSync):
    """Clean up old active trades that are stuck or orphaned."""
    # This is a safety net. The main sync happens in trade_evaluator.py
    try:
        # Example: if a signal is active for > 24 hours, maybe deactivate it
        # Supabase RPC or custom logic can be placed here.
        pass
    except Exception as e:
        logger.error(f"Ghost Buster error: {e}")

def main():
    logger.info("==============================================")
    logger.info(" 🤖 BOT MANAGER (V4 ORCHESTRATOR) ")
    logger.info("==============================================")
    
    supabase = SupabaseSync()
    active_processes = {}
    
    while not _shutdown:
        system_settings.fetch_and_apply_system_settings()
        try:
            accounts = supabase.fetch_all_enabled_accounts()
        except Exception as e:
            logger.error(f"Failed to fetch accounts: {e}")
            accounts = []
            
        # Spawn trade_evaluator for each account if not running
        for acc in accounts:
            if acc not in active_processes or active_processes[acc].poll() is not None:
                logger.info(f"🚀 Launching trade_evaluator for {acc}...")
                p = subprocess.Popen([sys.executable, "trade_evaluator.py", acc])
                active_processes[acc] = p
                
        # Cleanup disabled accounts
        for acc in list(active_processes.keys()):
            if acc not in accounts:
                logger.info(f"🛑 Terminating trade_evaluator for {acc} (Account disabled)")
                active_processes[acc].terminate()
                del active_processes[acc]
                
        ghost_buster(supabase)
        
        # Sleep for 15 seconds (Orchestrator heartbeat)
        time.sleep(15)
        
    # Shutdown all
    for acc, p in active_processes.items():
        p.terminate()

if __name__ == "__main__":
    main()
