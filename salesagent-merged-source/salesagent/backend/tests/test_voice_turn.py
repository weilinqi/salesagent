"""Offline checks for the voice turn handoff."""
import asyncio
import base64
import unittest
from unittest.mock import AsyncMock, patch

from app.websocket.voice_turn import finish_voice_input


class VoiceTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_audio_precedes_end_marker(self):
        queue = asyncio.Queue()
        convert = AsyncMock(return_value=b"last-pcm")

        await finish_voice_input(queue, [b"webm-a", b"webm-b"], "audio/webm", convert)

        convert.assert_awaited_once_with(b"webm-awebm-b", "audio/webm")
        self.assertEqual(await queue.get(), b"last-pcm")
        self.assertIsNone(await queue.get())

    async def test_empty_audio_still_ends_input(self):
        queue = asyncio.Queue()
        convert = AsyncMock()

        await finish_voice_input(queue, [], "audio/webm", convert)

        convert.assert_not_awaited()
        self.assertIsNone(await queue.get())

    async def test_conversion_timeout_unblocks_realtime_input(self):
        queue = asyncio.Queue()
        never = asyncio.Event()

        async def stalled_convert(audio, mime):
            await never.wait()

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(
                finish_voice_input(queue, [b"webm"], "audio/webm", stalled_convert),
                timeout=0.01,
            )

        self.assertIsNone(await queue.get())

    async def test_voice_transcript_does_not_start_second_ai_reply(self):
        from app import main

        service = AsyncMock()
        service.speech_to_text_realtime.return_value = "你好"
        with patch.object(main, "get_minimax_service", return_value=service), \
             patch.object(main, "safe_send_message", new_callable=AsyncMock) as send, \
             patch.object(main, "safe_send_status", new_callable=AsyncMock) as status, \
             patch.object(main, "save_message_to_db") as save, \
             patch.object(main.session_manager, "add_message") as add:
            await main.process_user_message(
                None, "session", "语音消息", base64.b64encode(b"audio").decode(),
                "audio/webm", "message-id", voice_only=True,
            )

        service.speech_to_text_realtime.assert_awaited_once()
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[1]["type"], "user_message_ack")
        self.assertEqual(send.await_args.args[1]["asr_text"], "你好")
        add.assert_called_once_with("session", "user", "你好")
        save.assert_called_once_with("session", "user", "你好")
        status.assert_not_awaited()

    async def test_transcript_waits_for_first_reply_audio(self):
        from app import main

        ready = asyncio.Event()
        service = AsyncMock()
        service.speech_to_text_realtime.return_value = "你好"
        with patch.object(main, "get_minimax_service", return_value=service), \
             patch.object(main, "safe_send_message", new_callable=AsyncMock), \
             patch.object(main, "save_message_to_db"), \
             patch.object(main.session_manager, "add_message"):
            task = asyncio.create_task(main.process_user_message(
                None, "session", "语音消息", base64.b64encode(b"audio").decode(),
                "audio/webm", "message-id", voice_only=True, voice_ready=ready,
            ))
            await asyncio.sleep(0)
            service.speech_to_text_realtime.assert_not_awaited()
            ready.set()
            await task

        service.speech_to_text_realtime.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
