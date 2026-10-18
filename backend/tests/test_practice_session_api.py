"""Offline API regression tests for starting a practice session."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.v1.practice import router as practice_router
from app.database import Base, get_db
from app.models.practice import PracticeSession, Scenario


class PracticeSessionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path.cwd())
        db_path = Path(self.temp_dir.name) / "practice.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.scenario_id = str(uuid4())
        with self.session_factory() as db:
            db.add(Scenario(
                id=self.scenario_id,
                name="Test scenario",
                type="first_contact",
                status="approved",
            ))
            db.commit()

        app = FastAPI()
        app.include_router(practice_router, prefix="/api/v1")

        def test_db():
            with self.session_factory() as db:
                yield db

        app.dependency_overrides[get_db] = test_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_anonymous_session_is_created_without_user_foreign_key(self):
        response = self.client.post("/api/v1/practice/sessions", json={
            "scenario_id": self.scenario_id,
            "role_config": {
                "position_level": "senior",
                "personality": "rational",
                "decision_style": "value_oriented",
            },
            "user_context": {"sales_name": "Test seller"},
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["websocket_url"], f"/ws/practice/{data['session_id']}")
        with self.session_factory() as db:
            session = db.get(PracticeSession, data["session_id"])
            self.assertIsNotNone(session)
            self.assertIsNone(session.user_id)
            self.assertEqual(session.user_context["sales_name"], "Test seller")

    def test_unknown_scenario_is_rejected(self):
        response = self.client.post("/api/v1/practice/sessions", json={
            "scenario_id": str(uuid4()),
            "role_config": {
                "position_level": "senior",
                "personality": "rational",
                "decision_style": "value_oriented",
            },
        })

        self.assertEqual(response.status_code, 404)
        with self.session_factory() as db:
            self.assertEqual(db.query(PracticeSession).count(), 0)


if __name__ == "__main__":
    unittest.main()
