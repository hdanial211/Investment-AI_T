import re
import sys

with open("Bot Engine/master_analyzer.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update loop_signal_generator signature
if "def loop_signal_generator(supabase: SupabaseSync, connector: MT5Connector, accounts: list, target_style: str = None):" not in content:
    content = content.replace("def loop_signal_generator(supabase: SupabaseSync, connector: MT5Connector, accounts: list):", 
                              "def loop_signal_generator(supabase: SupabaseSync, connector: MT5Connector, accounts: list, target_style: str = None):")

# 2. Update styles list assignment inside loop_signal_generator
old_styles = 'styles = ["SCALPING", "INTRADAY", "SWING"]'
new_styles = 'styles = [target_style] if target_style else ["SCALPING", "INTRADAY", "SWING"]'
if new_styles not in content:
    content = content.replace(old_styles, new_styles)

# 3. Update main() loop
if "last_runs =" not in content:
    # Need to add import datetime
    if "from datetime import datetime" not in content:
        content = "from datetime import datetime\n" + content
        
    old_main_loop_start = "    last_signal_time = 0\n    last_heartbeat = 0\n    \n    while not _shutdown_requested:"
    new_main_loop_start = """    last_runs = {
        "SCALPING": "",
        "INTRADAY": "",
        "SWING": ""
    }
    last_heartbeat = 0
    
    while not _shutdown_requested:"""
    content = content.replace(old_main_loop_start, new_main_loop_start)
    
    old_signal_loop = """        # 2. Signal Generator Loop (10m)
        if now - last_signal_time >= 600:
            loop_signal_generator(supabase, connector, accounts)
            last_signal_time = now"""
            
    new_signal_loop = """        # 2. Clock-Based Schedule (Genap Masa)
        dt_now = datetime.now()
        cur_min = dt_now.minute
        time_str = dt_now.strftime("%Y-%m-%d %H:%M")
        
        # SWING (Setiap 1 Jam: XX:00)
        if cur_min == 0 and last_runs["SWING"] != time_str:
            loop_signal_generator(supabase, connector, accounts, target_style="SWING")
            last_runs["SWING"] = time_str
            
        # INTRADAY (Setiap 30 Min: XX:00, XX:30)
        if (cur_min == 0 or cur_min == 30) and last_runs["INTRADAY"] != time_str:
            loop_signal_generator(supabase, connector, accounts, target_style="INTRADAY")
            last_runs["INTRADAY"] = time_str
            
        # SCALPING (Setiap 10 Min: XX:00, XX:10, XX:20...)
        if (cur_min % 10 == 0) and last_runs["SCALPING"] != time_str:
            loop_signal_generator(supabase, connector, accounts, target_style="SCALPING")
            last_runs["SCALPING"] = time_str"""
            
    content = content.replace(old_signal_loop, new_signal_loop)

with open("Bot Engine/master_analyzer.py", "w", encoding="utf-8") as f:
    f.write(content)

print("master_analyzer.py patched successfully!")
