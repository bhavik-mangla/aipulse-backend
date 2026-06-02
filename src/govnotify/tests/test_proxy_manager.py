import asyncio
import time
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add repo/src to sys.path
sys.path.append(os.path.join(os.getcwd(), "repo", "src"))

from govnotify.sources.proxy_manager import ProxyManager

class TestProxyManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Reset the singleton instance for each test
        ProxyManager._instance = None
        self.pm = ProxyManager()

    async def test_singleton(self):
        pm2 = ProxyManager()
        self.assertIs(self.pm, pm2)

    async def test_blacklisting(self):
        # Setup initial proxies
        self.pm.proxies = ["http://proxy1:80", "http://proxy2:80"]
        
        # Mark proxy1 as bad
        await self.pm.mark_bad_proxy("http://proxy1:80")
        
        self.assertEqual(len(self.pm.proxies), 1)
        self.assertIn("http://proxy1:80", self.pm.blacklist)
        self.assertEqual(self.pm.proxies[0], "http://proxy2:80")

    @patch('httpx.AsyncClient.get')
    async def test_fetch_filters_blacklist(self, mock_get):
        # Mock response for a proxy list
        mock_resp = MagicMock()
        mock_resp.text = "http://bad-proxy:80\nhttp://good-proxy:80"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        
        # Blacklist the bad proxy
        await self.pm.mark_bad_proxy("http://bad-proxy:80")
        
        # Trigger fetch
        await self.pm._fetch_proxies()
        
        self.assertIn("http://good-proxy:80", self.pm.proxies)
        self.assertNotIn("http://bad-proxy:80", self.pm.proxies)
        self.assertEqual(len(self.pm.proxies), 1)

    async def test_blacklist_expiry(self):
        # Add to blacklist with a very short expiry (manually)
        self.pm.blacklist["http://expired:80"] = time.time() - 1
        self.pm.blacklist["http://active:80"] = time.time() + 100
        
        # Fetching should trigger cleanup
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_resp = MagicMock()
            mock_resp.text = "http://expired:80\nhttp://active:80"
            mock_get.return_value = mock_resp
            await self.pm._fetch_proxies()
        
        # http://expired:80 should be back in proxies because it was removed from blacklist
        self.assertIn("http://expired:80", self.pm.proxies)
        # http://active:80 should NOT be in proxies because it's still blacklisted
        self.assertNotIn("http://active:80", self.pm.proxies)

if __name__ == '__main__':
    unittest.main()
