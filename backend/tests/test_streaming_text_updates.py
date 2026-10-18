"""Offline regression tests for practice-chat text streaming."""
import unittest
from unittest.mock import AsyncMock, patch
import httpx

from app.services.conversation import streaming
from app.services.llm.minimax import MiniMaxService


class _FakeMiniMax:
    """A deterministic LLM/TTS double that never makes network calls."""

    def __init__(self, tokens=("您好，", "我正在", "整理您的", "需求。")):
        self.stream_finished = False
        self._tokens = tokens

    async def chat_stream(self, messages, model):
        del messages, model
        for token in self._tokens:
            yield token
        self.stream_finished = True

    async def text_to_speech_stream(self, **kwargs):
        del kwargs
        if False:
            yield b""

    async def text_to_speech(self, **kwargs):
        del kwargs
        return b""


class StreamingTextUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_provider_stream_is_shown_in_chat(self):
        events = []

        async def websocket_send(event):
            events.append(event)

        assembled = {
            "messages": [{"role": "system", "content": "test"}],
            "emotion": "neutral",
            "voice_modify": {},
            "breath_tag": "",
            "knowledge_refs": [],
        }
        with patch.object(
            streaming, "parallel_context_assembly", new=AsyncMock(return_value=assembled)
        ), patch(
            "app.websocket.manager.session_manager.get_session_info", return_value={}
        ):
            result = await streaming.stream_pipeline(
                websocket_send=websocket_send,
                websocket_send_binary=None,
                session_id="test-session",
                user_text="你好",
                user_audio_data=None,
                user_audio_mime=None,
                client_id=None,
                minimax=_FakeMiniMax(tokens=()),
                handler=object(),
            )

        self.assertEqual(result["full_response"], "")
        self.assertEqual(events[-1]["type"], "ai_streaming_end")
        self.assertIn("暂时无法", events[-1]["content"])

    async def test_provider_rejection_is_shown_in_chat(self):
        request = httpx.Request("POST", "https://api.minimaxi.com/v1/chat/completions")
        response = httpx.Response(402, request=request)

        class RejectedMiniMax(_FakeMiniMax):
            async def chat_stream(self, messages, model):
                del messages, model
                response.raise_for_status()
                if False:
                    yield ""

        events = []
        async def websocket_send(event):
            events.append(event)

        assembled = {
            "messages": [{"role": "system", "content": "test"}],
            "emotion": "neutral",
            "voice_modify": {},
            "breath_tag": "",
            "knowledge_refs": [],
        }
        with patch.object(
            streaming, "parallel_context_assembly", new=AsyncMock(return_value=assembled)
        ), patch(
            "app.websocket.manager.session_manager.get_session_info", return_value={}
        ):
            result = await streaming.stream_pipeline(
                websocket_send=websocket_send,
                websocket_send_binary=None,
                session_id="test-session",
                user_text="你好",
                user_audio_data=None,
                user_audio_mime=None,
                client_id=None,
                minimax=RejectedMiniMax(),
                handler=object(),
            )

        self.assertEqual(result["full_response"], "")
        self.assertEqual(events[-1]["type"], "ai_streaming_end")
        self.assertIn("额度", events[-1]["content"])

    async def test_chat_stream_rejects_http_error_without_network(self):
        request = httpx.Request("POST", "https://api.minimaxi.com/v1/chat/completions")
        transport = httpx.MockTransport(lambda _request: httpx.Response(402, request=request))
        real_client = httpx.AsyncClient

        with patch(
            "app.services.llm.minimax.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            with self.assertRaises(httpx.HTTPStatusError) as raised:
                async for _ in MiniMaxService(api_key="test-key").chat_stream(
                    [{"role": "user", "content": "hello"}]
                ):
                    pass

        self.assertEqual(raised.exception.response.status_code, 402)

if __name__ == "__main__":
    unittest.main()
