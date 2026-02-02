"""
Comprehensive Logging System for DON Futures

Logs EVERYTHING:
- All bars received
- All channel calculations  
- All signal detections (including non-triggered)
- All entries and exits
- All position state changes
- All trail stop updates
- Performance metrics

Multiple output formats:
- Console (colored, real-time)
- Daily log files (human readable)
- JSONL files (machine readable, for analysis)
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, asdict
import sys


class ColorFormatter(logging.Formatter):
    """Colored console output"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'
    }
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        record.msg = f"{color}{record.msg}{reset}"
        return super().format(record)


@dataclass
class LogEntry:
    """Structured log entry for JSONL output"""
    timestamp: str
    event_type: str
    data: Dict[str, Any]
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class DonFuturesLogger:
    """
    Central logging hub for DON Futures strategy
    
    Usage:
        logger = DonFuturesLogger("logs")
        logger.bar("2024-01-01 09:30:00", 4500.0, 4502.0, 4498.0, 4501.0)
        logger.signal("failed_test", "long", 4500.0, "price reclaimed channel")
        logger.entry("long", 4501.0, 4497.0, 4505.0)
        logger.exit("long", 4504.0, 3.0, "trail_stop")
    """
    
    def __init__(self, log_dir: str = "logs", console_level: str = "INFO"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Daily log file
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_log = self.log_dir / f"don_futures_{today}.log"
        
        # JSONL files for structured data
        self.trades_file = self.log_dir / "trades.jsonl"
        self.signals_file = self.log_dir / "signals.jsonl"
        self.bars_file = self.log_dir / f"bars_{today}.jsonl"
        self.state_file = self.log_dir / "state.jsonl"
        
        # Set up Python logger
        self.logger = logging.getLogger("don_futures")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []  # Clear existing handlers
        
        # Console handler (colored)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(getattr(logging, console_level.upper()))
        console.setFormatter(ColorFormatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        ))
        self.logger.addHandler(console)
        
        # File handler (detailed)
        file_handler = logging.FileHandler(self.daily_log)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self.logger.addHandler(file_handler)
        
        # Session stats
        self.session_start = datetime.now()
        self.stats = {
            'bars_received': 0,
            'signals_generated': 0,
            'entries': 0,
            'exits': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl_pts': 0.0
        }
        
        self.info(f"=== DON FUTURES LOGGER INITIALIZED ===")
        self.info(f"Log directory: {self.log_dir.absolute()}")
        self.info(f"Daily log: {self.daily_log}")
    
    def _write_jsonl(self, filepath: Path, entry: LogEntry):
        """Append to JSONL file"""
        with open(filepath, 'a') as f:
            f.write(entry.to_json() + '\n')
    
    def _now(self) -> str:
        return datetime.now().isoformat()
    
    # === Core logging methods ===
    
    def debug(self, msg: str):
        self.logger.debug(msg)
    
    def info(self, msg: str):
        self.logger.info(msg)
    
    def warning(self, msg: str):
        self.logger.warning(msg)
    
    def error(self, msg: str):
        self.logger.error(msg)
    
    def critical(self, msg: str):
        self.logger.critical(msg)
    
    # === Strategy-specific logging ===
    
    def bar(self, timestamp: str, o: float, h: float, l: float, c: float, 
            volume: float = 0, source: str = "unknown"):
        """Log received bar"""
        self.stats['bars_received'] += 1
        
        self.debug(f"BAR [{source}] {timestamp} O:{o:.2f} H:{h:.2f} L:{l:.2f} C:{c:.2f}")
        
        self._write_jsonl(self.bars_file, LogEntry(
            timestamp=self._now(),
            event_type="bar",
            data={
                "bar_time": timestamp,
                "open": o, "high": h, "low": l, "close": c,
                "volume": volume,
                "source": source
            }
        ))
    
    def channel(self, ch_high: float, ch_low: float, period: int):
        """Log channel calculation"""
        self.debug(f"CHANNEL [{period}bar] High:{ch_high:.2f} Low:{ch_low:.2f} Range:{ch_high-ch_low:.2f}")
    
    def break_detected(self, direction: str, level: float, price: float):
        """Log when price breaks channel"""
        self.info(f">>> BREAK DETECTED: {direction.upper()} through {level:.2f} (price: {price:.2f})")
        
        self._write_jsonl(self.signals_file, LogEntry(
            timestamp=self._now(),
            event_type="break_detected",
            data={"direction": direction, "level": level, "price": price}
        ))
    
    def signal(self, signal_type: str, direction: str, price: float, 
               reason: str, triggered: bool = True):
        """Log signal generation"""
        self.stats['signals_generated'] += 1
        
        emoji = "🎯" if triggered else "⏸️"
        status = "TRIGGERED" if triggered else "PENDING"
        
        self.info(f"{emoji} SIGNAL [{signal_type.upper()}] {direction.upper()} @ {price:.2f} - {reason} [{status}]")
        
        self._write_jsonl(self.signals_file, LogEntry(
            timestamp=self._now(),
            event_type="signal",
            data={
                "signal_type": signal_type,
                "direction": direction,
                "price": price,
                "reason": reason,
                "triggered": triggered
            }
        ))
    
    def entry(self, direction: str, entry_type: str, price: float, 
              stop: float, target: float, reason: str):
        """Log trade entry"""
        self.stats['entries'] += 1
        
        self.info(f"")
        self.info(f"{'='*50}")
        self.info(f"[+] ENTRY: {direction.upper()} [{entry_type}] @ {price:.2f}")
        self.info(f"   Stop: {stop:.2f} | Target: {target:.2f}")
        self.info(f"   Reason: {reason}")
        self.info(f"{'='*50}")
        
        self._write_jsonl(self.trades_file, LogEntry(
            timestamp=self._now(),
            event_type="entry",
            data={
                "direction": direction,
                "entry_type": entry_type,
                "price": price,
                "stop": stop,
                "target": target,
                "reason": reason
            }
        ))
    
    def trail_update(self, old_stop: float, new_stop: float, current_price: float):
        """Log trailing stop update"""
        self.info(f"📈 TRAIL UPDATE: {old_stop:.2f} → {new_stop:.2f} (price: {current_price:.2f})")
        
        self._write_jsonl(self.state_file, LogEntry(
            timestamp=self._now(),
            event_type="trail_update",
            data={
                "old_stop": old_stop,
                "new_stop": new_stop,
                "current_price": current_price
            }
        ))
    
    def exit(self, direction: str, entry_type: str, entry_price: float,
             exit_price: float, pnl_pts: float, pnl_dollars: float, reason: str):
        """Log trade exit"""
        self.stats['exits'] += 1
        self.stats['total_pnl_pts'] += pnl_pts
        
        if pnl_pts > 0:
            self.stats['wins'] += 1
            emoji = "✅"
        else:
            self.stats['losses'] += 1
            emoji = "❌"
        
        self.info(f"")
        self.info(f"{'='*50}")
        self.info(f"{emoji} EXIT: {direction.upper()} [{entry_type}] @ {exit_price:.2f}")
        self.info(f"   Entry: {entry_price:.2f} | P&L: {pnl_pts:+.2f} pts (${pnl_dollars:+,.0f})")
        self.info(f"   Reason: {reason}")
        self.info(f"   Session: {self.stats['wins']}W / {self.stats['losses']}L | Total: {self.stats['total_pnl_pts']:+.1f} pts")
        self.info(f"{'='*50}")
        
        self._write_jsonl(self.trades_file, LogEntry(
            timestamp=self._now(),
            event_type="exit",
            data={
                "direction": direction,
                "entry_type": entry_type,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_pts": pnl_pts,
                "pnl_dollars": pnl_dollars,
                "reason": reason,
                "session_wins": self.stats['wins'],
                "session_losses": self.stats['losses'],
                "session_pnl": self.stats['total_pnl_pts']
            }
        ))
    
    def position_state(self, in_position: bool, direction: str = None,
                       entry_price: float = None, current_stop: float = None,
                       unrealized_pnl: float = None):
        """Log position state (call periodically)"""
        if in_position:
            self.debug(f"POSITION: {direction.upper()} @ {entry_price:.2f} | Stop: {current_stop:.2f} | P&L: {unrealized_pnl:+.2f} pts")
        else:
            self.debug("POSITION: FLAT")
        
        self._write_jsonl(self.state_file, LogEntry(
            timestamp=self._now(),
            event_type="position_state",
            data={
                "in_position": in_position,
                "direction": direction,
                "entry_price": entry_price,
                "current_stop": current_stop,
                "unrealized_pnl": unrealized_pnl
            }
        ))
    
    def session_summary(self):
        """Log end-of-session summary"""
        duration = datetime.now() - self.session_start
        
        self.info(f"")
        self.info(f"{'='*60}")
        self.info(f"SESSION SUMMARY")
        self.info(f"{'='*60}")
        self.info(f"Duration: {duration}")
        self.info(f"Bars received: {self.stats['bars_received']}")
        self.info(f"Signals generated: {self.stats['signals_generated']}")
        self.info(f"Trades: {self.stats['entries']} entries, {self.stats['exits']} exits")
        self.info(f"Results: {self.stats['wins']}W / {self.stats['losses']}L")
        if self.stats['exits'] > 0:
            wr = self.stats['wins'] / self.stats['exits'] * 100
            self.info(f"Win Rate: {wr:.1f}%")
        self.info(f"Total P&L: {self.stats['total_pnl_pts']:+.1f} pts (${self.stats['total_pnl_pts']*50:+,.0f})")
        self.info(f"{'='*60}")


# Singleton for easy access
_logger: Optional[DonFuturesLogger] = None

def get_logger(log_dir: str = "logs") -> DonFuturesLogger:
    global _logger
    if _logger is None:
        _logger = DonFuturesLogger(log_dir)
    return _logger
