"""Offline regressions: Windows env loading, proxy routing and TTS decoding."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import httpx
from app.services.llm.minimax import MiniMaxService


class ConfigurationTests(unittest.TestCase):
    def test_utf8_dotenv_quotes_and_process_override(self):
        source = Path(__file__).parents[1] / 'app' / 'config.py'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'app').mkdir()
            (root / 'app' / 'config.py').write_bytes(source.read_bytes())
            (root / '.env').write_text(
                '# 中文配置\nAPP_NAME="测试项目"\nDATABASE_URL="sqlite:///file.db"\n',
                encoding='utf-8',
            )
            env = os.environ.copy()
            env.pop('APP_NAME', None)
            env['DATABASE_URL'] = 'sqlite:///temporary.db'
            env['PYTHONUTF8'] = '0'
            code = (
                "import runpy; s=runpy.run_path('app/config.py')['settings']; "
                "assert s.APP_NAME == '\u6d4b\u8bd5\u9879\u76ee', repr(s.APP_NAME); "
                "assert s.DATABASE_URL == 'sqlite:///temporary.db', s.DATABASE_URL"
            )
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=root,
                                    env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))


class MiniMaxConnectivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_tts_returns_audio_without_a_second_download(self):
        calls = []
        options = []
        original = httpx.AsyncClient

        def respond(request):
            calls.append(request)
            self.assertEqual(request.url.path, '/v1/t2a_v2')
            self.assertEqual(json.loads(request.content)['output_format'], 'hex')
            return httpx.Response(200, json={
                'data': {'audio': '4944330102', 'status': 2},
                'base_resp': {'status_code': 0, 'status_msg': 'success'},
            })

        def client(**kwargs):
            options.append(kwargs)
            return original(transport=httpx.MockTransport(respond), **kwargs)

        with patch('app.services.llm.minimax.httpx.AsyncClient', side_effect=client):
            audio = await MiniMaxService(api_key='test-placeholder').text_to_speech('你好')
        self.assertEqual(audio, b'ID3\x01\x02')
        self.assertEqual(len(calls), 1)
        self.assertIs(options[0].get('trust_env'), False)

    async def test_http_200_quota_error_is_not_reported_as_missing_audio(self):
        original = httpx.AsyncClient
        def respond(request):
            return httpx.Response(200, json={
                'data': None, 'base_resp': {'status_code': 2056, 'status_msg': 'quota exceeded'},
            })
        def client(**kwargs):
            return original(transport=httpx.MockTransport(respond), **kwargs)
        with patch('app.services.llm.minimax.httpx.AsyncClient', side_effect=client):
            with self.assertRaisesRegex(RuntimeError, '2056'):
                await MiniMaxService(api_key='test-placeholder').text_to_speech('你好')

    async def test_text_routing_defaults_direct_and_can_opt_in_to_proxy(self):
        original = httpx.AsyncClient
        for use_proxy in (False, True):
            with self.subTest(use_proxy=use_proxy):
                options = []
                def respond(request):
                    return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n')
                def client(**kwargs):
                    options.append(kwargs)
                    return original(transport=httpx.MockTransport(respond), **kwargs)
                with patch('app.config.settings', SimpleNamespace(MINIMAX_API_KEY='', MINIMAX_USE_PROXY=use_proxy)), \
                     patch('app.services.llm.minimax.httpx.AsyncClient', side_effect=client):
                    result = ''.join([token async for token in MiniMaxService(api_key='test-placeholder').chat_stream([])])
                self.assertEqual(result, '你好')
                self.assertIs(options[0].get('trust_env'), use_proxy)

    async def test_speech_websocket_bypasses_proxy_by_default(self):
        class Socket:
            def __init__(self):
                self.responses = iter([
                    {'event': 'connected_success'}, {'event': 'task_started'},
                    {'data': {'audio': '494433'}, 'is_final': True},
                ])
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def recv(self): return json.dumps(next(self.responses))
            async def send(self, _): pass
        with patch('websockets.connect', return_value=Socket()) as connect:
            audio = b''.join([part async for part in MiniMaxService(api_key='test-placeholder').text_to_speech_stream('你好')])
        self.assertEqual(audio, b'ID3')
        self.assertIn('proxy', connect.call_args.kwargs)
        self.assertIsNone(connect.call_args.kwargs['proxy'])


if __name__ == '__main__':
    unittest.main()
