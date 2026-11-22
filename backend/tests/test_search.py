import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services.search import SearchUnavailable, _SEARCH_CACHE, search_via_mcp


class SearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _SEARCH_CACHE.clear()

    async def test_repeated_query_uses_cache(self):
        with patch('app.services.search.settings.MINIMAX_SEARCH_API_KEY', 'test-search-key'), \
             patch('app.services.search._search_once', new=AsyncMock(return_value=[{'title': '结果'}])) as search:
            first = await search_via_mcp('学而思 新东方 单课时价格', 3)
            second = await search_via_mcp('学而思 新东方 单课时价格', 3)
        self.assertEqual(first, second)
        self.assertEqual(search.await_count, 1)

    async def test_search_timeout_is_bounded_and_safe(self):
        with patch('app.services.search.settings.MINIMAX_SEARCH_API_KEY', 'test-search-key'), \
             patch('app.services.search._search_once', new=AsyncMock(side_effect=asyncio.TimeoutError())):
            with self.assertRaises(SearchUnavailable) as error:
                await search_via_mcp('测试超时查询', 3)
        self.assertIn('超时', str(error.exception))



if __name__ == '__main__':
    unittest.main()
