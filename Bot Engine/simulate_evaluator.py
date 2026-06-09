import sys
import time

def simulate_evaluator():
    print("Memulakan Simulasi Trade Evaluator (0 - 60 minit)...")
    
    # Simulate variables
    last_eval_minute = -1
    
    for current_minute in range(0, 61):
        is_startup = (last_eval_minute == -1)
        
        # Saringan masa
        run_evaluator = False
        if current_minute != last_eval_minute or is_startup:
            run_evaluator = True
            
        if run_evaluator:
            # Di dalam loop_evaluator:
            print(f"--- Minit ke-{current_minute} ---")
            
            # Scalping (15 minit)
            if current_minute % 15 == 0 or is_startup:
                print(f"  ✅ [SCALPING] Evaluator berjalan")
            else:
                print(f"  ⏭️ [SCALPING] Skip")
                
            # Intraday (30 minit)
            if current_minute % 30 == 0 or is_startup:
                print(f"  ✅ [INTRADAY] Evaluator berjalan")
            else:
                print(f"  ⏭️ [INTRADAY] Skip")
                
            # Swing (60 minit)
            if current_minute == 0 or current_minute == 60 or is_startup:
                print(f"  ✅ [SWING] Evaluator berjalan")
            else:
                print(f"  ⏭️ [SWING] Skip")
                
            last_eval_minute = current_minute
            
        # Fast forward
        time.sleep(0.01)

if __name__ == "__main__":
    simulate_evaluator()
