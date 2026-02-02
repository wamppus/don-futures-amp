#!/usr/bin/env python3
"""
DON Futures TopStep - GUI v2

This GUI is a VIEWER, not the engine.
The engine (bot/engine.py) does all the work.
GUI just displays what the engine is doing.

Key changes from v1:
- Engine runs independently in background thread
- GUI polls engine state for display
- No bar fetching or strategy processing in GUI
- Settings changes sent TO engine, not applied directly
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import json
import os
import sys
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from bot.engine import TradingEngine

CONFIG_FILE = "config.json"


class TradingBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("DON Futures TopStep - MNQ - v2")
        self.root.geometry("1000x750")
        self.root.minsize(900, 650)
        
        # Engine
        self.engine: TradingEngine = None
        
        # Log directory
        self.log_dir = os.path.join(os.path.dirname(__file__), 'bot', 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.setup_ui()
        self.load_config()
    
    def setup_ui(self):
        # Main container
        main = ttk.Frame(self.root, padding="10")
        main.pack(fill=tk.BOTH, expand=True)
        
        # === Top Row: Credentials + Settings ===
        top_frame = ttk.Frame(main)
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        # === Credentials Frame ===
        cred_frame = ttk.LabelFrame(top_frame, text="ProjectX Credentials", padding="10")
        cred_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        ttk.Label(cred_frame, text="Username:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(cred_frame, textvariable=self.username_var, width=30)
        self.username_entry.grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(cred_frame, text="API Key:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.apikey_var = tk.StringVar()
        self.apikey_entry = ttk.Entry(cred_frame, textvariable=self.apikey_var, width=30, show="*")
        self.apikey_entry.grid(row=1, column=1, padx=5, pady=2)
        
        self.show_key_var = tk.BooleanVar()
        ttk.Checkbutton(cred_frame, text="Show", variable=self.show_key_var, 
                       command=self.toggle_key_visibility).grid(row=1, column=2, padx=5)
        
        # === Settings Notebook (Tabbed) ===
        settings_notebook = ttk.Notebook(top_frame)
        settings_notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # --- Entry Tab ---
        entry_frame = ttk.Frame(settings_notebook, padding="5")
        settings_notebook.add(entry_frame, text="Entry")
        
        ttk.Label(entry_frame, text="S/R Lookback:").grid(row=0, column=0, sticky=tk.W, padx=2)
        self.lookback_var = tk.IntVar(value=10)
        ttk.Spinbox(entry_frame, from_=5, to=100, width=6, textvariable=self.lookback_var).grid(row=0, column=1, padx=2, pady=1)
        
        ttk.Label(entry_frame, text="Channel Lag:").grid(row=0, column=2, sticky=tk.W, padx=2)
        self.channel_lag_var = tk.IntVar(value=0)
        ttk.Spinbox(entry_frame, from_=0, to=20, width=6, textvariable=self.channel_lag_var).grid(row=0, column=3, padx=2, pady=1)
        
        ttk.Label(entry_frame, text="S/R Tolerance:").grid(row=1, column=0, sticky=tk.W, padx=2)
        self.sr_tolerance_var = tk.DoubleVar(value=1.0)
        ttk.Spinbox(entry_frame, from_=0.5, to=5.0, increment=0.25, width=6, textvariable=self.sr_tolerance_var).grid(row=1, column=1, padx=2, pady=1)
        
        # --- Exit Tab ---
        exit_frame = ttk.Frame(settings_notebook, padding="5")
        settings_notebook.add(exit_frame, text="Exit")
        
        ttk.Label(exit_frame, text="Stop (pts):").grid(row=0, column=0, sticky=tk.W, padx=2)
        self.stop_pts_var = tk.DoubleVar(value=4.0)
        ttk.Spinbox(exit_frame, from_=0.5, to=20.0, increment=0.5, width=6, textvariable=self.stop_pts_var).grid(row=0, column=1, padx=2, pady=1)
        
        ttk.Label(exit_frame, text="Target (pts):").grid(row=1, column=0, sticky=tk.W, padx=2)
        self.target_pts_var = tk.DoubleVar(value=4.0)
        ttk.Spinbox(exit_frame, from_=1.0, to=50.0, increment=0.5, width=6, textvariable=self.target_pts_var).grid(row=1, column=1, padx=2, pady=1)
        
        ttk.Label(exit_frame, text="Time Exit Bars:").grid(row=2, column=0, sticky=tk.W, padx=2)
        self.time_exit_var = tk.IntVar(value=5)
        ttk.Spinbox(exit_frame, from_=1, to=50, width=6, textvariable=self.time_exit_var).grid(row=2, column=1, padx=2, pady=1)
        
        ttk.Label(exit_frame, text="Trail Activate:").grid(row=0, column=2, sticky=tk.W, padx=2)
        self.trail_activation_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(exit_frame, from_=0.5, to=20.0, increment=0.5, width=6, textvariable=self.trail_activation_var).grid(row=0, column=3, padx=2, pady=1)
        
        ttk.Label(exit_frame, text="Trail Distance:").grid(row=1, column=2, sticky=tk.W, padx=2)
        self.trail_distance_var = tk.DoubleVar(value=1.5)
        ttk.Spinbox(exit_frame, from_=0.5, to=10.0, increment=0.5, width=6, textvariable=self.trail_distance_var).grid(row=1, column=3, padx=2, pady=1)
        
        # --- Risk Tab ---
        risk_frame = ttk.Frame(settings_notebook, padding="5")
        settings_notebook.add(risk_frame, text="Risk")
        
        ttk.Label(risk_frame, text="Max Daily Loss:").grid(row=0, column=0, sticky=tk.W, padx=2)
        self.max_daily_loss_var = tk.DoubleVar(value=1000.0)
        ttk.Spinbox(risk_frame, from_=100, to=5000, increment=100, width=8, textvariable=self.max_daily_loss_var).grid(row=0, column=1, padx=2, pady=1)
        
        ttk.Label(risk_frame, text="Max Trades/Day:").grid(row=1, column=0, sticky=tk.W, padx=2)
        self.max_trades_var = tk.IntVar(value=25)
        ttk.Spinbox(risk_frame, from_=5, to=100, width=8, textvariable=self.max_trades_var).grid(row=1, column=1, padx=2, pady=1)
        
        # Apply button
        ttk.Button(cred_frame, text="Apply Settings", command=self.apply_settings).grid(row=2, column=0, columnspan=3, pady=(10, 0))
        
        # === Status Frame ===
        status_frame = ttk.LabelFrame(main, text="Status", padding="10")
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Status row 1
        status_row1 = ttk.Frame(status_frame)
        status_row1.pack(fill=tk.X)
        
        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(status_row1, textvariable=self.status_var, font=('Arial', 12, 'bold')).pack(side=tk.LEFT, padx=10)
        
        self.quote_var = tk.StringVar(value="Quote: --")
        ttk.Label(status_row1, textvariable=self.quote_var, font=('Consolas', 10)).pack(side=tk.LEFT, padx=20)
        
        self.channel_var = tk.StringVar(value="Channel: --")
        ttk.Label(status_row1, textvariable=self.channel_var, font=('Consolas', 10)).pack(side=tk.LEFT, padx=20)
        
        # Status row 2 - Position
        status_row2 = ttk.Frame(status_frame)
        status_row2.pack(fill=tk.X, pady=(5, 0))
        
        self.position_var = tk.StringVar(value="Position: FLAT")
        ttk.Label(status_row2, textvariable=self.position_var, font=('Consolas', 10)).pack(side=tk.LEFT, padx=10)
        
        # Stats
        stats_frame = ttk.Frame(status_row1)
        stats_frame.pack(side=tk.RIGHT, padx=10)
        
        self.signals_var = tk.StringVar(value="Signals: 0")
        ttk.Label(stats_frame, textvariable=self.signals_var).pack(side=tk.LEFT, padx=10)
        
        self.trades_var = tk.StringVar(value="Trades: 0")
        ttk.Label(stats_frame, textvariable=self.trades_var).pack(side=tk.LEFT, padx=10)
        
        self.pnl_var = tk.StringVar(value="PnL: $0.00")
        ttk.Label(stats_frame, textvariable=self.pnl_var).pack(side=tk.LEFT, padx=10)
        
        # === Control Buttons ===
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_btn = ttk.Button(btn_frame, text="Start Engine", command=self.start_engine)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self.stop_engine, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="Open Logs", command=self.open_logs).pack(side=tk.RIGHT, padx=5)
        
        # === Log Frame ===
        log_frame = ttk.LabelFrame(main, text="Engine Log", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, state=tk.DISABLED,
                                                   font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Configure log colors
        self.log_text.tag_config('entry', foreground='green')
        self.log_text.tag_config('exit_win', foreground='green', font=('Consolas', 9, 'bold'))
        self.log_text.tag_config('exit_loss', foreground='red', font=('Consolas', 9, 'bold'))
        self.log_text.tag_config('error', foreground='red')
        self.log_text.tag_config('info', foreground='gray')
    
    def toggle_key_visibility(self):
        self.apikey_entry.config(show="" if self.show_key_var.get() else "*")
    
    def log(self, message, tag=None):
        """Add message to log"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def get_config(self) -> dict:
        """Get current config from UI"""
        return {
            'lookback_bars': self.lookback_var.get(),
            'channel_lag': self.channel_lag_var.get(),
            'sr_touch_tolerance': self.sr_tolerance_var.get(),
            'stop_pts': self.stop_pts_var.get(),
            'target_pts': self.target_pts_var.get(),
            'max_hold_bars': self.time_exit_var.get(),
            'trail_activation_pts': self.trail_activation_var.get(),
            'trail_distance': self.trail_distance_var.get(),
            'daily_loss_limit': self.max_daily_loss_var.get(),
            'max_trades_per_day': self.max_trades_var.get(),
            'use_trailing_stop': True,
        }
    
    def apply_settings(self):
        """Send settings to engine"""
        config = self.get_config()
        
        if self.engine:
            self.engine.update_config(config)
            self.log(f"Settings applied: Stop={config['stop_pts']}pts, Target={config['target_pts']}pts")
        else:
            self.log("Settings saved (will apply on start)")
        
        self.save_config()
    
    def save_config(self):
        """Save config to file"""
        config = {
            'username': self.username_var.get(),
            'api_key': self.apikey_var.get(),
            **self.get_config()
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    
    def load_config(self):
        """Load config from file"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                
                self.username_var.set(config.get('username', ''))
                self.apikey_var.set(config.get('api_key', ''))
                self.lookback_var.set(config.get('lookback_bars', 10))
                self.channel_lag_var.set(config.get('channel_lag', 0))
                self.sr_tolerance_var.set(config.get('sr_touch_tolerance', 1.0))
                self.stop_pts_var.set(config.get('stop_pts', 4.0))
                self.target_pts_var.set(config.get('target_pts', 4.0))
                self.time_exit_var.set(config.get('max_hold_bars', 5))
                self.trail_activation_var.set(config.get('trail_activation_pts', 2.0))
                self.trail_distance_var.set(config.get('trail_distance', 1.5))
                self.max_daily_loss_var.set(config.get('daily_loss_limit', 1000.0))
                self.max_trades_var.set(config.get('max_trades_per_day', 25))
                
                self.log("Config loaded")
            except Exception as e:
                self.log(f"Error loading config: {e}", 'error')
    
    def on_log(self, message: str, level: str = 'info'):
        """Callback from engine for log messages"""
        self.root.after(0, lambda: self.log(message, level))
    
    def on_state_change(self, state: dict):
        """Callback from engine when state changes"""
        def update():
            # Quote
            if state.get('mid'):
                self.quote_var.set(f"Bid: {state['bid']:.2f} | Ask: {state['ask']:.2f} | Mid: {state['mid']:.2f}")
            
            # Channel
            if state.get('channel_high'):
                self.channel_var.set(f"Channel: {state['channel_low']:.2f} - {state['channel_high']:.2f}")
            
            # Position
            if state.get('in_position'):
                direction = state['direction']
                entry = state['entry_price']
                stop = state['current_stop']
                target = state['current_target']
                pnl = state.get('unrealized_pnl', 0)
                self.position_var.set(f"Position: {direction} @ {entry:.2f} | Stop: {stop:.2f} | Target: {target:.2f} | Unrealized: {pnl:+.2f}")
            else:
                self.position_var.set("Position: FLAT")
            
            # Stats
            self.signals_var.set(f"Signals: {state.get('signals', 0)}")
            self.trades_var.set(f"Trades: {state.get('trades', 0)} ({state.get('wins', 0)}W/{state.get('losses', 0)}L)")
            self.pnl_var.set(f"PnL: ${state.get('session_pnl', 0):+.2f}")
            
            # Status
            if state.get('is_running'):
                self.status_var.set("Running (Shadow Mode)")
            elif state.get('is_connected'):
                self.status_var.set("Connected")
            else:
                self.status_var.set("Stopped")
        
        self.root.after(0, update)
    
    def on_entry(self, trade: dict):
        """Callback from engine on entry"""
        # Already logged by engine, just for additional UI updates if needed
        pass
    
    def on_exit(self, trade: dict):
        """Callback from engine on exit"""
        # Already logged by engine
        pass
    
    def start_engine(self):
        """Start the trading engine"""
        username = self.username_var.get()
        api_key = self.apikey_var.get()
        
        if not username or not api_key:
            messagebox.showerror("Error", "Please enter username and API key")
            return
        
        # Create engine with current config
        config = self.get_config()
        self.engine = TradingEngine(username, api_key, config)
        
        # Set callbacks
        self.engine.set_callbacks(
            on_log=self.on_log,
            on_state_change=self.on_state_change,
            on_entry=self.on_entry,
            on_exit=self.on_exit
        )
        
        # Start engine
        self.engine.start()
        
        # Update UI
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Starting...")
        self.log("Engine starting...")
    
    def stop_engine(self):
        """Stop the trading engine"""
        if self.engine:
            self.engine.stop()
        
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Stopping...")
    
    def open_logs(self):
        """Open logs directory"""
        import subprocess
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', self.log_dir])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', self.log_dir])
        else:
            subprocess.Popen(['xdg-open', self.log_dir])
    
    def on_close(self):
        """Handle window close"""
        if self.engine:
            self.engine.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = TradingBotGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == '__main__':
    main()
