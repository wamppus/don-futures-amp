"""
ProjectX API Client for TopstepX
Handles authentication, market data, and order execution
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass
from enum import IntEnum
import os

# Optional: SignalR for real-time data
try:
    from signalrcore.hub_connection_builder import HubConnectionBuilder
    HAS_SIGNALR = True
except ImportError:
    HAS_SIGNALR = False

logger = logging.getLogger(__name__)


class OrderType(IntEnum):
    LIMIT = 1
    MARKET = 2
    STOP = 4
    TRAILING_STOP = 5
    JOIN_BID = 6
    JOIN_ASK = 7


class OrderSide(IntEnum):
    BID = 0  # Buy
    ASK = 1  # Sell


@dataclass
class Position:
    account_id: int
    contract_id: str
    size: int
    avg_price: float
    unrealized_pnl: float


@dataclass
class Order:
    order_id: str
    account_id: int
    contract_id: str
    side: OrderSide
    order_type: OrderType
    size: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    status: str = "pending"


class ProjectXClient:
    """
    Async client for ProjectX Gateway API (TopstepX)
    
    Usage:
        client = ProjectXClient(username, api_key)
        await client.connect()
        
        # Get accounts
        accounts = await client.get_accounts()
        
        # Place order
        order = await client.place_order(
            account_id=123,
            contract_id="CON.F.US.EP.H25",  # ES March 2025
            side=OrderSide.BID,
            order_type=OrderType.MARKET,
            size=1
        )
        
        # Stream real-time quotes
        await client.subscribe_quotes("CON.F.US.EP.H25", on_quote)
    """
    
    # TopstepX Production URLs
    BASE_URL = "https://api.topstepx.com"
    DEMO_URL = "https://gateway-api-demo.s2f.projectx.com"
    USER_HUB = "https://rtc.topstepx.com/hubs/user"
    MARKET_HUB = "https://rtc.topstepx.com/hubs/market"
    
    def __init__(
        self,
        username: str,
        api_key: str,
        base_url: Optional[str] = None,
    ):
        self.username = username
        self.api_key = api_key
        self.base_url = base_url or self.BASE_URL
        
        self.token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self._token_time: Optional[datetime] = None  # When token was last refreshed
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Real-time connections
        self.user_hub = None
        self.market_hub = None
        
        # Callbacks
        self._quote_callbacks: Dict[str, List[Callable]] = {}
        self._order_callbacks: List[Callable] = []
        self._position_callbacks: List[Callable] = []
        
    async def connect(self) -> bool:
        """Initialize connection and authenticate"""
        self.session = aiohttp.ClientSession()
        
        try:
            await self._authenticate()
            logger.info(f"ProjectX: Connected as {self.username}")
            return True
        except Exception as e:
            logger.error(f"ProjectX: Connection failed - {e}")
            return False
    
    async def disconnect(self):
        """Clean up connections"""
        if self.user_hub:
            await self._stop_hub(self.user_hub)
        if self.market_hub:
            await self._stop_hub(self.market_hub)
        if self.session:
            await self.session.close()
    
    async def _authenticate(self):
        """Authenticate and get JWT token"""
        url = f"{self.base_url}/api/Auth/loginKey"
        payload = {
            "userName": self.username,
            "apiKey": self.api_key
        }
        
        async with self.session.post(url, json=payload) as resp:
            data = await resp.json()
            
            if not data.get("success"):
                raise Exception(f"Auth failed: {data.get('errorMessage')}")
            
            self.token = data["token"]
            self.token_expires = datetime.now() + timedelta(hours=23)
            self._token_time = datetime.utcnow()
            logger.debug("ProjectX: Authenticated successfully")
    
    async def _ensure_token(self):
        """Refresh token if expired"""
        if not self.token or datetime.now() >= self.token_expires:
            await self._validate_session()
    
    async def _validate_session(self):
        """Validate/refresh session token"""
        url = f"{self.base_url}/api/Auth/validate"
        headers = {"Authorization": f"Bearer {self.token}"}
        
        async with self.session.post(url, headers=headers) as resp:
            data = await resp.json()
            
            if data.get("success") and data.get("newToken"):
                self.token = data["newToken"]
                self.token_expires = datetime.now() + timedelta(hours=23)
                self._token_time = datetime.utcnow()
            else:
                # Re-authenticate
                await self._authenticate()
    
    def _headers(self) -> dict:
        """Get auth headers"""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    # =========================================================================
    # ACCOUNT OPERATIONS
    # =========================================================================
    
    async def get_accounts(self) -> List[dict]:
        """Get all trading accounts"""
        await self._ensure_token()
        url = f"{self.base_url}/api/Account/search"
        
        async with self.session.post(url, headers=self._headers(), json={}) as resp:
            data = await resp.json()
            return data.get("accounts", [])
    
    async def get_account_balance(self, account_id: int) -> dict:
        """Get account balance info"""
        await self._ensure_token()
        url = f"{self.base_url}/api/Account/balance"
        
        try:
            async with self.session.post(
                url,
                headers=self._headers(),
                json={"accountId": account_id}
            ) as resp:
                if resp.status == 404:
                    return {}
                return await resp.json()
        except Exception as e:
            logger.warning(f"Balance fetch failed: {e}")
            return {}
    
    # =========================================================================
    # MARKET DATA
    # =========================================================================
    
    async def get_contracts(self, live: bool = False) -> List[dict]:
        """Get available contracts"""
        await self._ensure_token()
        url = f"{self.base_url}/api/Contract/available"
        
        async with self.session.post(
            url,
            headers=self._headers(),
            json={"live": live}
        ) as resp:
            data = await resp.json()
            return data.get("contracts", [])
    
    async def find_es_contract(self, live: bool = False) -> Optional[dict]:
        """Find the active ES (E-mini S&P 500) contract"""
        contracts = await self.get_contracts(live)
        
        for c in contracts:
            # ES contracts have symbolId like "F.US.EP" (E-mini S&P)
            if c.get("symbolId") == "F.US.EP" and c.get("activeContract"):
                return c
        
        return None
    
    async def find_mnq_contract(self, live: bool = False) -> Optional[dict]:
        """Find the active MNQ (Micro Nasdaq) contract"""
        contracts = await self.get_contracts(live)
        
        for c in contracts:
            # MNQ contracts have symbolId like "F.US.ENQ" (Micro E-mini Nasdaq)
            if c.get("symbolId") == "F.US.ENQ" and c.get("activeContract"):
                return c
        
        # Fallback: try to find any NQ contract
        for c in contracts:
            if "ENQ" in c.get("symbolId", "") or "NQ" in c.get("id", "").upper():
                return c
        
        return None
    
    async def get_bars(
        self,
        contract_id: str,
        start_time: datetime,
        end_time: datetime,
        unit: int = 2,  # 2 = Minute
        unit_number: int = 1,
        limit: int = 1000,
        live: bool = False
    ) -> List[dict]:
        """
        Get historical OHLCV bars
        
        unit: 1=Second, 2=Minute, 3=Hour, 4=Day, 5=Week, 6=Month
        """
        await self._ensure_token()
        url = f"{self.base_url}/api/History/retrieveBars"
        
        payload = {
            "contractId": contract_id,
            "live": live,
            "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unit": unit,
            "unitNumber": unit_number,
            "limit": limit,
            "includePartialBar": False
        }
        
        async with self.session.post(url, headers=self._headers(), json=payload) as resp:
            data = await resp.json()
            
            # Check for API error
            if data.get("success") == False:
                print(f"[BARS-API] API Error for {contract_id}: code={data.get('errorCode')}, msg={data.get('errorMessage')}")
                return []
            
            bars = data.get("bars") or []
            if not bars:
                print(f"[BARS-API] No bars for {contract_id} ({start_time} to {end_time})")
            return bars
    
    # =========================================================================
    # ORDER OPERATIONS
    # =========================================================================
    
    async def place_order(
        self,
        account_id: int,
        contract_id: str,
        side: OrderSide,
        order_type: OrderType,
        size: int,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        stop_loss_ticks: Optional[int] = None,
        take_profit_ticks: Optional[int] = None,
        custom_tag: Optional[str] = None,
    ) -> dict:
        """
        Place an order
        
        Returns order response with orderId
        """
        await self._ensure_token()
        url = f"{self.base_url}/api/Order/place"
        
        payload = {
            "accountId": account_id,
            "contractId": contract_id,
            "type": int(order_type),
            "side": int(side),
            "size": size,
        }
        
        if limit_price is not None:
            payload["limitPrice"] = limit_price
        if stop_price is not None:
            payload["stopPrice"] = stop_price
        if custom_tag:
            payload["customTag"] = custom_tag
        
        # Bracket orders
        if stop_loss_ticks:
            payload["stopLossBracket"] = {
                "ticks": stop_loss_ticks,
                "type": int(OrderType.STOP)
            }
        if take_profit_ticks:
            payload["takeProfitBracket"] = {
                "ticks": take_profit_ticks,
                "type": int(OrderType.LIMIT)
            }
        
        async with self.session.post(url, headers=self._headers(), json=payload) as resp:
            data = await resp.json()
            
            if not data.get("success", True):
                logger.error(f"Order failed: {data.get('errorMessage')}")
            
            return data
    
    async def cancel_order(self, account_id: int, order_id: str) -> dict:
        """Cancel an order"""
        await self._ensure_token()
        url = f"{self.base_url}/api/Order/cancel"
        
        payload = {
            "accountId": account_id,
            "orderId": order_id
        }
        
        async with self.session.post(url, headers=self._headers(), json=payload) as resp:
            return await resp.json()
    
    async def cancel_all_orders(self, account_id: int) -> dict:
        """Cancel all open orders for account"""
        await self._ensure_token()
        url = f"{self.base_url}/api/Order/cancelAllOrders"
        
        async with self.session.post(
            url,
            headers=self._headers(),
            json={"accountId": account_id}
        ) as resp:
            return await resp.json()
    
    async def get_open_orders(self, account_id: int) -> List[dict]:
        """Get open orders for account"""
        await self._ensure_token()
        url = f"{self.base_url}/api/Order/searchOpen"
        
        async with self.session.post(
            url,
            headers=self._headers(),
            json={"accountId": account_id}
        ) as resp:
            data = await resp.json()
            return data.get("orders", [])
    
    # =========================================================================
    # POSITION OPERATIONS
    # =========================================================================
    
    async def get_positions(self, account_id: int) -> List[dict]:
        """Get open positions for account"""
        await self._ensure_token()
        url = f"{self.base_url}/api/Position/searchOpen"
        
        async with self.session.post(
            url,
            headers=self._headers(),
            json={"accountId": account_id}
        ) as resp:
            data = await resp.json()
            return data.get("positions", [])
    
    async def close_position(
        self,
        account_id: int,
        contract_id: str,
        size: Optional[int] = None
    ) -> dict:
        """Close a position (market order opposite direction)"""
        positions = await self.get_positions(account_id)
        
        for pos in positions:
            if pos.get("contractId") == contract_id:
                pos_size = pos.get("size", 0)
                close_size = size or abs(pos_size)
                
                # Opposite side
                if pos_size > 0:
                    side = OrderSide.ASK  # Sell to close long
                else:
                    side = OrderSide.BID  # Buy to close short
                
                return await self.place_order(
                    account_id=account_id,
                    contract_id=contract_id,
                    side=side,
                    order_type=OrderType.MARKET,
                    size=close_size
                )
        
        return {"success": False, "errorMessage": "No position found"}
    
    # =========================================================================
    # REAL-TIME DATA (SignalR WebSocket)
    # =========================================================================
    
    async def start_realtime(self):
        """Start real-time data connections"""
        if not HAS_SIGNALR:
            logger.warning("signalrcore not installed - real-time data unavailable")
            logger.warning("Install with: pip install signalrcore")
            return
        
        await self._ensure_token()
        
        # Market data hub - per ProjectX docs, need skipNegotiation for WebSocket
        self.market_hub = HubConnectionBuilder()\
            .with_url(
                f"{self.MARKET_HUB}?access_token={self.token}",
                options={
                    "access_token_factory": lambda: self.token,
                    "skip_negotiation": True,  # Required per docs
                }
            )\
            .with_automatic_reconnect({
                "type": "raw",
                "keep_alive_interval": 10,
                "reconnect_interval": 5,
            })\
            .build()
        
        # Register handlers - per docs, events are GatewayQuote/GatewayDepth
        self.market_hub.on("GatewayQuote", self._on_quote)
        self.market_hub.on("GatewayDepth", self._on_depth)
        
        self.market_hub.start()
        logger.info("ProjectX: Real-time market hub connected")
    
    async def subscribe_quotes(
        self,
        contract_id: str,
        callback: Callable[[dict], None]
    ):
        """Subscribe to real-time quotes for a contract"""
        if not self.market_hub:
            await self.start_realtime()
        
        if not self.market_hub:
            logger.warning("Real-time quotes unavailable - market_hub not initialized")
            return
        
        if contract_id not in self._quote_callbacks:
            self._quote_callbacks[contract_id] = []
            
            # Subscribe on hub - per ProjectX SDK, use SubscribeContractQuotes
            self.market_hub.send("SubscribeContractQuotes", [contract_id])
            logger.info(f"ProjectX: Subscribed to quotes for {contract_id}")
        
        self._quote_callbacks[contract_id].append(callback)
    
    def _on_quote(self, *args):
        """Handle incoming quote data - GatewayQuote per ProjectX docs
        
        Data format from SignalR: [contract_id_string, {quote_dict}]
        """
        try:
            data = args[0] if args else None
            if not data or not isinstance(data, list) or len(data) < 2:
                print(f"[QUOTE DEBUG] Invalid data format: {data}")
                return
            
            # Format: [contract_id, quote_dict]
            contract_id = data[0]  # e.g., 'CON.F.US.EP.H26'
            quote = data[1]        # e.g., {'symbol': 'F.US.EP', 'bestBid': 7016.75, ...}
            
            # Debug: show every 10th quote to confirm flow
            import random
            if random.random() < 0.1:
                print(f"[QUOTE] {contract_id}: Bid={quote.get('bestBid')} Ask={quote.get('bestAsk')}")
            
            if not isinstance(quote, dict):
                return
            
            # Find callbacks for this contract - try exact match first, then partial match
            callbacks = self._quote_callbacks.get(contract_id, [])
            
            # If no exact match, try partial matching (handles CON. prefix differences)
            if not callbacks:
                for registered_id, cbs in self._quote_callbacks.items():
                    # Match if one contains the other (e.g., "CON.F.US.ENQ.H26" vs "F.US.ENQ.H26")
                    if registered_id in contract_id or contract_id in registered_id:
                        callbacks = cbs
                        # Debug: log the mismatch so we know
                        print(f"[QUOTE-CB] ID mismatch - registered: {registered_id}, incoming: {contract_id}")
                        break
            
            if not callbacks:
                # Only log occasionally to avoid spam
                if random.random() < 0.01:
                    print(f"[QUOTE-CB] No callbacks for {contract_id}, registered: {list(self._quote_callbacks.keys())}")
                return
            
            # Parse quote data
            parsed = {
                "contract_id": contract_id,
                "bid": quote.get("bestBid"),
                "ask": quote.get("bestAsk"),
                "last": quote.get("lastPrice"),
                "volume": quote.get("volume"),
                "timestamp": quote.get("timestamp"),
            }
            
            # Call registered callbacks
            for cb in callbacks:
                try:
                    cb(parsed)
                except Exception as e:
                    logger.error(f"Quote callback error: {e}")
                    
        except Exception as e:
            logger.error(f"Quote parse error: {e}")
    
    def _on_depth(self, data):
        """Handle depth/L2 data"""
        # TODO: Implement if needed
        pass
    
    async def _stop_hub(self, hub):
        """Stop a SignalR hub"""
        try:
            hub.stop()
        except:
            pass


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def create_client_from_env() -> ProjectXClient:
    """Create client from environment variables"""
    username = os.environ.get("PROJECTX_USERNAME")
    api_key = os.environ.get("PROJECTX_API_KEY")
    
    if not username or not api_key:
        raise ValueError(
            "Set PROJECTX_USERNAME and PROJECTX_API_KEY environment variables"
        )
    
    client = ProjectXClient(username, api_key)
    await client.connect()
    return client


# =============================================================================
# TEST
# =============================================================================

async def test_connection():
    """Test ProjectX connection"""
    import os
    
    username = os.environ.get("PROJECTX_USERNAME")
    api_key = os.environ.get("PROJECTX_API_KEY")
    
    if not username or not api_key:
        print("Set PROJECTX_USERNAME and PROJECTX_API_KEY to test")
        return
    
    client = ProjectXClient(username, api_key)
    
    if await client.connect():
        print("✅ Connected to ProjectX")
        
        # Get accounts
        accounts = await client.get_accounts()
        print(f"\n📊 Accounts: {len(accounts)}")
        for acc in accounts:
            print(f"  - {acc.get('name')} (ID: {acc.get('id')})")
        
        # Find ES contract
        es = await client.find_es_contract()
        if es:
            print(f"\n📈 ES Contract: {es.get('id')} - {es.get('description')}")
        
        # Get recent bars
        if es:
            from datetime import datetime, timedelta
            bars = await client.get_bars(
                es["id"],
                datetime.now() - timedelta(hours=2),
                datetime.now(),
                limit=10
            )
            print(f"\n🕐 Recent bars: {len(bars)}")
            if bars:
                last = bars[-1]
                print(f"  Last: O={last.get('o')} H={last.get('h')} L={last.get('l')} C={last.get('c')}")
        
        await client.disconnect()
        print("\n✅ Test complete")
    else:
        print("❌ Connection failed")


if __name__ == "__main__":
    asyncio.run(test_connection())
