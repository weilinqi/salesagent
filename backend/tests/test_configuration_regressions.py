"""Configuration precedence and signing-key validation are exercised offline."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.config import Settings


class ConfigurationTests(unittest.TestCase):
    def test_default_dotenv_loader_preserves_process_environment(self):
        import app.config
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app" / "config.py"
            path.parent.mkdir()
            shutil.copyfile(app.config.__file__, path)
            (Path(directory) / ".env").write_text("ACCESS_TOKEN_EXPIRE_MINUTES=15\nAPP_NAME='UTF8 销售'\n", encoding="utf-8")
            environment = dict(os.environ, ACCESS_TOKEN_EXPIRE_MINUTES="19", PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONPATH=os.pathsep.join(sys.path), SECRET_KEY="offline-regression-secret-with-at-least-32-characters")
            script = "import importlib.util,json,sys; s=importlib.util.spec_from_file_location('isolated_config',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps({'expiry':m.settings.ACCESS_TOKEN_EXPIRE_MINUTES,'name':m.settings.APP_NAME}))"
            result = subprocess.run([sys.executable, "-c", script, str(path)], env=environment, capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(result.stdout), {"expiry": 19, "name": "UTF8 销售"})

    def test_settings_environment_takes_precedence_over_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("ACCESS_TOKEN_EXPIRE_MINUTES=15\nAPP_NAME='UTF8 销售'\n", encoding="utf-8")
            with patch.dict(os.environ, {"ACCESS_TOKEN_EXPIRE_MINUTES": "19"}):
                value = Settings(_env_file=path)
            self.assertEqual(value.ACCESS_TOKEN_EXPIRE_MINUTES, 19)
            self.assertEqual(value.APP_NAME, "UTF8 销售")

    def test_production_rejects_default_empty_and_short_jwt_secrets(self):
        for secret in ("your-secret-key-change-in-production", "", "short", "x" * 40):
            with self.assertRaises(ValueError):
                Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY=secret)

    def test_validation_errors_do_not_echo_credentials(self):
        credential = "sentinel"
        with self.assertRaises(ValueError) as captured:
            Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY=credential)
        self.assertNotIn(credential, str(captured.exception))


if __name__ == "__main__":
    unittest.main()
