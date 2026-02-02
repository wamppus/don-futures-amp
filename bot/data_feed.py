"""
Live Data Feed for DON Futures

Priority order:
1. ProjectX API (primary — real-time quotes + bars)
2. Quote-based synthetic bars (fallback if ProjectX bars stale)
3. Yahoo Finance (backup for testing only)

ALWAYS LOG WHICH SOURCE IS ACTIVE
"""

import os
import time
import json
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass
from threading import Thread, Event
import queue

from .logger import get_logger


@dataclass
class Quote:
    """Real-time quote"""
    bid: float
    ask: float
    last: float
    timestamp: datetime
    source: str
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2
    
    def is_stale(self, max_age_seconds: float = 5.0) -> bool:
        age = (datetime.now() - self.timestamp).total_seconds()
        return age > max_age_seconds


@dataclass
class Bar:
    """OHLCV bar"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }


class ProjectXClient:
    """
    ProjectX API client for live ES data
    
    Endpoints:
    - Auth: POST /api/Auth/loginKey
    - Bars: POST /api/History/retrieveBars
    - Quotes: WebSocket or polling
    """
    
    BASE_URL = "https://api.projectx.com"  # Update with actual URL
    
    def __init__(self, username: str, api_key: str):
        self.username = username
        self.api_key = api_key
        self.token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.logger = get_logger()
        
    def authenticate(self) -> bool:
        """Login and get auth token"""
        try:
            resp = requests.post(
                f"{self.BASE_URL}/api/Auth/loginKey",
                json={"userName": self.username, "apiKey": self.api_key},
                timeout=10
            )
            data = resp.json()
            
            if data.get('success'):
                self.token = data['token']
                self.token_expiry = datetime.now() + timedelta(hours=1)
                self.logger.info(f"ProjectX authenticated as {self.username}")
                return True
            else:
                self.logger.error(f"ProjectX auth failed: {data}")
                return False
                
        except Exception as e:
            self.logger.error(f"ProjectX auth error: {e}")
            return False
    
    def ensure_auth(self) -> bool:
        """Ensure we have valid auth"""
        if self.token and self.token_expiry and datetime.now() < self.token_expiry:
            return True
        return self.authenticate()
    
    def get_bars(self, symbol: str = "F.US.EP", interval: int = 5, 
                 count: int = 100) -> List[Bar]:
        """Fetch historical bars"""
        if not self.ensure_auth():
            return []
        
        try:
            resp = requests.post(
                f"{self.BASE_URL}/api/History/retrieveBars",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "symbolId": symbol,
                    "barInterval": interval,
                    "barCount": count
                },
                timeout=30
            )
            data = resp.json()
            
            if not data.get('success'):
                self.logger.error(f"ProjectX bars failed: {data}")
                return []
            
            bars = []
            for b in data.get('bars', []):
                bars.append(Bar(
                    timestamp=datetime.fromisoformat(b['timestamp']),
                    open=b['open'],
                    high=b['high'],
                    low=b['low'],
                    close=b['close'],
                    volume=b.get('volume', 0),
                    source='projectx'
                ))
            
            self.logger.info(f"ProjectX: received {len(bars)} bars")
            return bars
            
        except Exception as e:
            self.logger.error(f"ProjectX bars error: {e}")
            return []
    
    def get_quote(self, symbol: str = "F.US.EP") -> Optional[Quote]:
        """Get current quote"""
        if not self.ensure_auth():
            return None
        
        try:
            resp = requests.get(
                f"{self.BASE_URL}/api/Quotes/{symbol}",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=5
            )
            data = resp.json()
            
            if data.get('success'):
                return Quote(
                    bid=data['bid'],
                    ask=data['ask'],
                    last=data.get('last', (data['bid'] + data['ask']) / 2),
                    timestamp=datetime.now(),
                    source='projectx'
                )
            return None
            
        except Exception as e:
            self.logger.warning(f"ProjectX quote error: {e}")
            return None


class DataFeed:
    """
    Unified data feed with automatic source selection.
    
    Priority:
    1. ProjectX bars (if fresh)
    2. Quote-based bars (if quotes available)
    3. Fallback source (for testing)
    """
    
    def __init__(self, 
                 projectx_username: str = None,
                 projectx_api_key: str = None,
                 bar_interval_minutes: int = 5,
                 symbol: str = "ES"):
        
        self.logger = get_logger()
        self.bar_interval = bar_interval_minutes
        self.symbol = symbol
        
        # Data sources
        self.projectx: Optional[ProjectXClient] = None
        if projectx_username and projectx_api_key:
            self.projectx = ProjectXClient(projectx_username, projectx_api_key)
        
        # Current state
        self.current_quote: Optional[Quote] = None
        self.current_bar: Optional[Bar] = None
        self.last_bar_time: Optional[datetime] = None
        
        # Bar building from quotes
        self.quote_bar_open: Optional[float] = None
        self.quote_bar_high: float = 0
        self.quote_bar_low: float = float('inf')
        self.quote_bar_start: Optional[datetime] = None
        
        # Callbacks
        self.bar_callbacks: List[Callable[[Bar], None]] = []
        self.quote_callbacks: List[Callable[[Quote], None]] = []
        
        # Control
        self.running = False
        self.stop_event = Event()
        
        self.logger.info(f"DataFeed initialized for {symbol} @ {bar_interval_minutes}min")
        self.logger.info(f"ProjectX: {'ENABLED' if self.projectx else 'DISABLED'}")
    
    def on_bar(self, callback: Callable[[Bar], None]):
        """Register bar callback"""
        self.bar_callbacks.append(callback)
    
    def on_quote(self, callback: Callable[[Quote], None]):
        """Register quote callback"""
        self.quote_callbacks.append(callback)
    
    def _emit_bar(self, bar: Bar):
        """Emit bar to all callbacks"""
        self.logger.info(f"📊 NEW BAR [{bar.source}] {bar.timestamp} O:{bar.open:.2f} H:{bar.high:.2f} L:{bar.low:.2f} C:{bar.close:.2f}")
        for cb in self.bar_callbacks:
            try:
                cb(bar)
            except Exception as e:
                self.logger.error(f"Bar callback error: {e}")
    
    def _emit_quote(self, quote: Quote):
        """Emit quote to all callbacks"""
        self.current_quote = quote
        for cb in self.quote_callbacks:
            try:
                cb(quote)
            except Exception as e:
                self.logger.error(f"Quote callback error: {e}")
    
    def _build_quote_bar(self, quote: Quote) -> Optional[Bar]:
        """Build bar from streaming quotes"""
        now = datetime.now()
        
        # Start new bar?
        if self.quote_bar_start is None:
            self.quote_bar_start = now.replace(second=0, microsecond=0)
            self.quote_bar_open = quote.mid
            self.quote_bar_high = quote.mid
            self.quote_bar_low = quote.mid
            return None
        
        # Update current bar
        self.quote_bar_high = max(self.quote_bar_high, quote.mid)
        self.quote_bar_low = min(self.quote_bar_low, quote.mid)
        
        # Bar complete?
        bar_end = self.quote_bar_start + timedelta(minutes=self.bar_interval)
        if now >= bar_end:
            bar = Bar(
                timestamp=self.quote_bar_start,
                open=self.quote_bar_open,
                high=self.quote_bar_high,
                low=self.quote_bar_low,
                close=quote.mid,
                volume=0,
                source='quote_built'
            )
            
            # Reset for next bar
            self.quote_bar_start = bar_end
            self.quote_bar_open = quote.mid
            self.quote_bar_high = quote.mid
            self.quote_bar_low = quote.mid
            
            return bar
        
        return None
    
    def fetch_historical(self, count: int = 100) -> List[Bar]:
        """Fetch historical bars for warmup"""
        if self.projectx:
            bars = self.projectx.get_bars(count=count)
            if bars:
                self.logger.info(f"Loaded {len(bars)} historical bars from ProjectX")
                return bars
        
        self.logger.warning("No historical data source available")
        return []
    
    def start(self):
        """Start live data feed"""
        self.running = True
        self.stop_event.clear()
        
        self.logger.info("Starting live data feed...")
        
        # Start polling thread
        self.poll_thread = Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()
    
    def stop(self):
        """Stop live data feed"""
        self.running = False
        self.stop_event.set()
        self.logger.info("Data feed stopped")
    
    def _poll_loop(self):
        """Main polling loop"""
        self.logger.info("Poll loop started")
        
        while self.running and not self.stop_event.is_set():
            try:
                # Try ProjectX quote
                if self.projectx:
                    quote = self.projectx.get_quote()
                    if quote:
                        self._emit_quote(quote)
                        
                        # Build bar from quotes
                        bar = self._build_quote_bar(quote)
                        if bar:
                            self._emit_bar(bar)
                
                # Sleep between polls
                self.stop_event.wait(1.0)  # 1 second poll interval
                
            except Exception as e:
                self.logger.error(f"Poll loop error: {e}")
                self.stop_event.wait(5.0)  # Back off on error
        
        self.logger.info("Poll loop ended")
    
    def get_current_quote(self) -> Optional[Quote]:
        """Get most recent quote"""
        return self.current_quote
    
    def is_market_open(self) -> bool:
        """Check if market is open (ES RTH: 9:30-16:00 ET)"""
        now = datetime.now()
        # Simplified check — enhance with proper timezone handling
        if now.weekday() >= 5:  # Weekend
            return False
        
        hour = now.hour
        # Rough RTH check (adjust for your timezone)
        return 9 <= hour < 16


# Convenience function
def create_data_feed(config: Dict[str, Any] = None) -> DataFeed:
    """Create data feed from config or environment"""
    config = config or {}
    
    return DataFeed(
        projectx_username=config.get('projectx_username') or os.getenv('PROJECTX_USERNAME'),
        projectx_api_key=config.get('projectx_api_key') or os.getenv('PROJECTX_API_KEY'),
        bar_interval_minutes=config.get('bar_interval', 5),
        symbol=config.get('symbol', 'ES')
    )
