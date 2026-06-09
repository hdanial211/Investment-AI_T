import os
import sys
import uuid
from loguru import logger
from Bot_Engine.trade_evaluator import loop_signal_executor
from Bot_Engine.config import SUPABASE_CLIENT
import time

def inject_test_signal():
    try:
        sig_id = f"TEST_SIG_{int(time.time())}"
        data, count = SUPABASE_CLIENT.table('radar_signals').insert({
            "id": sig_id,
            "symbol": "XAUUSD",
            "timeframe": "H1",
            "direction": "BUY",
            "ai_confidence": 85,
            "reason": "Test Signal for Pip-based Entry Verification",
            "status": "WAITING",
            "trade_style": "SCALPING"
        }).execute()
        logger.info(f"Injected test signal: {sig_id}")
    except Exception as e:
        logger.error(f"Failed to inject test signal: {e}")

if __name__ == "__main__":
    inject_test_signal()
    # Now run loop_signal_executor once
    logger.info("Running loop_signal_executor...")
    loop_signal_executor(SUPABASE_CLIENT)
    logger.info("Done verifying.")
