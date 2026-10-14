"""Exercise the real auth/profile routers without AI calls or a business database."""
import os
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "offline-regression-secret-with-at-least-32-characters"
os.environ["ENVIRONMENT"] = "test"

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token, get_current_user_optional
from app.database import Base, get_db
from app.models.user import User


def load_router(name):
    # Load the real router file without app.api's eager report/audio imports.
    path = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"regression_{name}_router", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


auth = load_router("auth")
profile = load_router("profile")


class AuthProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp.name) / 'test.db'}",
            connect_args={"check_same_thread": False},
        )
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        app = FastAPI()
        app.include_router(auth.router, prefix="/api/v1")
        app.include_router(profile.router, prefix="/api/v1")
        def temporary_db():
            with self.session_factory() as db:
                yield db
        app.dependency_overrides[get_db] = temporary_db
        @app.get("/optional")
        def optional(user=Depends(get_current_user_optional)):
            return {"user_id": user.id if user else None}
        self.client = TestClient(app, raise_server_exceptions=False)
        with self.session_factory() as db:
            db.add_all([
                User(id="user-one", email="one@example.com", username="first", hashed_password="unused"),
                User(id="user-two", email="two@example.com", username="second", hashed_password="unused"),
                User(id="disabled", email="disabled@example.com", username="disabled", hashed_password="unused", is_active=False),
            ])
            db.commit()
        self.headers = {"Authorization": f"Bearer {create_access_token('user-one')}"}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_refresh_accepts_json_body_and_reports_configured_expiry(self):
        with patch.object(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 11):
            response = self.client.post("/api/v1/auth/refresh", json={"refresh_token": create_refresh_token("user-one")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["expires_in"], 660)
        self.assertEqual(response.json()["user"]["id"], "user-one")

    def test_register_and_login_return_configured_expiry(self):
        with patch.object(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 9):
            created = self.client.post("/api/v1/auth/register", json={"email": "new@example.com", "username": "new-user", "password": "test-password"})
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["expires_in"], 540)
            logged_in = self.client.post("/api/v1/auth/login", json={"email": "new@example.com", "password": "test-password"})
            self.assertEqual(logged_in.status_code, 200, logged_in.text)
            self.assertEqual(logged_in.json()["expires_in"], 540)
            self.assertEqual(logged_in.json()["user"]["id"], created.json()["user"]["id"])

    def test_update_account_is_committed_and_visible_in_later_request(self):
        response = self.client.put("/api/v1/auth/me", headers=self.headers, json={
            "username": "changed", "email": "changed@example.com", "full_name": "Changed name", "bio": "New bio",
        })
        self.assertEqual(response.status_code, 200, response.text)
        later = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(later.status_code, 200, later.text)
        self.assertEqual(later.json()["username"], "changed")
        self.assertEqual(later.json()["email"], "changed@example.com")
        self.assertEqual(later.json()["full_name"], "Changed name")

    def test_account_uniqueness_and_invalid_required_fields_are_rejected(self):
        for data in ({"username": "second"}, {"email": "two@example.com"}):
            response = self.client.put("/api/v1/auth/me", headers=self.headers, json=data)
            self.assertEqual(response.status_code, 400, response.text)
        for data in ({"username": None}, {"email": None}, {"username": "  "}, {"email": "bad"}):
            self.assertEqual(self.client.put("/api/v1/auth/me", headers=self.headers, json=data).status_code, 422)

    def test_avatar_accepts_json_and_persists(self):
        url = "https://example.com/avatar.png"
        response = self.client.post("/api/v1/users/me/avatar", headers=self.headers, json={"avatar_url": url})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.headers).json()["avatar_url"], url)

    def test_skills_persist_between_sessions_and_are_isolated_per_account(self):
        response = self.client.put("/api/v1/users/me/skills", headers=self.headers, json=[{"skill_name": "需求挖掘", "level": 5}])
        self.assertEqual(response.status_code, 200, response.text)
        later = self.client.get("/api/v1/users/me/profile", headers=self.headers)
        self.assertEqual(later.status_code, 200, later.text)
        skill = next(s for s in later.json()["stats"]["skills"] if s["skill_name"] == "需求挖掘")
        self.assertEqual(skill["level"], 5)
        self.assertEqual(skill["last_updated"], response.json()[0]["last_updated"])
        other = self.client.get("/api/v1/users/me/profile", headers={"Authorization": f"Bearer {create_access_token('user-two')}"})
        self.assertEqual(next(s for s in other.json()["stats"]["skills"] if s["skill_name"] == "需求挖掘")["level"], 2)

    def test_invalid_skill_update_does_not_partially_commit(self):
        response = self.client.put("/api/v1/users/me/skills", headers=self.headers, json=[
            {"skill_name": "需求挖掘", "level": 5}, {"skill_name": "开场破冰", "level": 7},
        ])
        self.assertIn(response.status_code, (400, 422))
        later = self.client.get("/api/v1/users/me/profile", headers=self.headers)
        self.assertEqual(later.status_code, 200, later.text)
        self.assertEqual(next(s for s in later.json()["stats"]["skills"] if s["skill_name"] == "需求挖掘")["level"], 2)

    def test_protected_routes_reject_refresh_invalid_expired_and_inactive_tokens(self):
        from datetime import timedelta
        tokens = [create_refresh_token("user-one"), "invalid", create_access_token("user-one", timedelta(seconds=-5)), create_access_token("missing"), create_access_token("disabled")]
        for token in tokens:
            response = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertIn(response.status_code, (401, 403), response.text)

    def test_optional_auth_is_anonymous_only_when_credentials_absent(self):
        self.assertEqual(self.client.get("/optional").json(), {"user_id": None})
        authorized = self.client.get("/optional", headers=self.headers)
        self.assertEqual(authorized.status_code, 200, authorized.text)
        self.assertEqual(authorized.json(), {"user_id": "user-one"})
        for token in ("invalid", create_refresh_token("user-one"), create_access_token("disabled")):
            response = self.client.get("/optional", headers={"Authorization": f"Bearer {token}"})
            self.assertIn(response.status_code, (401, 403), response.text)

    def test_optional_auth_rejects_malformed_authorization_header(self):
        for value in ("Bearer", "Basic malformed"):
            self.assertEqual(self.client.get("/optional", headers={"Authorization": value}).status_code, 401)

    def test_signed_tokens_without_expiry_cannot_authorize(self):
        from jose import jwt
        token = jwt.encode({"sub": "user-one", "type": "access"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code, 401)

    def test_access_token_is_rejected_by_refresh_endpoint(self):
        response = self.client.post("/api/v1/auth/refresh", json={"refresh_token": create_access_token("user-one")})
        self.assertEqual(response.status_code, 401)


class TokenConfigurationTests(unittest.TestCase):
    def test_jwt_helpers_use_settings_expiry(self):
        before = int(time.time())
        with patch.dict(settings.__dict__, {"ACCESS_TOKEN_EXPIRE_MINUTES": 13, "REFRESH_TOKEN_EXPIRE_DAYS": 3}):
            access = decode_token(create_access_token("test"))
            refresh = decode_token(create_refresh_token("test"))
        self.assertAlmostEqual(access["exp"] - before, 780, delta=2)
        self.assertAlmostEqual(refresh["exp"] - before, 259200, delta=2)


if __name__ == "__main__":
    unittest.main()
