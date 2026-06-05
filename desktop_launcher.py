import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import os
import sys
import signal
import time
import queue

# For importing account_settings from Bot Engine
sys.path.append(os.path.join(os.path.dirname(__file__), "Bot Engine"))
try:
    from account_settings import get_all_enabled_accounts, account_has_active_trades
    from system_settings import fetch_and_apply_system_settings
except ImportError:
    pass

CREATE_NO_WINDOW = 0x08000000

class TerminalUI:
    def __init__(self, parent, name, command, bg_color="#1E1E1E", fg_color="#D4D4D4"):
        self.name = name
        self.command = command
        self.process = None
        
        # Frame
        self.frame = tk.Frame(parent, bg="#2D2D30", bd=2, relief=tk.GROOVE)
        
        # Header
        self.header_frame = tk.Frame(self.frame, bg="#2D2D30")
        self.header_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.lbl_title = tk.Label(self.header_frame, text=self.name, font=("Segoe UI", 10, "bold"), bg="#2D2D30", fg="#FFFFFF")
        self.lbl_title.pack(side=tk.LEFT)
        
        self.lbl_status = tk.Label(self.header_frame, text="🔴 Stopped", font=("Segoe UI", 9), bg="#2D2D30", fg="#FF5C5C")
        self.lbl_status.pack(side=tk.RIGHT)
        
        # Text Area
        self.text_area = scrolledtext.ScrolledText(self.frame, bg=bg_color, fg=fg_color, font=("Consolas", 9), wrap=tk.WORD)
        self.text_area.pack(fill=tk.BOTH, expand=True)
        
        # Configure Color Tags
        self.text_area.tag_config("ERROR", foreground="#FF5C5C")     # Red
        self.text_area.tag_config("WARNING", foreground="#F0E68C")   # Yellow (Khaki)
        self.text_area.tag_config("SUCCESS", foreground="#4CAF50")   # Green
        self.text_area.tag_config("INFO", foreground=fg_color)       # Default
        
        self.text_area.insert(tk.END, f"Ready to start {self.name}...\n")
        self.text_area.configure(state="disabled")

    def log(self, message):
        self.text_area.configure(state="normal")
        
        import re
        # Strip ANSI color codes
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_msg = ansi_escape.sub('', message)
        
        # Determine tag based on content
        tag = "INFO"
        upper_msg = clean_msg.upper()
        if "ERROR" in upper_msg or "CRITICAL" in upper_msg or "FAIL" in upper_msg or "✘" in clean_msg:
            tag = "ERROR"
        elif "WARNING" in upper_msg or "⚠" in clean_msg:
            tag = "WARNING"
        elif "SUCCESS" in upper_msg or "✅" in clean_msg or "✔" in clean_msg or "APPROVED" in upper_msg:
            tag = "SUCCESS"
            
        self.text_area.insert(tk.END, clean_msg, tag)
        self.text_area.see(tk.END)
        self.text_area.configure(state="disabled")

    def _read_output(self):
        try:
            for line in iter(self.process.stdout.readline, ''):
                if not line: break
                self.text_area.after(0, self.log, line)
        except Exception:
            pass
        finally:
            self.text_area.after(0, self.set_stopped)

    def start(self):
        if self.process and self.process.poll() is None:
            return # Already running
            
        self.log(f"\n--- Starting {self.name} ---\n")
        self.lbl_status.config(text="🟢 Running", fg="#4CAF50")
        
        env = os.environ.copy()
        # Ensure python outputs immediately (unbuffered)
        env["PYTHONUNBUFFERED"] = "1"
        
        # Get absolute path to the script folder
        cwd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Bot Engine")
        
        self.process = subprocess.Popen(
            self.command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        
        thread = threading.Thread(target=self._read_output, daemon=True)
        thread.start()

    def stop(self):
        if self.process and self.process.poll() is None:
            self.log(f"\n--- Stopping {self.name} ---\n")
            try:
                # Try graceful shutdown
                if os.name == 'nt':
                    os.kill(self.process.pid, signal.CTRL_C_EVENT)
                else:
                    os.kill(self.process.pid, signal.SIGTERM)
            except Exception:
                try:
                    self.process.terminate()
                except:
                    pass
            self.set_stopped()

    def set_stopped(self):
        self.lbl_status.config(text="🔴 Stopped", fg="#FF5C5C")
        self.process = None

class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Investment-AI Supervisor & Terminal Manager")
        self.root.geometry("1400x800")
        self.root.configure(bg="#1E1E1E")
        
        self.running = False
        
        # Terminals dictionary: key = ID, value = TerminalUI object
        self.terminals = {}
        
        # Top Control Bar
        self.control_frame = tk.Frame(root, bg="#252526", height=60)
        self.control_frame.pack(fill=tk.X, side=tk.TOP)
        self.control_frame.pack_propagate(False)
        
        lbl = tk.Label(self.control_frame, text="⚙️ AI Trading Supervisor", font=("Segoe UI", 14, "bold"), bg="#252526", fg="#FFFFFF")
        lbl.pack(side=tk.LEFT, padx=20, pady=15)
        
        self.btn_start_all = tk.Button(self.control_frame, text="▶ Start Supervisor", font=("Segoe UI", 10, "bold"), bg="#4CAF50", fg="white", borderwidth=0, padx=15, pady=5, cursor="hand2", command=self.start_supervisor)
        self.btn_start_all.pack(side=tk.RIGHT, padx=10, pady=15)
        
        self.btn_stop_all = tk.Button(self.control_frame, text="⏹ Stop All", font=("Segoe UI", 10, "bold"), bg="#FF5C5C", fg="white", borderwidth=0, padx=15, pady=5, cursor="hand2", command=self.stop_all)
        self.btn_stop_all.pack(side=tk.RIGHT, padx=5, pady=15)
        self.btn_stop_all.config(state=tk.DISABLED)
        
        self.lbl_watchdog = tk.Label(self.control_frame, text="Supervisor is inactive.", font=("Segoe UI", 10), bg="#252526", fg="#D4D4D4")
        self.lbl_watchdog.pack(side=tk.RIGHT, padx=20, pady=15)
        
        # Terminals Container (Grid layout with scrollbar if needed)
        self.canvas = tk.Canvas(root, bg="#1E1E1E", highlightthickness=0)
        self.scrollbar = tk.Scrollbar(root, orient="vertical", command=self.canvas.yview)
        
        self.terminals_frame = tk.Frame(self.canvas, bg="#1E1E1E")
        self.terminals_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        
        self.canvas.create_window((0, 0), window=self.terminals_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=0, pady=10)
        
        # We handle layout dynamically
        self.update_layout()

    def update_layout(self):
        """Rearrange terminals in a grid (2 columns max)."""
        col = 0
        row = 0
        
        # We always want Master Analyzer first if it exists
        term_keys = list(self.terminals.keys())
        if "master" in term_keys:
            term_keys.remove("master")
            term_keys.insert(0, "master")
            
        # Also let's put Watchdog terminal next
        if "watchdog" in term_keys:
            term_keys.remove("watchdog")
            term_keys.insert(1, "watchdog")

        for key in term_keys:
            term = self.terminals[key]
            term.frame.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
            # Give frame some fixed dimensions to prevent collapsing
            term.frame.configure(width=650, height=350)
            term.frame.grid_propagate(False)
            
            col += 1
            if col > 1:
                col = 0
                row += 1

    def ensure_terminal_exists(self, term_id, title, command, bg_color, fg_color):
        if term_id not in self.terminals:
            term = TerminalUI(self.terminals_frame, title, command, bg_color=bg_color, fg_color=fg_color)
            self.terminals[term_id] = term
            self.update_layout()
            # Start it automatically if supervisor is running
            if self.running:
                term.start()
        return self.terminals[term_id]

    def remove_terminal(self, term_id):
        if term_id in self.terminals:
            term = self.terminals[term_id]
            term.stop()
            term.frame.destroy()
            del self.terminals[term_id]
            self.update_layout()

    def watchdog_loop(self):
        """Runs in background thread, syncing settings every 5 minutes and managing terminals."""
        # We'll use a local "watchdog" terminal to show supervisor logs
        # We can simulate a terminal by just having one that prints our local logs
        
        while self.running:
            self.root.after(0, lambda: self.lbl_watchdog.config(text="🔄 Supervisor is checking Supabase..."))
            self._log_to_watchdog("\n[WATCHDOG] Waking up to check system settings and active accounts...")
            
            try:
                # 1. Fetch System Settings
                fetch_and_apply_system_settings()
                self._log_to_watchdog("[WATCHDOG] System settings & API keys fetched successfully.")
                
                # 2. Get active accounts from Supabase
                active_accounts = get_all_enabled_accounts()
                self._log_to_watchdog(f"[WATCHDOG] Found {len(active_accounts)} active accounts: {active_accounts}")
                
                # 3. Ensure Master Analyzer is running
                if len(active_accounts) > 0:
                    self.root.after(0, lambda: self.ensure_terminal_exists(
                        "master", "🧠 Master Analyzer", ["python", "master_analyzer.py"], "#101018", "#E6E6FA"
                    ))
                
                # 4. Ensure Trade Monitors are running
                for acc_id in active_accounts:
                    term_id = f"acc_{acc_id}"
                    title = f"📈 Monitor: Account {acc_id}"
                    cmd = ["python", "trade_monitor.py", str(acc_id)]
                    self.root.after(0, lambda t=term_id, ti=title, c=cmd: self.ensure_terminal_exists(
                        t, ti, c, "#181818", "#DCDCAA"
                    ))
                
                # 5. Stop & Remove inactive terminals
                # (Keep watchdog and master alone)
                # RULE: Never kill a terminal that has active trades — wait until trades are closed.
                existing_term_ids = list(self.terminals.keys())
                for term_id in existing_term_ids:
                    if term_id.startswith("acc_"):
                        acc_id_str = term_id.replace("acc_", "")
                        if acc_id_str not in active_accounts:
                            # Check if there are still active trades before killing
                            try:
                                has_trades = account_has_active_trades(acc_id_str)
                            except Exception:
                                has_trades = False
                                
                            if has_trades:
                                self._log_to_watchdog(f"[WATCHDOG] ⚠ Account {acc_id_str} is disabled but has ACTIVE TRADES. Terminal will stay alive until all trades are closed.")
                            else:
                                self._log_to_watchdog(f"[WATCHDOG] Account {acc_id_str} is disabled and has no active trades. Terminating its terminal...")
                                self.root.after(0, lambda t=term_id: self.remove_terminal(t))
                            
            except Exception as e:
                self._log_to_watchdog(f"[WATCHDOG] ⚠ Error during check: {e}")

            # Sleep for 5 minutes (300 seconds), broken down into small chunks to allow quick exit
            self.root.after(0, lambda: self.lbl_watchdog.config(text="✅ Supervisor active. Sleeping..."))
            
            # Setup signal watching
            import os, config, subprocess
            signals_file = os.path.join(config.LOG_DIR, "latest_signals.json")
            last_mtime = 0
            if os.path.exists(signals_file):
                last_mtime = os.path.getmtime(signals_file)
                
            for _ in range(300):
                if not self.running:
                    break
                    
                # Check for new signals
                if os.path.exists(signals_file):
                    current_mtime = os.path.getmtime(signals_file)
                    if current_mtime > last_mtime:
                        last_mtime = current_mtime
                        self._log_to_watchdog("\n[WATCHDOG] 🚨 New signals detected! Launching Entry Terminals...")
                        
                        try:
                            # Re-fetch active accounts just in case
                            from system_settings import get_all_enabled_accounts
                            active_accounts = get_all_enabled_accounts()
                            
                            for acc_id in active_accounts:
                                self._log_to_watchdog(f"[WATCHDOG] Spawning Entry Terminal for {acc_id}...")
                                # Spawn detached subprocess so it runs and dies on its own
                                # Pipe output to DEVNULL to avoid filling up the main terminal stdout, 
                                # but we could also read it. For now, it will log to its own file.
                                subprocess.Popen(
                                    ["python", "entry_terminal.py", str(acc_id)],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                )
                        except Exception as e:
                            self._log_to_watchdog(f"[WATCHDOG] Error launching entry terminals: {e}")
                            
                time.sleep(1)

    def _log_to_watchdog(self, msg):
        # Safely log to the watchdog terminal if it exists
        def append_log():
            if "watchdog" in self.terminals:
                self.terminals["watchdog"].log(msg + "\n")
        self.root.after(0, append_log)

    def start_supervisor(self):
        if self.running:
            return
            
        self.running = True
        self.btn_start_all.config(state=tk.DISABLED)
        self.btn_stop_all.config(state=tk.NORMAL)
        
        # Create a fake terminal for Watchdog output
        self.ensure_terminal_exists(
            "watchdog", "👁️ Watchdog / Supervisor", ["cmd.exe", "/c", "echo Supervisor running..."], "#0D1B2A", "#74B3CE"
        )
        
        # We don't actually run a process for watchdog, we just hijack the TerminalUI for logging.
        # But TerminalUI starts a subprocess if start() is called. 
        # By setting command to an infinite sleep or just letting it run out and stop, it's fine.
        
        # Start watchdog thread
        threading.Thread(target=self.watchdog_loop, daemon=True).start()

    def stop_all(self):
        self.running = False
        self.lbl_watchdog.config(text="Supervisor is inactive.")
        
        for term in self.terminals.values():
            term.stop()
            
        self.btn_start_all.config(state=tk.NORMAL)
        self.btn_stop_all.config(state=tk.DISABLED)

    def on_closing(self):
        self.stop_all()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = LauncherApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
