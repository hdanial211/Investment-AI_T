import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'Bot Engine'))

import time
from loguru import logger
from config import SUPABASE_CLIENT
import trade_evaluator

sig_id = f'TEST_SIG_{int(time.time())}'
SUPABASE_CLIENT.table('radar_signals').insert({
    'id': sig_id,
    'symbol': 'XAUUSD',
    'timeframe': 'H1',
    'direction': 'BUY',
    'ai_confidence': 85,
    'reason': 'Test Signal for pip verification',
    'status': 'WAITING',
    'trade_style': 'SCALPING'
}).execute()
logger.info(f'Injected test signal: {sig_id}')

trade_evaluator.loop_signal_executor(SUPABASE_CLIENT)
logger.info("Done verification.")
