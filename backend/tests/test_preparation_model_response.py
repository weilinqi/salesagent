import unittest
from unittest.mock import patch
import httpx
from app.services.llm.minimax import MiniMaxService

class PreparationModelResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_tool_calls_does_not_hide_extracted_content(self):
        original = httpx.AsyncClient
        text = '{"product":"数学课"}'
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
            'choices': [{'message': {'content': text, 'tool_calls': None}}], 'base_resp': {'status_code':0}}))
        with patch('app.services.llm.minimax.httpx.AsyncClient', side_effect=lambda **kwargs: original(transport=transport, **kwargs)):
            result = await MiniMaxService(api_key='offline-test-key').chat([{'role':'user','content':'extract'}])
        self.assertEqual(result, text)
