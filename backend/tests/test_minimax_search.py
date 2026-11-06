import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from app.services.search import search_via_mcp, SearchUnavailable

class MiniMaxSearchTests(unittest.IsolatedAsyncioTestCase):
    async def run_search(self, payload=None, status=200, key='test-key'):
        self.requests = []
        def handler(request):
            self.requests.append(request)
            return httpx.Response(status, json=payload)
        original = httpx.AsyncClient
        settings = SimpleNamespace(MINIMAX_SEARCH_API_KEY=key, MINIMAX_API_KEY='', MINIMAX_API_HOST='https://api.minimaxi.com', MINIMAX_USE_PROXY=False)
        with patch('app.services.search.settings', settings), patch('app.services.search.httpx.AsyncClient', side_effect=lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)):
            return await search_via_mcp('示例公司', 1)

    async def test_official_request_and_result_mapping(self):
        result = await self.run_search({'base_resp':{'status_code':0},'organic':[{'title':'官网','link':'https://example.com','snippet':'简介','date':'2026-11-05'},{'title':'second','link':'https://example.org'}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['url'], 'https://example.com')
        self.assertEqual(self.requests[0].url.path, '/v1/coding_plan/search')
        self.assertEqual(self.requests[0].headers['Authorization'], 'Bearer test-key')
        self.assertIn(b'"q"', self.requests[0].content)

    async def test_api_failure_is_not_empty_success(self):
        with self.assertRaises(SearchUnavailable):
            await self.run_search({'base_resp':{'status_code':1004,'status_msg':'sensitive provider error'}})

    async def test_http_failure_is_sanitized(self):
        with self.assertRaises(SearchUnavailable) as caught:
            await self.run_search({}, 401)
        self.assertNotIn('test-key', str(caught.exception))

    async def test_missing_key_makes_no_request(self):
        with self.assertRaises(SearchUnavailable):
            await self.run_search({}, key='')
        self.assertEqual(self.requests, [])

    async def test_unsafe_links_are_filtered(self):
        result = await self.run_search({'base_resp':{'status_code':0},'organic':[{'link':'javascript:alert(1)'}]})
        self.assertEqual(result, [])

if __name__ == '__main__': unittest.main()
