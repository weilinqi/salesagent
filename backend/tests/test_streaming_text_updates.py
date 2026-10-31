"""Offline regression tests for practice-chat text streaming."""
import asyncio
import contextlib
import io
import json
import unittest
from unittest.mock import AsyncMock, patch
import httpx

from app.services.conversation import streaming
from app.services.llm.minimax import MiniMaxService
from app.services.llm.minimax_fallback import MiniMaxAPIError


class _FakeMiniMax:
    """A deterministic LLM/TTS double that never makes network calls."""

    def __init__(self, tokens=("您好，", "我正在", "整理您的", "需求。")):
        self.stream_finished = False
        self._tokens = tokens

    async def chat_stream(self, messages, model, max_tokens=4096):
        del messages, model, max_tokens
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
    async def test_first_audio_latency_includes_context_assembly(self):
        """The reported first-audio time must cover context, LLM, and TTS."""
        now = [100.0]
        events = []
        binary_chunks = []

        async def assemble_context(*_args, **_kwargs):
            now[0] += 1.25
            return {
                "messages": [{"role": "system", "content": "test"}],
                "emotion": "neutral",
                "voice_modify": {},
                "breath_tag": "",
                "knowledge_refs": [],
            }

        class LatencyMiniMax:
            async def chat_stream(self, messages, model, max_tokens=4096):
                del messages, model, max_tokens
                now[0] += 1.0
                yield "好的。"

            async def text_to_speech_stream(self, text, **kwargs):
                del text, kwargs
                now[0] += 0.5
                yield b"audio"

            async def text_to_speech(self, **kwargs):
                del kwargs
                return b""

        async def websocket_send(event):
            events.append(event)

        async def websocket_send_binary(chunk):
            binary_chunks.append(chunk)

        stdout = io.StringIO()
        with patch.object(
            streaming, "parallel_context_assembly", new=assemble_context
        ), patch(
            "app.websocket.manager.session_manager.get_session_info", return_value={}
        ), contextlib.redirect_stdout(stdout):
            result = await streaming.stream_pipeline(
                websocket_send=websocket_send,
                websocket_send_binary=websocket_send_binary,
                session_id="test-session",
                user_text="你好",
                user_audio_data=None,
                user_audio_mime=None,
                client_id=None,
                minimax=LatencyMiniMax(),
                handler=object(),
                latency_clock=lambda: now[0],
            )

        self.assertEqual(binary_chunks, [b"audio"])
        self.assertEqual(result["first_audio_ms"], 2750)
        self.assertTrue(result["first_audio_target_met"])
        self.assertIn(
            "[LATENCY] first_audio=2750ms target<3000ms PASS",
            stdout.getvalue(),
        )

    async def test_first_audio_latency_requires_a_binary_sender(self):
        """Generating bytes without a WebSocket sender is not first audio."""
        assembled = {
            "messages": [{"role": "system", "content": "test"}],
            "emotion": "neutral",
            "voice_modify": {},
            "breath_tag": "",
            "knowledge_refs": [],
        }

        class AudioMiniMax:
            async def chat_stream(self, messages, model, max_tokens=4096):
                del messages, model, max_tokens
                yield "好的。"

            async def text_to_speech_stream(self, text, **kwargs):
                del text, kwargs
                yield b"audio"

        with patch.object(
            streaming, "parallel_context_assembly", new=AsyncMock(return_value=assembled)
        ), patch(
            "app.websocket.manager.session_manager.get_session_info", return_value={}
        ):
            result = await streaming.stream_pipeline(
                websocket_send=AsyncMock(),
                websocket_send_binary=None,
                session_id="test-session",
                user_text="你好",
                user_audio_data=None,
                user_audio_mime=None,
                client_id=None,
                minimax=AudioMiniMax(),
                handler=object(),
            )

        self.assertIsNone(result["first_audio_ms"])
        self.assertIsNone(result["first_audio_target_met"])

    async def test_knowledge_warmup_primes_conversation_retrieval(self):
        calls = []

        class Handler:
            def _retrieve_knowledge_references(
                self, user_message, conversation_history, scenario
            ):
                calls.append((user_message, conversation_history, scenario))
                return [{"source": "test"}]

        ready = await streaming.warmup_knowledge_retrieval(Handler())

        self.assertTrue(ready)
        self.assertEqual(calls, [("产品介绍", [], "general")])

    async def test_knowledge_warmup_failure_is_non_fatal(self):
        class Handler:
            def _retrieve_knowledge_references(self, *_args, **_kwargs):
                raise RuntimeError("offline")

        ready = await streaming.warmup_knowledge_retrieval(Handler())

        self.assertFalse(ready)

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
            async def chat_stream(self, messages, model, max_tokens=4096):
                del messages, model, max_tokens
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

    async def test_rate_limit_explains_quota_in_chat(self):
        request = httpx.Request("POST", "https://api.minimaxi.com/v1/chat/completions")
        response = httpx.Response(429, request=request)

        class RateLimitedMiniMax(_FakeMiniMax):
            async def chat_stream(self, messages, model, max_tokens=4096):
                del messages, model, max_tokens
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
            await streaming.stream_pipeline(
                websocket_send=websocket_send,
                websocket_send_binary=None,
                session_id="test-session",
                user_text="你好",
                user_audio_data=None,
                user_audio_mime=None,
                client_id=None,
                minimax=RateLimitedMiniMax(),
                handler=object(),
            )

        self.assertEqual(events[-1]["type"], "ai_streaming_end")
        self.assertIn("429", events[-1]["content"])
        self.assertIn("额度", events[-1]["content"])

    async def test_chat_stream_rejects_http_error_without_network(self):
        request = httpx.Request("POST", "https://api.minimaxi.com/v1/chat/completions")
        transport = httpx.MockTransport(lambda _request: httpx.Response(402, request=request))
        real_client = httpx.AsyncClient

        with patch(
            "app.services.llm.minimax.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            with self.assertRaises(MiniMaxAPIError) as raised:
                async for _ in MiniMaxService(api_key="test-key").chat_stream(
                    [{"role": "user", "content": "hello"}]
                ):
                    pass

        self.assertEqual(raised.exception.http_status, 402)

    async def test_chat_stream_disables_thinking_for_low_latency(self):
        """The provider request must skip M3 thinking and cap short chat output."""
        captured = {}

        def handler(request):
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                request=request,
                content=(
                    b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
                    b'data: [DONE]\n\n'
                ),
            )

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with patch(
            "app.services.llm.minimax.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            tokens = [
                token
                async for token in MiniMaxService(api_key="test-key").chat_stream(
                    [{"role": "user", "content": "hello"}], max_tokens=256
                )
            ]

        self.assertEqual(tokens, ["hello"])
        self.assertEqual(captured["thinking"], {"type": "disabled"})
        self.assertTrue(captured["reasoning_split"])
        self.assertEqual(captured["max_tokens"], 256)

    async def test_tts_stream_uses_websockets_16_headers(self):
        """TTS must connect with the websockets 16 additional_headers keyword."""
        sent = []
        replies = iter([
            json.dumps({"event": "connected_success"}),
            json.dumps({"event": "task_started"}),
            json.dumps({
                "event": "task_continued",
                "data": {"audio": "00ff"},
                "is_final": True,
            }),
        ])

        class FakeSocket:
            async def recv(self):
                return next(replies)

            async def send(self, message):
                sent.append(json.loads(message))

        class FakeConnection:
            async def __aenter__(self):
                return FakeSocket()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        def connect(_url, **kwargs):
            if "extra_headers" in kwargs:
                raise TypeError("websockets 16 rejects extra_headers")
            self.assertEqual(
                kwargs["additional_headers"], {"Authorization": "Bearer test-key"}
            )
            return FakeConnection()

        with patch("websockets.connect", side_effect=connect):
            chunks = [
                chunk
                async for chunk in MiniMaxService(api_key="test-key").text_to_speech_stream(
                    "你好"
                )
            ]

        self.assertEqual(chunks, [b"\x00\xff"])
        self.assertEqual(sent[0]["event"], "task_start")
        self.assertEqual(sent[1], {"event": "task_continue", "text": "你好"})

    async def test_starts_tts_before_llm_finishes_and_skips_http_duplicate(self):
        """A completed sentence should speak while later LLM tokens are still arriving."""
        class OverlapMiniMax:
            def __init__(self):
                self.tts_started = False
                self.tts_started_before_stream_finished = False
                self.http_tts_calls = 0

            async def chat_stream(self, messages, model, max_tokens=4096):
                del messages, model, max_tokens
                yield "第一句。"
                await asyncio.sleep(0)
                self.tts_started_before_stream_finished = self.tts_started
                yield "第二句。"

            async def text_to_speech_stream(self, text, **kwargs):
                del kwargs
                self.tts_started = True
                yield text.encode("utf-8")

            async def text_to_speech(self, **kwargs):
                del kwargs
                self.http_tts_calls += 1
                return b"duplicate"

        minimax = OverlapMiniMax()
        events = []
        binary_chunks = []

        async def websocket_send(event):
            events.append(event)

        async def websocket_send_binary(chunk):
            binary_chunks.append(chunk)

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
                websocket_send_binary=websocket_send_binary,
                session_id="test-session",
                user_text="你好",
                user_audio_data=None,
                user_audio_mime=None,
                client_id=None,
                minimax=minimax,
                handler=object(),
            )

        self.assertTrue(minimax.tts_started_before_stream_finished)
        self.assertEqual(minimax.http_tts_calls, 0)
        self.assertEqual(binary_chunks, ["第一句。".encode(), "第二句。".encode()])
        self.assertEqual(result["full_response"], "第一句。第二句。")
        self.assertTrue(events[-1]["audio_data"])

    async def test_sends_text_update_before_llm_stream_finishes(self):
        """The UI must receive cumulative text while the LLM is still yielding."""
        minimax = _FakeMiniMax()
        events = []

        async def websocket_send(event):
            events.append((event, minimax.stream_finished))

        async def websocket_send_binary(chunk):
            del chunk

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
                websocket_send_binary=websocket_send_binary,
                session_id="test-session",
                user_text="请介绍一下产品",
                user_audio_data=None,
                user_audio_mime=None,
                client_id=None,
                minimax=minimax,
                handler=object(),
            )

        updates = [event for event, _ in events if event["type"] == "ai_streaming_update"]
        update_states = [finished for event, finished in events if event["type"] == "ai_streaming_update"]

        self.assertTrue(updates)
        self.assertIn(False, update_states)
        self.assertEqual(updates[-1]["content"], "您好，我正在整理您的需求。")
        self.assertEqual(result["full_response"], "您好，我正在整理您的需求。")
        self.assertEqual(events[-1][0]["type"], "ai_streaming_end")

    async def test_does_not_stream_reasoning_when_think_tag_is_split_across_tokens(self):
        """Split reasoning tags must not expose their contents in incremental updates."""
        minimax = _FakeMiniMax(("<thi", "nk>internal reasoning</think>", "您好"))
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
                user_text="请介绍一下产品",
                user_audio_data=None,
                user_audio_mime=None,
                client_id=None,
                minimax=minimax,
                handler=object(),
            )

        updates = [event["content"] for event in events if event["type"] == "ai_streaming_update"]
        self.assertTrue(updates)
        self.assertTrue(all("internal reasoning" not in content for content in updates))
        self.assertEqual(updates[-1], "您好")
        self.assertEqual(result["full_response"], "您好")


if __name__ == "__main__":
    unittest.main()
