import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "spin-guidance-test-secret-long-enough-for-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

import app.main as main


def run_async(coroutine):
    if os.name == "nt":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


class SpinGuidanceStatusTests(unittest.TestCase):
    def test_success_status_includes_measured_update_duration(self):
        async def run():
            async def delayed_guidance(_session_id):
                await asyncio.sleep(0.05)
                return {"focus": "test"}

            fake_module = types.ModuleType("app.services.conversation.spin_guidance")
            fake_module.update_guidance = delayed_guidance
            with patch.dict(sys.modules, {fake_module.__name__: fake_module}), patch.object(
                main.manager, "send_message", new_callable=AsyncMock
            ) as send:
                await main._safe_update_spin_guidance("test-session")

            statuses = [call.args[1]["data"] for call in send.await_args_list]
            self.assertEqual([status["status"] for status in statuses], ["updating", "updated"])
            self.assertGreaterEqual(statuses[-1]["duration_ms"], 20)

        run_async(run())

if __name__ == "__main__":
    unittest.main()
