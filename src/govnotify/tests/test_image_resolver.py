import os
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

# Add repo/src to sys.path
sys.path.append(os.path.join(os.getcwd(), "repo", "src"))

from govnotify.processing.image_resolver import ImageResolver
from govnotify.models.source import RawDocument

class TestImageResolver(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.resolver = ImageResolver()
        self.raw_doc = RawDocument(
            source_id="et_top_stories",
            source_url="http://example.com",
            fetch_url="http://example.com/article",
            title="Test Article",
            raw_content="test",
            content_type="text/plain",
            fetched_at=datetime.utcnow(),
            metadata={}
        )

    async def test_resolve_image_tier1_metadata(self):
        self.raw_doc.metadata = {"og:image": "http://example.com/meta.jpg"}
        image_url = await self.resolver.resolve_image(self.raw_doc)
        self.assertEqual(image_url, "http://example.com/meta.jpg")

    async def test_resolve_image_tier2_wikipedia(self):
        # Ensure tier 1 returns None
        self.raw_doc.metadata = {}
        
        # Mock wikipedia search
        with patch.object(self.resolver, '_search_wikipedia_image', new_callable=AsyncMock) as mock_wiki:
            mock_wiki.return_value = "http://wikipedia.org/image.jpg"
            
            image_url = await self.resolver.resolve_image(self.raw_doc, search_query="Test Query")
            
            self.assertEqual(image_url, "http://wikipedia.org/image.jpg")
            mock_wiki.assert_called_once_with("Test Query")

    async def test_resolve_image_tier3_ddg(self):
        # Ensure tier 1 and 2 return None
        self.raw_doc.metadata = {}
        
        with patch.object(self.resolver, '_search_wikipedia_image', new_callable=AsyncMock) as mock_wiki:
            mock_wiki.return_value = None
            
            with patch.object(self.resolver, '_search_duckduckgo_images', new_callable=AsyncMock) as mock_ddg:
                mock_ddg.return_value = "http://ddg.com/image.jpg"
                
                image_url = await self.resolver.resolve_image(self.raw_doc, search_query="Test Query")
                
                self.assertEqual(image_url, "http://ddg.com/image.jpg")
                mock_ddg.assert_called_once()

    async def test_resolve_image_tier4_logo(self):
        # Ensure higher tiers return None
        self.raw_doc.metadata = {}
        self.raw_doc.source_id = "et_top_stories"  # has a bundled logo
        
        with patch.object(self.resolver, '_search_wikipedia_image', new_callable=AsyncMock) as mock_wiki:
            mock_wiki.return_value = None
            with patch.object(self.resolver, '_search_duckduckgo_images', new_callable=AsyncMock) as mock_ddg:
                mock_ddg.return_value = None
                
                image_url = await self.resolver.resolve_image(self.raw_doc, search_query="Test Query")
                
                self.assertEqual(image_url, "/static/logos/et_top_stories.png")

    async def test_search_wikipedia_image_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "query": {
                "pages": {
                    "123": {
                        "original": {"source": "http://wikipedia.org/actual_image.jpg"}
                    }
                }
            }
        }
        
        # Mocking httpx.AsyncClient.get correctly for 'async with'
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            image_url = await self.resolver._search_wikipedia_image("Test Query")
            self.assertEqual(image_url, "http://wikipedia.org/actual_image.jpg")

    async def test_search_wikipedia_image_no_results(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"query": {"pages": {}}}
        
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            image_url = await self.resolver._search_wikipedia_image("Test Query")
            self.assertIsNone(image_url)

if __name__ == '__main__':
    unittest.main()
