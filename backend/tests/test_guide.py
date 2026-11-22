import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "guide-test-secret-longer-than-thirty-two-characters")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.guide import _apply_guide_seen, _get_or_create_progress
from app.database import Base
from app.models import User


class GuideProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            "sqlite:///" + str(Path(self.tmp.name) / "guide.db"),
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.user_id = str(uuid.uuid4())
        with self.sessions() as db:
            db.add(User(id=self.user_id, email="guide@example.com", username="guide", hashed_password="unused"))
            db.commit()

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def test_overview_and_module_are_persisted_per_user(self):
        with self.sessions() as db:
            progress = _get_or_create_progress(db, self.user_id)
            self.assertFalse(progress.overview_seen)
            _apply_guide_seen(progress, "overview")
            _apply_guide_seen(progress, "module", "practice")
            db.commit()
            stored = _get_or_create_progress(db, self.user_id)
            self.assertTrue(stored.overview_seen)
            self.assertTrue(stored.modules["practice"])
            self.assertFalse(stored.modules.get("customers", False))


if __name__ == "__main__":
    unittest.main()