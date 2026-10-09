"""Run: python -m unittest discover -s tests -v (no API keys or model downloads)."""
import ast
import asyncio
import builtins
import importlib.util
import json
import logging
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

import websockets

ROOT = Path(__file__).resolve().parents[1]


def load_service():
    spec = importlib.util.spec_from_file_location(
        "network_test_minimax", ROOT / "app/services/llm/minimax.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    service = module.MiniMaxService.__new__(module.MiniMaxService)
    service.api_key = "local-test-key"
    service.group_id = ""
    return service


class NetworkRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_whisper_import_does_not_block_event_loop(self):
        tree = ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))
        warmup = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.AsyncFunctionDef)
                      and n.name == "_warmup_whisper")
        started = threading.Event()
        completed = threading.Event()
        real_import = builtins.__import__

        def slow_import(name, *args, **kwargs):
            if name == "faster_whisper":
                started.set()
                time.sleep(0.3)
                completed.set()
                return types.ModuleType(name)
            return real_import(name, *args, **kwargs)

        namespace = {
            "asyncio": asyncio, "logger": logging.getLogger(__name__),
            "__builtins__": {**vars(builtins), "__import__": slow_import},
        }
        exec(compile(ast.Module(body=[warmup], type_ignores=[]), "warmup", "exec"), namespace)
        minimax = types.ModuleType("app.services.llm.minimax")
        minimax.get_minimax_service = lambda: None
        with patch.dict(sys.modules, {"app.services.llm.minimax": minimax}):
            task = asyncio.create_task(namespace["_warmup_whisper"]())
            try:
                await asyncio.sleep(0.05)
                self.assertTrue(started.is_set(), "Whisper import did not start")
                self.assertFalse(completed.is_set(), "Whisper import blocked the event loop")
            finally:
                await task

    async def test_model_warmup_does_not_block_event_loop(self):
        # Load the real nested startup function without starting the database,
        # scheduler, or downloading models. Only the slow model is substituted.
        tree = ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))
        warmup = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.AsyncFunctionDef)
                      and n.name == "_warmup_embedding")
        namespace = {"asyncio": asyncio, "logger": logging.getLogger(__name__)}
        exec(compile(ast.Module(body=[warmup], type_ignores=[]), "warmup", "exec"), namespace)
        started = threading.Event()
        completed = threading.Event()

        class SlowModel:
            def embed_query(self, text):
                started.set()
                time.sleep(0.3)
                completed.set()
                return [0.1]

        embedding = types.ModuleType("app.services.knowledge.embedding")
        embedding.get_embedding_model = lambda: SlowModel()
        modules = {"app.services.knowledge.embedding": embedding}
        with patch.dict(sys.modules, modules):
            task = asyncio.create_task(namespace["_warmup_embedding"]())
            try:
                await asyncio.sleep(0.05)
                self.assertTrue(started.is_set(), "Model warmup did not start")
                self.assertFalse(completed.is_set(), "Model loading blocked the event loop")
            finally:
                await task

    async def run_with_local_server(self, operation, tts=False):
        received_auth = []

        async def handler(ws):
            received_auth.append(ws.request.headers.get("Authorization"))
            if tts:
                await ws.send(json.dumps({"event": "connected_success"}))
                await ws.recv()  # task_start
                await ws.send(json.dumps({"event": "task_started"}))
                await ws.recv()  # task_continue
                await ws.send(json.dumps({"data": {"audio": "010203"}, "is_final": True}))
                await ws.recv()  # task_finish
            else:
                await ws.send(json.dumps({"type": "session.created"}))
                await ws.recv()  # session.update
                await ws.send(json.dumps({"type": "session.updated"}))
                await ws.send(json.dumps({"type": "response.text.done", "text": "test response"}))
                await ws.send(json.dumps({
                    "type": "response.done",
                    "response": {"output": [{"content": [{"type": "text", "text": "test response"}]}]},
                }))
                await ws.wait_closed()

        real_connect = websockets.connect
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]

            def connect_locally(uri, **kwargs):
                # Preserve production header arguments: websockets itself must
                # accept them and send Authorization in the real handshake.
                kwargs.pop("ssl", None)
                return real_connect(f"ws://127.0.0.1:{port}", proxy=None, **kwargs)

            with patch.object(websockets, "connect", connect_locally):
                result = await asyncio.wait_for(operation(load_service()), timeout=5)
        self.assertEqual(received_auth, ["Bearer local-test-key"])
        return result

    async def test_tts_connects_and_returns_audio(self):
        async def operation(service):
            return b"".join([chunk async for chunk in service.text_to_speech_stream("test")])

        self.assertEqual(await self.run_with_local_server(operation, tts=True), b"\x01\x02\x03")

    async def test_streaming_asr_connects_and_returns_text(self):
        async def operation(service):
            async def chunks():
                if False:
                    yield b""

            async def on_partial(text):
                pass

            return await service.speech_to_text_realtime_stream(chunks(), on_partial)

        self.assertEqual(await self.run_with_local_server(operation), "test response")

    async def test_realtime_chat_connects_and_returns_text(self):
        async def operation(service):
            async def chunks():
                if False:
                    yield b""

            async def callback(value):
                pass

            return await service.realtime_voice_chat(chunks(), callback, callback)

        self.assertEqual(await self.run_with_local_server(operation), "test response")

    async def test_recorded_asr_connects_and_returns_text(self):
        async def operation(service):
            def convert_audio(args, **kwargs):
                Path(args[-1]).write_bytes(b"\x00\x00" * 100)

            with patch("subprocess.run", convert_audio):
                return await service.speech_to_text_realtime(b"test-audio")

        self.assertEqual(await self.run_with_local_server(operation), "test response")


if __name__ == "__main__":
    unittest.main()
