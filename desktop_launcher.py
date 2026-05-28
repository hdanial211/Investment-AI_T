import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import os
import signal

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
            creationflags=CREATE_NO_WINDOW
        )
        
        thread = threading.Thread(target=self._read_output, daemon=True)
        thread.start()

    def stop(self):
        if self.process and self.process.poll() is None:
            self.log(f"\n--- Stopping {self.name} ---\n")
            try:
                # Use signal.CTRL_C_EVENT to allow graceful shutdown if possible
                os.kill(self.process.pid, signal.CTRL_C_EVENT)
            except Exception:
                try:
                    self.process.terminate()
                except:
                    pass
            self.set_stopped()

    def set_stopped(self):
        self.lbl_status.config(text="🔴 Stopped", fg="#FF5C5C")


class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Investment-AI Microservices Command Center")
        self.root.geometry("1400x700")
        self.root.configure(bg="#1E1E1E")
        
        # Top Control Bar
        self.control_frame = tk.Frame(root, bg="#252526", height=60)
        self.control_frame.pack(fill=tk.X, side=tk.TOP)
        self.control_frame.pack_propagate(False)
        
        lbl = tk.Label(self.control_frame, text="⚙️ AI Trading Bot Command Center", font=("Segoe UI", 14, "bold"), bg="#252526", fg="#FFFFFF")
        lbl.pack(side=tk.LEFT, padx=20, pady=15)
        
        btn_start_all = tk.Button(self.control_frame, text="▶ Start All", font=("Segoe UI", 10, "bold"), bg="#4CAF50", fg="white", borderwidth=0, padx=15, pady=5, cursor="hand2", command=self.start_all)
        btn_start_all.pack(side=tk.RIGHT, padx=10, pady=15)
        
        btn_stop_all = tk.Button(self.control_frame, text="⏹ Stop All", font=("Segoe UI", 10, "bold"), bg="#FF5C5C", fg="white", borderwidth=0, padx=15, pady=5, cursor="hand2", command=self.stop_all)
        btn_stop_all.pack(side=tk.RIGHT, padx=5, pady=15)
        
        # Terminals Container (Grid layout 2 columns)
        self.terminals_frame = tk.Frame(root, bg="#1E1E1E")
        self.terminals_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.terminals_frame.columnconfigure(0, weight=1)
        self.terminals_frame.columnconfigure(1, weight=1)
        self.terminals_frame.rowconfigure(0, weight=1)
        
        # Define Terminals
        self.terminals = [
            TerminalUI(self.terminals_frame, "🤖 Terminal 1: AI Trader", ["python", "main.py"], bg_color="#181818", fg_color="#DCDCAA"),
            TerminalUI(self.terminals_frame, "🛡️ Terminal 3: Trade Manager", ["python", "terminal_trade_manager.py"], bg_color="#181818", fg_color="#CE9178"),
        ]
        
        for i, term in enumerate(self.terminals):
            term.frame.grid(row=0, column=i, sticky="nsew", padx=5)

    def start_all(self):
        for term in self.terminals:
            term.start()

    def stop_all(self):
        for term in self.terminals:
            term.stop()

    def on_closing(self):
        self.stop_all()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = LauncherApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
