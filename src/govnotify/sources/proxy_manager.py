"""
Free Proxy Manager.
Fetches and rotates free proxies from public GitHub lists to bypass IP-based blocks.
"""
import asyncio
import random
import time
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# User-suggested high-quality free proxy lists on GitHub
PROXY_LIST_URLS = [
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/all.txt",
]

class ProxyManager:
    """Singleton manager for fetching and rotating free proxies."""
    _instance: Optional['ProxyManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ProxyManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.proxies: list[str] = []
        self.blacklist: dict[str, float] = {} # proxy -> expiry_timestamp
        self.last_fetched: float = 0
        self.fetch_lock = asyncio.Lock()
        self._initialized = True

    async def get_proxy(self, force_refresh: bool = False) -> Optional[str]:
        """Get a random proxy, fetching if list is empty or old (1 hour)."""
        async with self.fetch_lock:
            # Refresh if empty or older than 1 hour
            if not self.proxies or force_refresh or (time.time() - self.last_fetched > 3600):
                await self._fetch_proxies()
            
            if not self.proxies:
                return None
                
            return random.choice(self.proxies)

    async def mark_bad_proxy(self, proxy: str):
        """Remove a proxy from the list and blacklist it for 24 hours."""
        async with self.fetch_lock:
            if proxy in self.proxies:
                self.proxies.remove(proxy)
            
            # Blacklist for 24 hours
            self.blacklist[proxy] = time.time() + 86400
            logger.info("proxy_manager_blacklisted_proxy", proxy=proxy, remaining=len(self.proxies), blacklist_size=len(self.blacklist))

    async def _fetch_proxies(self):
        """Fetch proxies from multiple sources in parallel."""
        logger.info("proxy_manager_fetching_start")
        
        # Clean up expired blacklist items
        now = time.time()
        self.blacklist = {p: expiry for p, expiry in self.blacklist.items() if expiry > now}
        
        all_proxies = set()
        
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            tasks = [self._fetch_source(client, url) for url in PROXY_LIST_URLS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list):
                    all_proxies.update(result)
        
        # Filter out blacklisted proxies
        self.proxies = [p for p in all_proxies if p not in self.blacklist]
        self.last_fetched = time.time()
        logger.info("proxy_manager_fetching_complete", count=len(self.proxies), blacklisted_filtered=len(all_proxies) - len(self.proxies))

    async def _fetch_source(self, client: httpx.AsyncClient, url: str) -> list[str]:
        """Fetch and parse a single proxy list URL."""
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            
            lines = resp.text.splitlines()
            proxies = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Basic validation for IP:PORT or scheme://IP:PORT
                if ":" in line:
                    # Determine scheme from URL or line content
                    scheme = "http"
                    if "socks5" in url.lower() or "socks5" in line.lower():
                        scheme = "socks5"
                    elif "socks4" in url.lower() or "socks4" in line.lower():
                        continue
                    
                    proxy = line
                    if "://" not in proxy:
                        proxy = f"{scheme}://{line}"
                    proxies.append(proxy)
            
            return proxies
        except Exception as exc:
            logger.warning("proxy_source_fetch_failed", url=url, error=str(exc))
            return []

# Export a global instance
proxy_manager = ProxyManager()
