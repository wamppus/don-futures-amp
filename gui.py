#!/usr/bin/env python3
"""
DON Futures TopStep - MNQ - GUI (LIVE VERSION)
With quote-based pricing and configurable parameters
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import asyncio
import json
import os
import sys
import pandas as pd
from datetime import datetime, time, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from bot.projectx_client import ProjectXClient
from bot.strategy_adapter import DONStrategyAdapter as SRBounceStrategy, Direction, Quote

# Default strategy settings for DON
STRATEGY = {
    "lookback_bars": 10,
    "sr_touch_tolerance": 1.0,
    "retest_tolerance": 1.0,
    "min_gap_bars": 1,
    "use_ct_filter": False,
    "ct_bars": 2,
    "use_trend_filter": False,
    "trend_lookback": 20,
    "stop_pts": 4.0,
    "target_pts": 4.0,
    "max_hold_bars": 5,
    "rsi_period": 14,
    "rsi_exit_high": 70,
    "rsi_exit_low": 30,
    "use_trailing_stop": True,
    "trail_activation_pts": 8.0,   # Activate after 8pts profit
    "trail_distance": 4.0,         # Trail 4pts behind
}

TRADING = {
    "contracts": 4,  # 4 MNQ for TopStep 100K
    "symbol": "MNQ",
}

CONFIG_FILE = "config.json"


class TradingBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("DON Futures TopStep - MNQ - LIVE")
        self.root.geometry("1000x750")
        self.root.minsize(900, 650)
        
        # State
        self.is_running = False
        self.client = None
        self.strategy = None
        self.loop = None
        self.thread = None
        self.current_quote = None
        self.contract_id = None
        
        # Quote-based bar aggregation (fallback when ProjectX bars are stale)
        self.quote_bars = []  # List of completed bars built from quotes
        self.current_bar = None  # Bar currently being built
        self.bar_interval = 60  # 1-minute bars in seconds
        self.last_bar_minute = None
        
        # Stats
        self.signals_count = 0
        self.trades_count = 0
        self.pnl = 0.0
        self.session_trades = []  # Store trades for CSV export
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
        
        ttk.Button(cred_frame, text="Save", command=self.save_config).grid(row=0, column=3, rowspan=2, padx=10)
        
        # === Settings Notebook (Tabbed) ===
        settings_notebook = ttk.Notebook(top_frame)
        settings_notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # --- Entry Tab ---
        entry_frame = ttk.Frame(settings_notebook, padding="5")
        settings_notebook.add(entry_frame, text="Entry")
        
        # S/R Lookback
        ttk.Label(entry_frame, text="S/R Lookback:").grid(row=0, column=0, sticky=tk.W, padx=2)
        self.lookback_var = tk.IntVar(value=STRATEGY.get("lookback_bars", 10))
        ttk.Spinbox(entry_frame, from_=5, to=100, width=6, textvariable=self.lookback_var).grid(row=0, column=1, padx=2, pady=1)
        
        # Channel Lag (bars)
        ttk.Label(entry_frame, text="Channel Lag:").grid(row=0, column=2, sticky=tk.W, padx=2)
        self.channel_lag_var = tk.IntVar(value=STRATEGY.get("channel_lag", 0))
        ttk.Spinbox(entry_frame, from_=0, to=20, width=6, textvariable=self.channel_lag_var).grid(row=0, column=3, padx=2, pady=1)
        
        # S/R Touch Tolerance
        ttk.Label(entry_frame, text="S/R Tolerance:").grid(row=1, column=0, sticky=tk.W, padx=2)
        self.sr_tolerance_var = tk.DoubleVar(value=STRATEGY.get("sr_touch_tolerance", 1.5))
        ttk.Spinbox(entry_frame, from_=0.5, to=5.0, increment=0.25, width=6, textvariable=self.sr_tolerance_var).grid(row=1, column=1, padx=2, pady=1)
        
        # Retest Tolerance
        ttk.Label(entry_frame, text="Retest Tol:").grid(row=2, column=0, sticky=tk.W, padx=2)
        self.retest_tolerance_var = tk.DoubleVar(value=STRATEGY.get("retest_tolerance", 1.0))
        ttk.Spinbox(entry_frame, from_=0.5, to=5.0, increment=0.25, width=6, textvariable=self.retest_tolerance_var).grid(row=2, column=1, padx=2, pady=1)
        
        # Min Gap Bars
        ttk.Label(entry_frame, text="Min Gap Bars:").grid(row=3, column=0, sticky=tk.W, padx=2)
        self.min_gap_bars_var = tk.IntVar(value=STRATEGY.get("min_gap_bars", 5))
        ttk.Spinbox(entry_frame, from_=1, to=20, width=6, textvariable=self.min_gap_bars_var).grid(row=3, column=1, padx=2, pady=1)
        
        # --- Filters Tab ---
        filters_frame = ttk.Frame(settings_notebook, padding="5")
        settings_notebook.add(filters_frame, text="Filters")
        
        # Counter-Trend Filter
        self.use_ct_filter_var = tk.BooleanVar(value=STRATEGY.get("use_ct_filter", True))
        ttk.Checkbutton(filters_frame, text="Counter-Trend Filter", variable=self.use_ct_filter_var).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=2)
        
        ttk.Label(filters_frame, text="CT Bars:").grid(row=1, column=0, sticky=tk.W, padx=2)
        self.ct_bars_var = tk.IntVar(value=STRATEGY.get("ct_bars", 2))
        ttk.Spinbox(filters_frame, from_=1, to=10, width=6, textvariable=self.ct_bars_var).grid(row=1, column=1, padx=2, pady=1)
        
        # Trend Filter
        self.use_trend_filter_var = tk.BooleanVar(value=STRATEGY.get("use_trend_filter", True))
        ttk.Checkbutton(filters_frame, text="Trend Filter", variable=self.use_trend_filter_var).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=2)
        
        ttk.Label(filters_frame, text="Trend Lookback:").grid(row=3, column=0, sticky=tk.W, padx=2)
        self.trend_lookback_var = tk.IntVar(value=STRATEGY.get("trend_lookback", 30))
        ttk.Spinbox(filters_frame, from_=10, to=100, width=6, textvariable=self.trend_lookback_var).grid(row=3, column=1, padx=2, pady=1)
        
        # --- Exit Tab ---
        exit_frame = ttk.Frame(settings_notebook, padding="5")
        settings_notebook.add(exit_frame, text="Exit")
        
        # Stop Loss
        ttk.Label(exit_frame, text="Stop (pts):").grid(row=0, column=0, sticky=tk.W, padx=2)
        self.stop_pts_var = tk.DoubleVar(value=STRATEGY.get("stop_pts", 1.5))
        ttk.Spinbox(exit_frame, from_=0.5, to=10.0, increment=0.25, width=6, textvariable=self.stop_pts_var).grid(row=0, column=1, padx=2, pady=1)
        
        # Target
        ttk.Label(exit_frame, text="Target (pts):").grid(row=1, column=0, sticky=tk.W, padx=2)
        self.target_pts_var = tk.DoubleVar(value=STRATEGY.get("target_pts", 4.0))
        ttk.Spinbox(exit_frame, from_=1.0, to=20.0, increment=0.25, width=6, textvariable=self.target_pts_var).grid(row=1, column=1, padx=2, pady=1)
        
        # Time Exit Bars
        ttk.Label(exit_frame, text="Time Exit Bars:").grid(row=2, column=0, sticky=tk.W, padx=2)
        self.time_exit_var = tk.IntVar(value=STRATEGY.get("max_hold_bars", 5))
        ttk.Spinbox(exit_frame, from_=1, to=20, width=6, textvariable=self.time_exit_var).grid(row=2, column=1, padx=2, pady=1)
        
        # RSI Period
        ttk.Label(exit_frame, text="RSI Period:").grid(row=0, column=2, sticky=tk.W, padx=2)
        self.rsi_period_var = tk.IntVar(value=STRATEGY.get("rsi_period", 14))
        ttk.Spinbox(exit_frame, from_=5, to=30, width=6, textvariable=self.rsi_period_var).grid(row=0, column=3, padx=2, pady=1)
        
        # RSI Exit High
        ttk.Label(exit_frame, text="RSI Exit Long:").grid(row=1, column=2, sticky=tk.W, padx=2)
        self.rsi_exit_high_var = tk.IntVar(value=STRATEGY.get("rsi_exit_high", 70))
        ttk.Spinbox(exit_frame, from_=50, to=90, width=6, textvariable=self.rsi_exit_high_var).grid(row=1, column=3, padx=2, pady=1)
        
        # RSI Exit Low
        ttk.Label(exit_frame, text="RSI Exit Short:").grid(row=2, column=2, sticky=tk.W, padx=2)
        self.rsi_exit_low_var = tk.IntVar(value=STRATEGY.get("rsi_exit_low", 30))
        ttk.Spinbox(exit_frame, from_=10, to=50, width=6, textvariable=self.rsi_exit_low_var).grid(row=2, column=3, padx=2, pady=1)
        
        # Trail Activation
        ttk.Label(exit_frame, text="Trail Activate:").grid(row=3, column=0, sticky=tk.W, padx=2)
        self.trail_activation_var = tk.DoubleVar(value=STRATEGY.get("trail_activation_pts", 8.0))
        ttk.Spinbox(exit_frame, from_=1.0, to=50.0, increment=1.0, width=6, textvariable=self.trail_activation_var).grid(row=3, column=1, padx=2, pady=1)
        
        # Trail Distance
        ttk.Label(exit_frame, text="Trail Distance:").grid(row=3, column=2, sticky=tk.W, padx=2)
        self.trail_distance_var = tk.DoubleVar(value=STRATEGY.get("trail_distance", 4.0))
        ttk.Spinbox(exit_frame, from_=0.5, to=20.0, increment=0.5, width=6, textvariable=self.trail_distance_var).grid(row=3, column=3, padx=2, pady=1)
        
        # --- Risk Tab ---
        risk_frame = ttk.Frame(settings_notebook, padding="5")
        settings_notebook.add(risk_frame, text="Risk")
        
        # Contracts
        ttk.Label(risk_frame, text="Contracts:").grid(row=0, column=0, sticky=tk.W, padx=2)
        self.contracts_var = tk.IntVar(value=TRADING.get("contracts", 2))
        ttk.Spinbox(risk_frame, from_=1, to=5, width=6, textvariable=self.contracts_var).grid(row=0, column=1, padx=2, pady=1)
        
        # Max Daily Loss
        ttk.Label(risk_frame, text="Max Daily Loss (pts):").grid(row=1, column=0, sticky=tk.W, padx=2)
        self.max_daily_loss_var = tk.DoubleVar(value=20.0)
        ttk.Spinbox(risk_frame, from_=5.0, to=100.0, increment=5.0, width=6, textvariable=self.max_daily_loss_var).grid(row=1, column=1, padx=2, pady=1)
        
        # Max Daily Trades
        ttk.Label(risk_frame, text="Max Daily Trades:").grid(row=2, column=0, sticky=tk.W, padx=2)
        self.max_daily_trades_var = tk.IntVar(value=50)
        ttk.Spinbox(risk_frame, from_=5, to=100, width=6, textvariable=self.max_daily_trades_var).grid(row=2, column=1, padx=2, pady=1)
        
        # Max Consecutive Losses
        ttk.Label(risk_frame, text="Max Consec. Losses:").grid(row=3, column=0, sticky=tk.W, padx=2)
        self.max_consec_losses_var = tk.IntVar(value=5)
        ttk.Spinbox(risk_frame, from_=2, to=20, width=6, textvariable=self.max_consec_losses_var).grid(row=3, column=1, padx=2, pady=1)
        
        # --- Session Tab ---
        session_frame = ttk.Frame(settings_notebook, padding="5")
        settings_notebook.add(session_frame, text="Session")
        
        # Trading Windows
        ttk.Label(session_frame, text="Windows:").grid(row=0, column=0, sticky=tk.W, padx=2)
        windows_frame = ttk.Frame(session_frame)
        windows_frame.grid(row=0, column=1, columnspan=2, sticky=tk.W, padx=2)
        
        self.window1_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(windows_frame, text="9:30-11:30", variable=self.window1_var).pack(side=tk.LEFT)
        
        self.window2_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(windows_frame, text="15:00-16:00", variable=self.window2_var).pack(side=tk.LEFT, padx=(5, 0))
        
        self.window3_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(windows_frame, text="All Day", variable=self.window3_var,
                       command=self.toggle_all_day).pack(side=tk.LEFT, padx=(5, 0))
        
        # Last Entry Time (hard stop)
        ttk.Label(session_frame, text="Last Entry:").grid(row=1, column=0, sticky=tk.W, padx=2)
        entry_time_frame = ttk.Frame(session_frame)
        entry_time_frame.grid(row=1, column=1, sticky=tk.W, padx=2)
        
        self.last_entry_hour_var = tk.IntVar(value=15)
        self.last_entry_min_var = tk.IntVar(value=55)
        ttk.Spinbox(entry_time_frame, from_=9, to=16, width=3, textvariable=self.last_entry_hour_var).pack(side=tk.LEFT)
        ttk.Label(entry_time_frame, text=":").pack(side=tk.LEFT)
        ttk.Spinbox(entry_time_frame, from_=0, to=59, width=3, textvariable=self.last_entry_min_var).pack(side=tk.LEFT)
        
        # Apply button at bottom of credentials frame
        ttk.Button(cred_frame, text="Apply All", command=self.apply_settings).grid(row=2, column=0, columnspan=4, pady=(10, 0))
        
        # === Status Frame ===
        status_frame = ttk.LabelFrame(main, text="Status", padding="10")
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Status indicators row 1
        status_row1 = ttk.Frame(status_frame)
        status_row1.pack(fill=tk.X)
        
        self.status_var = tk.StringVar(value="⚪ Stopped")
        ttk.Label(status_row1, textvariable=self.status_var, font=('Arial', 12, 'bold')).pack(side=tk.LEFT, padx=10)
        
        # Quote display
        self.quote_var = tk.StringVar(value="Quote: --")
        ttk.Label(status_row1, textvariable=self.quote_var, font=('Consolas', 10)).pack(side=tk.LEFT, padx=20)
        
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
        
        self.start_btn = ttk.Button(btn_frame, text="▶ Start Shadow Mode", command=self.start_bot)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(btn_frame, text="⏹ Stop", command=self.stop_bot, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="🔄 Test Connection", command=self.test_connection).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="📁 Open Logs", command=self.open_logs).pack(side=tk.RIGHT, padx=5)
        
        # === Log Frame ===
        log_frame = ttk.LabelFrame(main, text="Activity Log", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, state=tk.DISABLED,
                                                   font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Configure log colors
        self.log_text.tag_config('signal', foreground='blue')
        self.log_text.tag_config('entry', foreground='green')
        self.log_text.tag_config('exit_win', foreground='green', font=('Consolas', 9, 'bold'))
        self.log_text.tag_config('exit_loss', foreground='red', font=('Consolas', 9, 'bold'))
        self.log_text.tag_config('error', foreground='red')
        self.log_text.tag_config('info', foreground='gray')
        self.log_text.tag_config('quote', foreground='purple')
        self.log_text.tag_config('skip', foreground='orange')
    
    def toggle_key_visibility(self):
        self.apikey_entry.config(show="" if self.show_key_var.get() else "*")
    
    def toggle_all_day(self):
        """Toggle all day mode"""
        if self.window3_var.get():
            self.window1_var.set(False)
            self.window2_var.set(False)
    
    def get_trading_windows(self):
        """Get trading windows from UI"""
        windows = []
        if self.window3_var.get():
            # All day mode
            windows.append((time(9, 30), time(16, 0)))
        else:
            if self.window1_var.get():
                windows.append((time(9, 30), time(11, 30)))
            if self.window2_var.get():
                windows.append((time(15, 0), time(16, 0)))
        return windows
    
    def get_last_entry_time(self):
        """Get last entry time from UI"""
        return time(self.last_entry_hour_var.get(), self.last_entry_min_var.get())
    
    def apply_settings(self):
        """Apply settings to running strategy"""
        config = {
            # Entry
            "lookback_bars": self.lookback_var.get(),
            "channel_lag": self.channel_lag_var.get(),
            "sr_touch_tolerance": self.sr_tolerance_var.get(),
            "retest_tolerance": self.retest_tolerance_var.get(),
            "min_gap_bars": self.min_gap_bars_var.get(),
            # Filters
            "use_ct_filter": self.use_ct_filter_var.get(),
            "ct_bars": self.ct_bars_var.get(),
            "use_trend_filter": self.use_trend_filter_var.get(),
            "trend_lookback": self.trend_lookback_var.get(),
            # Exit
            "stop_pts": self.stop_pts_var.get(),
            "target_pts": self.target_pts_var.get(),
            "max_hold_bars": self.time_exit_var.get(),
            "rsi_period": self.rsi_period_var.get(),
            "rsi_exit_high": self.rsi_exit_high_var.get(),
            "rsi_exit_low": self.rsi_exit_low_var.get(),
            "trail_activation_pts": self.trail_activation_var.get(),
            "trail_distance": self.trail_distance_var.get(),
            # Session
            "trading_windows": self.get_trading_windows(),
            "last_entry_time": self.get_last_entry_time(),
        }
        
        if self.strategy:
            self.strategy.update_config(config)
            self.log(f"Settings updated: Stop={config['stop_pts']}pts, Target={config['target_pts']}pts, "
                    f"Lookback={config['lookback_bars']}, TimeExit={config['max_hold_bars']} bars", 'info')
        else:
            self.log("Settings saved (will apply on start)", 'info')
        
        # Save to config file
        self.save_config()
    
    def log(self, message, tag=None):
        """Add message to log"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def save_config(self):
        """Save credentials and settings to config file"""
        config = {
            # Credentials
            "username": self.username_var.get(),
            "api_key": self.apikey_var.get(),
            # Entry
            "lookback_bars": self.lookback_var.get(),
            "channel_lag": self.channel_lag_var.get(),
            "sr_touch_tolerance": self.sr_tolerance_var.get(),
            "retest_tolerance": self.retest_tolerance_var.get(),
            "min_gap_bars": self.min_gap_bars_var.get(),
            # Filters
            "use_ct_filter": self.use_ct_filter_var.get(),
            "ct_bars": self.ct_bars_var.get(),
            "use_trend_filter": self.use_trend_filter_var.get(),
            "trend_lookback": self.trend_lookback_var.get(),
            # Exit
            "stop_pts": self.stop_pts_var.get(),
            "target_pts": self.target_pts_var.get(),
            "time_exit_bars": self.time_exit_var.get(),
            "rsi_period": self.rsi_period_var.get(),
            "rsi_exit_high": self.rsi_exit_high_var.get(),
            "rsi_exit_low": self.rsi_exit_low_var.get(),
            "trail_activation_pts": self.trail_activation_var.get(),
            "trail_distance": self.trail_distance_var.get(),
            # Risk
            "contracts": self.contracts_var.get(),
            "max_daily_loss_pts": self.max_daily_loss_var.get(),
            "max_daily_trades": self.max_daily_trades_var.get(),
            "max_consecutive_losses": self.max_consec_losses_var.get(),
            # Session
            "window_morning": self.window1_var.get(),
            "window_power_hour": self.window2_var.get(),
            "window_all_day": self.window3_var.get(),
            "last_entry_hour": self.last_entry_hour_var.get(),
            "last_entry_min": self.last_entry_min_var.get(),
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        self.log("Configuration saved", 'info')
    
    def load_config(self):
        """Load credentials and settings from config file"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                # Credentials
                self.username_var.set(config.get("username", ""))
                self.apikey_var.set(config.get("api_key", ""))
                # Entry
                self.lookback_var.set(config.get("lookback_bars", STRATEGY.get("lookback_bars", 10)))
                self.sr_tolerance_var.set(config.get("sr_touch_tolerance", STRATEGY.get("sr_touch_tolerance", 1.5)))
                self.retest_tolerance_var.set(config.get("retest_tolerance", STRATEGY.get("retest_tolerance", 1.0)))
                self.min_gap_bars_var.set(config.get("min_gap_bars", STRATEGY.get("min_gap_bars", 5)))
                # Filters
                self.use_ct_filter_var.set(config.get("use_ct_filter", STRATEGY.get("use_ct_filter", True)))
                self.ct_bars_var.set(config.get("ct_bars", STRATEGY.get("ct_bars", 2)))
                self.use_trend_filter_var.set(config.get("use_trend_filter", STRATEGY.get("use_trend_filter", True)))
                self.trend_lookback_var.set(config.get("trend_lookback", STRATEGY.get("trend_lookback", 30)))
                # Exit
                self.stop_pts_var.set(config.get("stop_pts", STRATEGY.get("stop_pts", 1.5)))
                self.target_pts_var.set(config.get("target_pts", STRATEGY.get("target_pts", 4.0)))
                self.time_exit_var.set(config.get("time_exit_bars", STRATEGY.get("max_hold_bars", 5)))
                self.rsi_period_var.set(config.get("rsi_period", STRATEGY.get("rsi_period", 14)))
                self.rsi_exit_high_var.set(config.get("rsi_exit_high", STRATEGY.get("rsi_exit_high", 70)))
                self.rsi_exit_low_var.set(config.get("rsi_exit_low", STRATEGY.get("rsi_exit_low", 30)))
                # Risk
                self.contracts_var.set(config.get("contracts", TRADING.get("contracts", 2)))
                self.max_daily_loss_var.set(config.get("max_daily_loss_pts", 20.0))
                self.max_daily_trades_var.set(config.get("max_daily_trades", 50))
                self.max_consec_losses_var.set(config.get("max_consecutive_losses", 5))
                # Session
                self.window1_var.set(config.get("window_morning", True))
                self.window2_var.set(config.get("window_power_hour", True))
                self.window3_var.set(config.get("window_all_day", False))
                self.last_entry_hour_var.set(config.get("last_entry_hour", 15))
                self.last_entry_min_var.set(config.get("last_entry_min", 55))
                self.log("Configuration loaded", 'info')
            except Exception as e:
                self.log(f"Error loading config: {e}", 'error')
    
    def test_connection(self):
        """Test ProjectX connection"""
        username = self.username_var.get()
        api_key = self.apikey_var.get()
        
        if not username or not api_key:
            messagebox.showerror("Error", "Please enter username and API key")
            return
        
        self.log("Testing connection...", 'info')
        
        def run_test():
            async def test():
                client = ProjectXClient(username, api_key)
                try:
                    if await client.connect():
                        accounts = await client.get_accounts()
                        es = await client.find_mnq_contract()
                        await client.disconnect()
                        return True, accounts, es
                    return False, None, None
                except Exception as e:
                    return False, None, str(e)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(test())
            loop.close()
            
            self.root.after(0, lambda: self.handle_test_result(result))
        
        threading.Thread(target=run_test, daemon=True).start()
    
    def handle_test_result(self, result):
        success, accounts, es = result
        if success:
            self.log("✅ Connection successful!", 'entry')
            if accounts:
                for acc in accounts:
                    self.log(f"   Account: {acc.get('name')}", 'info')
            if es:
                self.log(f"   MNQ Contract: {es.get('id')}", 'info')
        else:
            self.log(f"❌ Connection failed: {es}", 'error')
    
    def start_bot(self):
        """Start the trading bot in shadow mode"""
        username = self.username_var.get()
        api_key = self.apikey_var.get()
        
        if not username or not api_key:
            messagebox.showerror("Error", "Please enter username and API key")
            return
        
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("🟢 Running (Shadow Mode)")
        self.log("Starting bot in shadow mode...", 'info')
        
        self.thread = threading.Thread(target=self.run_bot_thread, args=(username, api_key), daemon=True)
        self.thread.start()
    
    def run_bot_thread(self, username, api_key):
        """Bot thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            self.loop.run_until_complete(self.run_bot(username, api_key))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"Error: {e}", 'error'))
        finally:
            self.loop.close()
            self.root.after(0, self.on_bot_stopped)
    
    def on_quote_update(self, quote_data):
        """Handle incoming quote data and build bars from quotes"""
        try:
            bid = quote_data.get('bid') or 0
            ask = quote_data.get('ask') or 0
            last = quote_data.get('last') or 0
            
            # Debug: log that we're receiving callbacks (less spam)
            if not hasattr(self, '_quote_cb_count'):
                self._quote_cb_count = 0
            self._quote_cb_count += 1
            if self._quote_cb_count <= 3 or self._quote_cb_count % 500 == 0:
                print(f"[GUI-QUOTE #{self._quote_cb_count}] bid={bid}, ask={ask}")
            
            # Handle one-sided quotes (common in pre-market)
            if bid or ask:
                from datetime import datetime
                now = datetime.utcnow()
                
                # Calculate mid price - use both if available, otherwise use what we have
                if bid and ask:
                    mid = (bid + ask) / 2
                else:
                    mid = bid or ask
                
                self.current_quote = Quote(bid=bid or mid, ask=ask or mid, last=last, timestamp=now)
                
                # Update strategy with current quote
                if self.strategy:
                    self.strategy.set_quote(self.current_quote)
                
                # === BUILD BARS FROM QUOTES ===
                current_minute = now.replace(second=0, microsecond=0)
                
                # Debug: log bar building progress occasionally
                if now.second == 0 and len(self.quote_bars) < 10:
                    print(f"[QUOTE-BAR] Building bars: {len(self.quote_bars)} complete, current_bar exists: {self.current_bar is not None}")
                
                # Check if we need to start a new bar
                if self.last_bar_minute is None or current_minute > self.last_bar_minute:
                    # Debug: log minute transitions
                    print(f"[BAR-BUILD] New minute! last={self.last_bar_minute}, current={current_minute}, had_bar={self.current_bar is not None}")
                    
                    # Close previous bar if exists
                    if self.current_bar is not None:
                        self.quote_bars.append(self.current_bar)
                        bar_count = len(self.quote_bars)
                        print(f"[BAR-BUILD] Completed bar #{bar_count} @ {self.current_bar['close']:.2f}")
                        # Log when we complete a bar (to GUI)
                        if bar_count <= 10:
                            self.root.after(0, lambda c=bar_count, p=self.current_bar['close']: 
                                self.log(f"📈 Quote bar #{c} complete @ {p:.2f}", 'info'))
                        # Keep only last 30 bars
                        if len(self.quote_bars) > 30:
                            self.quote_bars = self.quote_bars[-30:]
                    
                    # Start new bar
                    self.current_bar = {
                        'timestamp': current_minute,
                        'open': mid,
                        'high': mid,
                        'low': mid,
                        'close': mid,
                        'volume': 0,
                    }
                    self.last_bar_minute = current_minute
                    print(f"[BAR-BUILD] Started new bar for {current_minute}")
                else:
                    # Update current bar
                    if self.current_bar:
                        self.current_bar['high'] = max(self.current_bar['high'], mid)
                        self.current_bar['low'] = min(self.current_bar['low'], mid)
                        self.current_bar['close'] = mid
                
                # Update UI
                self.root.after(0, lambda: self.quote_var.set(
                    f"Bid: {bid:.2f} | Ask: {ask:.2f} | Mid: {mid:.2f}"
                ))
        except Exception as e:
            print(f"[QUOTE-ERROR] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    async def run_bot(self, username, api_key):
        """Main bot loop with quote subscription"""
        self.client = ProjectXClient(username, api_key)
        
        if not await self.client.connect():
            self.root.after(0, lambda: self.log("Failed to connect to ProjectX", 'error'))
            return
        
        self.root.after(0, lambda: self.log("Connected to ProjectX", 'info'))
        
        # Log current time for debugging - compare system vs internet time
        now_utc = datetime.utcnow()
        now_local = datetime.now()
        self.root.after(0, lambda u=now_utc, l=now_local: 
            self.log(f"🕐 System UTC: {u.strftime('%H:%M:%S')} | Local: {l.strftime('%H:%M:%S')}", 'info'))
        
        # Fetch internet time for comparison
        try:
            import urllib.request
            import json as json_module
            with urllib.request.urlopen('http://worldtimeapi.org/api/timezone/America/New_York', timeout=5) as resp:
                time_data = json_module.loads(resp.read().decode())
                internet_time = time_data.get('datetime', '')[:19]  # Just the time part
                self.root.after(0, lambda t=internet_time: 
                    self.log(f"🌐 Internet time (EST): {t}", 'info'))
        except Exception as e:
            self.root.after(0, lambda: self.log("Could not fetch internet time", 'warning'))
        
        # Find ES contract
        es = await self.client.find_mnq_contract()
        if not es:
            self.root.after(0, lambda: self.log("Could not find MNQ contract", 'error'))
            return
        
        self.contract_id = es['id']
        self.root.after(0, lambda: self.log(f"Trading: {es.get('description', self.contract_id)}", 'info'))
        
        # Subscribe to live quotes
        try:
            await self.client.subscribe_quotes(self.contract_id, self.on_quote_update)
            self.root.after(0, lambda: self.log("📡 Subscribed to live quotes", 'info'))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"Quote subscription failed: {e} (using bar data)", 'info'))
        
        # Initialize strategy with current settings (override defaults with GUI values)
        strategy_config = {
            **STRATEGY,
            # Entry
            "lookback_bars": self.lookback_var.get(),
            "channel_lag": self.channel_lag_var.get(),
            "sr_touch_tolerance": self.sr_tolerance_var.get(),
            "retest_tolerance": self.retest_tolerance_var.get(),
            "min_gap_bars": self.min_gap_bars_var.get(),
            # Filters
            "use_ct_filter": self.use_ct_filter_var.get(),
            "ct_bars": self.ct_bars_var.get(),
            "use_trend_filter": self.use_trend_filter_var.get(),
            "trend_lookback": self.trend_lookback_var.get(),
            # Exit
            "stop_pts": self.stop_pts_var.get(),
            "target_pts": self.target_pts_var.get(),
            "max_hold_bars": self.time_exit_var.get(),
            "rsi_period": self.rsi_period_var.get(),
            "rsi_exit_high": self.rsi_exit_high_var.get(),
            "rsi_exit_low": self.rsi_exit_low_var.get(),
            "trail_activation_pts": self.trail_activation_var.get(),
            "trail_distance": self.trail_distance_var.get(),
            # Session
            "trading_windows": self.get_trading_windows(),
            "last_entry_time": self.get_last_entry_time(),
        }
        self.strategy = SRBounceStrategy(strategy_config)
        
        # Log settings
        windows = self.get_trading_windows()
        window_str = ", ".join([f"{w[0].strftime('%H:%M')}-{w[1].strftime('%H:%M')}" for w in windows])
        last_entry = self.get_last_entry_time().strftime('%H:%M')
        self.root.after(0, lambda: self.log(
            f"Strategy: Stop={self.stop_pts_var.get()}pts, Target={self.target_pts_var.get()}pts, "
            f"Lookback={self.lookback_var.get()}, TimeExit={self.time_exit_var.get()} bars", 'info'
        ))
        self.root.after(0, lambda: self.log(
            f"Filters: CT={self.use_ct_filter_var.get()}, Trend={self.use_trend_filter_var.get()}, "
            f"Windows=[{window_str}], LastEntry={last_entry}", 'info'
        ))
        
        # Track last quote time for health monitoring
        last_quote_check = datetime.utcnow()
        last_5min_validation = datetime.utcnow()
        quote_reconnect_attempts = 0
        quote_price_warnings = 0
        
        while self.is_running:
            try:
                # === Quote Health Check ===
                # If no quote update in 30 seconds, try to reconnect
                if self.current_quote and self.current_quote.timestamp:
                    quote_age = (datetime.utcnow() - self.current_quote.timestamp).total_seconds()
                    if quote_age > 30 and quote_reconnect_attempts < 3:
                        self.root.after(0, lambda: self.log(f"⚠️ Quote feed stale ({quote_age:.0f}s) - reconnecting...", 'info'))
                        try:
                            # Re-subscribe to quotes
                            await self.client.subscribe_quotes(self.contract_id, self.on_quote_update)
                            quote_reconnect_attempts += 1
                            self.root.after(0, lambda: self.log("📡 Re-subscribed to quotes", 'info'))
                        except Exception as e:
                            self.root.after(0, lambda e=e: self.log(f"Quote reconnect failed: {e}", 'error'))
                    elif quote_age <= 10:
                        quote_reconnect_attempts = 0  # Reset counter when quotes are flowing
                
                # === Token Refresh Check ===
                # Refresh token if it's getting old (every 20 hours to be safe before 24hr expiry)
                if hasattr(self.client, '_token_time') and self.client._token_time:
                    token_age = (datetime.utcnow() - self.client._token_time).total_seconds()
                    if token_age > 20 * 3600:  # 20 hours
                        self.root.after(0, lambda: self.log("🔄 Refreshing API token...", 'info'))
                        try:
                            await self.client._ensure_token()
                            self.root.after(0, lambda: self.log("✅ Token refreshed", 'info'))
                        except Exception as e:
                            self.root.after(0, lambda e=e: self.log(f"Token refresh failed: {e}", 'error'))
                
                # === 5-MINUTE DATA VALIDATION CHECK ===
                # Every 5 minutes, verify quote price matches recent bar data
                if (datetime.utcnow() - last_5min_validation).total_seconds() > 300:
                    last_5min_validation = datetime.utcnow()
                    if self.current_quote:
                        # Will compare against latest bar below
                        self.root.after(0, lambda: self.log("🔍 Running 5-min data validation...", 'info'))
                
                # Fetch latest bars (completed bars only)
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(minutes=30)
                
                # DEBUG: Log what we're requesting
                self.root.after(0, lambda s=start_time.strftime('%H:%M:%S'), e=end_time.strftime('%H:%M:%S'): 
                    self.log(f"[DEBUG] Requesting bars: {s} to {e} UTC", 'info'))
                
                bars = await self.client.get_bars(
                    self.contract_id,
                    start_time,
                    end_time,
                    unit=2,
                    unit_number=1,
                    limit=30
                )
                
                if bars and len(bars) > 0:
                    last_bar = bars[-1]
                    # DEBUG: Log what ProjectX actually returns
                    raw_ts = last_bar['t']
                    now_utc = datetime.utcnow()
                    self.root.after(0, lambda r=raw_ts, n=now_utc.strftime('%H:%M:%S'): 
                        self.log(f"[DEBUG] Bar ts={r}, now_utc={n}", 'info'))
                    # Parse timestamp and convert to EST for proper window comparison
                    bar_ts_str = last_bar['t'].replace('Z', '+00:00')
                    bar_ts_utc = datetime.fromisoformat(bar_ts_str)
                    bar_ts_est = bar_ts_utc.astimezone(ZoneInfo('America/New_York')).replace(tzinfo=None)
                    bar = {
                        'timestamp': bar_ts_est,
                        'open': float(last_bar['o']),
                        'high': float(last_bar['h']),
                        'low': float(last_bar['l']),
                        'close': float(last_bar['c']),
                        'volume': int(last_bar.get('v', 0)),
                    }
                    
                    # === BAR STALENESS CHECK ===
                    # If bar is stale, use ProjectX bars for HISTORY but quote bar for CURRENT
                    bar_age_seconds = (datetime.utcnow() - bar_ts_utc.replace(tzinfo=None)).total_seconds()
                    
                    if bar_age_seconds > 180:  # 3 minutes stale
                        # First: Seed strategy with ProjectX historical bars (for S/R lookback)
                        if not hasattr(self, '_history_seeded') or not self._history_seeded:
                            self.root.after(0, lambda: self.log(f"📚 Seeding strategy with {len(bars)} historical bars from ProjectX", 'info'))
                            for hist_bar in bars[:-1]:  # All but the last (stale) bar
                                hbar_ts = datetime.fromisoformat(hist_bar['t'].replace('Z', '+00:00'))
                                hbar_est = hbar_ts.astimezone(ZoneInfo('America/New_York')).replace(tzinfo=None)
                                hbar = {
                                    'timestamp': hbar_est,
                                    'open': float(hist_bar['o']),
                                    'high': float(hist_bar['h']),
                                    'low': float(hist_bar['l']),
                                    'close': float(hist_bar['c']),
                                    'volume': int(hist_bar.get('v', 0)),
                                }
                                self.strategy.add_historical_bar(hbar)  # Just add to history, no trading
                            self._history_seeded = True
                        
                        # Now use quote bar for current price action
                        if len(self.quote_bars) >= 1:
                            qbar = self.quote_bars[-1]
                            bar_ts_est = qbar['timestamp'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('America/New_York')).replace(tzinfo=None)
                            bar = {
                                'timestamp': bar_ts_est,
                                'open': qbar['open'],
                                'high': qbar['high'],
                                'low': qbar['low'],
                                'close': qbar['close'],
                                'volume': qbar['volume'],
                            }
                            self.root.after(0, lambda: self.log(f"📊 Using quote bar @ {bar['close']:.2f} (ProjectX stale)", 'info'))
                        else:
                            self.root.after(0, lambda qb=len(self.quote_bars): 
                                self.log(f"⏳ Waiting for first quote bar to complete ({qb}/1)...", 'warning'))
                            await asyncio.sleep(5)
                            continue
                    
                    # === QUOTE vs BAR VALIDATION ===
                    # Check if quote price matches bar data (detects stuck quotes)
                    if self.current_quote:
                        price_diff = abs(self.current_quote.mid - bar['close'])
                        bar_range = bar['high'] - bar['low']
                        # Use larger of 50pts or 2x bar range (handles volatile days like today)
                        threshold = max(50.0, bar_range * 2.0)
                        if price_diff > threshold:  # Significant drift = problem
                            quote_price_warnings += 1
                            self.root.after(0, lambda d=price_diff, q=self.current_quote.mid, b=bar['close']: 
                                self.log(f"⚠️ QUOTE DRIFT: Quote={q:.2f} vs Bar={b:.2f} (diff={d:.2f})", 'error'))
                            
                            if quote_price_warnings >= 3:
                                # Clear the bad quote and force reconnect
                                self.root.after(0, lambda: self.log("🔄 Quote data invalid - clearing and reconnecting...", 'error'))
                                self.current_quote = None
                                if self.strategy:
                                    self.strategy.current_quote = None
                                try:
                                    await self.client.subscribe_quotes(self.contract_id, self.on_quote_update)
                                    quote_price_warnings = 0
                                except Exception as e:
                                    self.root.after(0, lambda e=e: self.log(f"Quote reconnect failed: {e}", 'error'))
                        else:
                            quote_price_warnings = 0  # Reset if quote is valid
                    
                    # Process bar
                    events = self.strategy.on_bar(bar)
                    
                    # Handle events
                    if events.get('stale'):
                        bar_time = bar['timestamp'].strftime('%H:%M:%S')
                        self.root.after(0, lambda bt=bar_time: self.log(f"⏭️ Stale bar skipped ({bt}) - history only, no signals", 'info'))
                    
                    if events['signal']:
                        signal = events['signal']
                        self.signals_count += 1
                        self.root.after(0, lambda s=signal: self.on_signal(s))
                    
                    if events['entry']:
                        trade = events['entry']
                        self.root.after(0, lambda t=trade: self.on_entry(t))
                    
                    if events['exit']:
                        trade = events['exit']
                        self.trades_count += 1
                        self.pnl += trade.pnl_dollars
                        self.root.after(0, lambda t=trade: self.on_exit(t))
                
                # Wait until next minute boundary + 5 seconds for bar to be available
                now = datetime.utcnow()
                seconds_until_next_minute = 60 - now.second
                await asyncio.sleep(seconds_until_next_minute + 5)
                
            except Exception as e:
                self.root.after(0, lambda e=e: self.log(f"Error: {e}", 'error'))
                await asyncio.sleep(10)
        
        await self.client.disconnect()
    
    def on_signal(self, signal):
        self.signals_var.set(f"Signals: {self.signals_count}")
        # Handle direction as enum, string, or int
        direction = signal.direction
        if hasattr(direction, 'value'):
            direction = direction.value
        if hasattr(direction, 'upper'):
            direction = direction.upper()
        else:
            direction = "LONG" if direction == 1 else "SHORT"
        self.log(f"📊 SIGNAL: {direction} at S/R={signal.sr_level:.2f}", 'signal')
    
    def on_entry(self, trade):
        quote_info = ""
        if self.current_quote:
            quote_info = f" (Mid: {self.current_quote.mid:.2f})"
        # Handle direction as enum, string, or int
        direction = trade.direction
        if hasattr(direction, 'value'):
            direction = direction.value
        if hasattr(direction, 'upper'):
            direction = direction.upper()
        else:
            direction = "LONG" if direction == 1 else "SHORT"
        self.log(f"🟢 ENTRY: {direction} @ {trade.entry_price:.2f}{quote_info} "
                f"| Stop: {trade.stop_price:.2f} | Target: {trade.target_price:.2f}", 'entry')
    
    def on_exit(self, trade):
        self.trades_var.set(f"Trades: {self.trades_count}")
        self.pnl_var.set(f"PnL: ${self.pnl:+.2f}")
        
        # Log trade to CSV
        self.log_trade_csv(trade)
        self.session_trades.append(trade)
        
        tag = 'exit_win' if trade.pnl_dollars > 0 else 'exit_loss'
        emoji = "✅" if trade.pnl_dollars > 0 else "❌"
        quote_info = ""
        if trade.exit_reason.value == "time" and self.current_quote:
            quote_info = f" (Mid: {self.current_quote.mid:.2f})"
        self.log(f"{emoji} EXIT: {trade.exit_reason.value.upper()} @ {trade.exit_price:.2f}{quote_info} "
                f"| PnL: ${trade.pnl_dollars:+.2f}", tag)
    
    def log_trade_csv(self, trade):
        """Log individual trade to CSV file"""
        try:
            trade_data = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'entry_time': trade.entry_time.strftime('%Y-%m-%d %H:%M:%S') if trade.entry_time else '',
                'exit_time': trade.exit_time.strftime('%Y-%m-%d %H:%M:%S') if trade.exit_time else '',
                'direction': trade.direction.value,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'stop_price': trade.stop_price,
                'target_price': trade.target_price,
                'sr_level': trade.sr_level,
                'pnl_pts': trade.pnl_pts,
                'pnl_dollars': trade.pnl_dollars,
                'exit_reason': trade.exit_reason.value if trade.exit_reason else '',
                'bars_held': trade.bars_held,
            }
            
            csv_path = os.path.join(self.log_dir, 'trades.csv')
            df = pd.DataFrame([trade_data])
            file_exists = os.path.exists(csv_path)
            df.to_csv(csv_path, mode='a', header=not file_exists, index=False)
        except Exception as e:
            print(f"Error logging trade to CSV: {e}")
    
    def export_daily_summary(self):
        """Export daily summary CSV at end of session"""
        if not self.session_trades:
            return
        
        try:
            date_str = datetime.now().strftime('%Y-%m-%d')
            summary_path = os.path.join(self.log_dir, f'daily_summary_{date_str}.csv')
            
            trades_data = []
            for trade in self.session_trades:
                trades_data.append({
                    'entry_time': trade.entry_time.strftime('%H:%M:%S') if trade.entry_time else '',
                    'exit_time': trade.exit_time.strftime('%H:%M:%S') if trade.exit_time else '',
                    'direction': trade.direction.value,
                    'entry_price': trade.entry_price,
                    'exit_price': trade.exit_price,
                    'sr_level': trade.sr_level,
                    'pnl_pts': trade.pnl_pts,
                    'pnl_dollars': trade.pnl_dollars,
                    'exit_reason': trade.exit_reason.value if trade.exit_reason else '',
                    'bars_held': trade.bars_held,
                })
            
            df = pd.DataFrame(trades_data)
            df.to_csv(summary_path, index=False)
            
            # Also create a stats summary
            stats_path = os.path.join(self.log_dir, f'stats_{date_str}.txt')
            with open(stats_path, 'w') as f:
                f.write(f"DON Futures TopStep - MNQ - Daily Summary\n")
                f.write(f"Date: {date_str}\n")
                f.write(f"{'='*40}\n\n")
                f.write(f"Total Trades: {len(self.session_trades)}\n")
                
                wins = sum(1 for t in self.session_trades if t.pnl_dollars > 0)
                losses = sum(1 for t in self.session_trades if t.pnl_dollars < 0)
                win_rate = wins / len(self.session_trades) * 100 if self.session_trades else 0
                
                f.write(f"Winners: {wins}\n")
                f.write(f"Losers: {losses}\n")
                f.write(f"Win Rate: {win_rate:.1f}%\n\n")
                
                total_pnl = sum(t.pnl_dollars for t in self.session_trades)
                f.write(f"Total PnL: ${total_pnl:+.2f}\n")
                
                # By exit type
                f.write(f"\nBy Exit Type:\n")
                for exit_type in ['target', 'stop', 'time', 'rsi']:
                    type_trades = [t for t in self.session_trades if t.exit_reason and t.exit_reason.value == exit_type]
                    if type_trades:
                        type_pnl = sum(t.pnl_dollars for t in type_trades)
                        f.write(f"  {exit_type.upper()}: {len(type_trades)} trades, ${type_pnl:+.2f}\n")
            
            self.log(f"📁 Daily summary saved: {summary_path}", 'info')
            
        except Exception as e:
            self.log(f"Error exporting daily summary: {e}", 'error')
    
    def stop_bot(self):
        """Stop the trading bot"""
        self.is_running = False
        self.status_var.set("🟡 Stopping...")
        self.log("Stopping bot...", 'info')
    
    def on_bot_stopped(self):
        """Called when bot stops"""
        self.is_running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("⚪ Stopped")
        self.quote_var.set("Quote: --")
        self.log("Bot stopped", 'info')
        
        # Export daily summary CSV
        self.export_daily_summary()
        
        # Print session summary
        if self.strategy:
            stats = self.strategy.get_stats()
            if stats:
                self.log(f"Session: {stats.get('total_trades', 0)} trades, "
                        f"{stats.get('win_rate', 0)*100:.1f}% win rate, "
                        f"${stats.get('total_pnl_dollars', 0):+.2f}", 'info')
    
    def open_logs(self):
        """Open logs folder"""
        log_dir = os.path.join(os.path.dirname(__file__), 'bot', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(log_dir)
        else:
            import subprocess
            subprocess.run(['xdg-open', log_dir])


def main():
    root = tk.Tk()
    app = TradingBotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
