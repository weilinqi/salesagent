"""Knowledge routes use real JWTs, isolated SQL sessions, and real PDF parsing."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database
from app.core.security import create_access_token, create_refresh_token
from app.models.user import User

# Load the real router without the API package's unrelated PDF/news integrations.
# The route functions and their authentication/database dependencies stay real.
_spec = importlib.util.spec_from_file_location(
    "knowledge_api_under_test", Path(__file__).resolve().parents[1] / "app/api/v1/knowledge.py")
knowledge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(knowledge)


class FakeCollection:
    """Only the external persistent vector boundary is replaced."""
    def __init__(self):
        self.chunks = {}
        self.fail = False

    def upsert(self, ids, documents, embeddings, metadatas):
        if self.fail:
            raise RuntimeError("vector failed at C:/private/server/secrets.pdf")
        for cid, text, embedding, metadata in zip(ids, documents, embeddings, metadatas):
            self.chunks[cid] = (text, embedding, metadata)

    def delete(self, where):
        for cid in list(self.chunks):
            if self.chunks[cid][2].get("document_id") == where.get("document_id"):
                del self.chunks[cid]

    def count(self):
        return len(self.chunks)


class FakeVectors:
    def __init__(self):
        self._collection = FakeCollection()

    def _connect(self):
        pass

    def count(self):
        return {"total": self._collection.count()}

    def search(self, **kwargs):
        return []


class FakeEmbedding:
    async def embed_text(self, text):
        return [1.0, 0.0]

    async def embed_with_metadata(self, chunks, source_name=""):
        return [{**chunk, "source": source_name, "embedding": [1.0, 0.0]}
                for chunk in chunks]


def write_pdf(path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td (" + b"Sales knowledge for customers. " * 6 + b") Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": "Sales fixture"})
    writer.write(path)


class KnowledgeRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "raw"
        self.root.mkdir()
        write_pdf(self.root / "sales.pdf")
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "test.db"),
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        database.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([User(id="reader", email="reader@test.example", username="reader", hashed_password="unused"),
                        User(id="admin", email="admin@test.example", username="admin", hashed_password="unused", role="admin"),
                        User(id="inactive", email="inactive@test.example", username="inactive", hashed_password="unused", is_active=False),
                        User(id="super", email="super@test.example", username="super", hashed_password="unused", is_superuser=True)])
            db.commit()
        self.vectors = FakeVectors()
        for context in [patch.object(database, "SessionLocal", self.sessions),
                        patch.object(knowledge, "SessionLocal", self.sessions, create=True),
                        patch.object(knowledge, "settings", SimpleNamespace(KNOWLEDGE_DATA_DIR=str(self.root)), create=True),
                        patch.object(knowledge, "_vector_store", self.vectors),
                        patch.object(knowledge, "_embedding_service", FakeEmbedding())]:
            context.start()
            self.addCleanup(context.stop)
        self.app = FastAPI()
        self.app.include_router(knowledge.router, prefix="/api/v1")
        def get_db():
            with self.sessions() as db:
                yield db
        self.app.dependency_overrides[database.get_db] = get_db
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def headers(self, user="admin"):
        return {"Authorization": "Bearer " + create_access_token(user)}

    def test_every_knowledge_route_requires_authentication(self):
        routes = [("GET", "/documents", None), ("GET", "/documents/missing", None),
                  ("GET", "/stats", None), ("POST", "/search", {"query": "sales"}),
                  ("POST", "/ingest", {"file_path": "sales.pdf", "category": "general"}),
                  ("POST", "/ingest-all", None),
                  ("POST", "/spin/questions", {"customer_industry": "tech", "customer_scale": "small", "pain_points": []}),
                  ("POST", "/conversation/context", {"scenario_type": "sales", "customer_profile": {}})]
        for method, route, body in routes:
            with self.subTest(route=route):
                response = self.client.request(method, "/api/v1/knowledge" + route, json=body)
                self.assertEqual(response.status_code, 401)

    def test_refresh_and_inactive_tokens_cannot_read_knowledge(self):
        for token, expected in [(create_refresh_token("reader"), 401), (create_access_token("inactive"), 403)]:
            response = self.client.get("/api/v1/knowledge/documents", headers={"Authorization": "Bearer " + token})
            self.assertEqual(response.status_code, expected)

    def test_ingestion_requires_admin_but_readers_can_list(self):
        for route in ["/ingest", "/ingest-all"]:
            response = self.client.post("/api/v1/knowledge" + route, headers=self.headers("reader"),
                                        json={"file_path": "sales.pdf", "category": "general"})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/v1/knowledge/documents", headers=self.headers("reader")).status_code, 200)

    def test_pdf_ingestion_completes_and_survives_fresh_sessions(self):
        response = self.client.post("/api/v1/knowledge/ingest", headers=self.headers(),
                                    json={"file_path": "sales.pdf", "category": "general"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "queued")
        doc_id = response.json()["document_id"]
        detail = self.client.get("/api/v1/knowledge/documents/" + doc_id, headers=self.headers("reader"))
        self.assertEqual(detail.json()["status"], "completed")
        self.assertGreater(detail.json()["chunk_count"], 0)
        self.assertNotIn("file_path", detail.json())
        self.assertNotIn(str(self.root), detail.text)
        from app.models.knowledge import KnowledgeDocument
        with self.sessions() as db:
            record = db.get(KnowledgeDocument, doc_id)
            self.assertEqual(record.status, "completed")
            self.assertEqual(record.chunk_count, detail.json()["chunk_count"])
        self.assertEqual(self.client.get("/api/v1/knowledge/documents", headers=self.headers()).json()[0]["id"], doc_id)

    def test_failed_vector_write_is_persisted_without_server_path(self):
        self.vectors._collection.fail = True
        with self.assertLogs(knowledge.logger, level="ERROR"):
            response = self.client.post("/api/v1/knowledge/ingest", headers=self.headers(),
                                        json={"file_path": "sales.pdf", "category": "general"})
        self.assertEqual(response.status_code, 200)
        detail = self.client.get("/api/v1/knowledge/documents/" + response.json()["document_id"], headers=self.headers())
        self.assertEqual(detail.json()["status"], "failed")
        self.assertEqual(detail.json()["chunk_count"], 0)
        self.assertTrue(detail.json()["error"])
        self.assertNotIn("private", detail.text)
        self.assertNotIn("secrets.pdf", detail.text)

    def test_search_does_not_expose_vector_server_paths_or_errors(self):
        result = {"id": "legacy_chunk", "text": "Customer questions", "source": "C:/private/server/book.pdf",
                  "score": 0.8, "metadata": {"full_path": "C:/private/server/book.pdf", "category": "spin"}}
        with patch.object(self.vectors, "search", return_value=[result]):
            response = self.client.post("/api/v1/knowledge/search", headers=self.headers("reader"), json={"query": "sales"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["results"][0]["source"], "book.pdf")
            self.assertNotIn("private", response.text)
        with patch.object(self.vectors, "search", side_effect=RuntimeError("C:/private/server/vector.db failed")):
            with self.assertLogs(knowledge.logger, level="ERROR"):
                response = self.client.post("/api/v1/knowledge/search", headers=self.headers("reader"), json={"query": "sales"})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private", response.text)

    def test_rejects_outside_traversal_missing_non_pdf_and_directory(self):
        (Path(self.temp.name) / "outside.pdf").write_bytes(b"not a pdf")
        (self.root / "notes.txt").write_text("notes")
        (self.root / "directory.pdf").mkdir()
        for requested, expected in [("../outside.pdf", 400), (str(Path(self.temp.name) / "outside.pdf"), 400),
                                    ("missing.pdf", 404), ("notes.txt", 400), ("directory.pdf", 400)]:
            with self.subTest(path=requested):
                response = self.client.post("/api/v1/knowledge/ingest", headers=self.headers(),
                                            json={"file_path": requested, "category": "general"})
                self.assertEqual(response.status_code, expected)
                self.assertNotIn(str(self.root), response.text)
                self.assertNotIn("outside.pdf", response.text)

    def test_ingest_all_uses_configured_directory_and_persists_records(self):
        write_pdf(self.root / "SPIN.PDF")
        response = self.client.post("/api/v1/knowledge/ingest-all", headers=self.headers("super"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)
        docs = self.client.get("/api/v1/knowledge/documents", headers=self.headers()).json()
        self.assertEqual(len(docs), 2)
        self.assertEqual({doc["status"] for doc in docs}, {"completed"})
        self.assertEqual({doc["category"] for doc in docs}, {"general", "spin"})

    def test_symlink_pointing_outside_root_is_rejected(self):
        outside_dir = Path(self.temp.name) / "outside"
        outside_dir.mkdir()
        outside = outside_dir / "outside.pdf"
        write_pdf(outside)
        try:
            (self.root / "linked.pdf").symlink_to(outside)
            requested = "linked.pdf"
        except OSError as exc:
            if os.name != "nt":
                self.skipTest("Host cannot create symlinks: " + str(exc))
            # NTFS junctions do not require the symlink privilege. They exercise
            # the same canonical containment check with a real redirected path.
            junction = self.root / "linked"
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
                                    capture_output=True)
            if result.returncode:
                self.skipTest("Host cannot create symlinks or directory junctions")
            self.addCleanup(lambda: os.rmdir(junction))
            requested = "linked/outside.pdf"
        response = self.client.post("/api/v1/knowledge/ingest", headers=self.headers(),
                                    json={"file_path": requested, "category": "general"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(str(outside), response.text)

    def test_restart_recovery_marks_unfinished_tasks_failed(self):
        from app.models.knowledge import KnowledgeDocument
        recover_interrupted_ingestions = knowledge.recover_interrupted_ingestions
        with self.sessions() as db:
            db.add_all([KnowledgeDocument(id="queued", name="queued.pdf", file_path="queued.pdf", category="general", status="queued"),
                        KnowledgeDocument(id="running", name="running.pdf", file_path="running.pdf", category="general", status="processing"),
                        KnowledgeDocument(id="completed", name="done.pdf", file_path="done.pdf", category="general", status="completed", chunk_count=1)])
            db.commit()
        self.vectors._collection.upsert(
            ids=["queued_0", "running_0", "completed_0"], documents=["q", "r", "c"],
            embeddings=[[1.0, 0.0]] * 3,
            metadatas=[{"document_id": "queued"}, {"document_id": "running"}, {"document_id": "completed"}])
        self.assertEqual(recover_interrupted_ingestions(), 2)
        self.assertEqual(set(self.vectors._collection.chunks), {"completed_0"})
        with self.sessions() as db:
            self.assertEqual(db.get(KnowledgeDocument, "queued").status, "failed")
            self.assertEqual(db.get(KnowledgeDocument, "running").status, "failed")
            self.assertEqual(db.get(KnowledgeDocument, "completed").status, "completed")
        self.assertEqual(recover_interrupted_ingestions(), 0)

    def test_restart_recovery_cleanup_failure_preserves_unfinished_sql_for_retry(self):
        from app.models.knowledge import KnowledgeDocument
        with self.sessions() as db:
            db.add(KnowledgeDocument(id="running", name="running.pdf", file_path="running.pdf", category="general", status="processing"))
            db.commit()
        self.vectors._collection.upsert(ids=["running_0"], documents=["partial knowledge"],
                                        embeddings=[[1.0, 0.0]], metadatas=[{"document_id": "running"}])
        with patch.object(self.vectors._collection, "delete", side_effect=RuntimeError("external vector cleanup unavailable")):
            with self.assertLogs(knowledge.logger, level="ERROR"):
                with self.assertRaises(RuntimeError):
                    knowledge.recover_interrupted_ingestions()
        with self.sessions() as db:
            self.assertEqual(db.get(KnowledgeDocument, "running").status, "processing")
        self.assertEqual(set(self.vectors._collection.chunks), {"running_0"})
        self.assertEqual(knowledge.recover_interrupted_ingestions(), 1)
        self.assertEqual(self.vectors._collection.chunks, {})

    def test_restart_without_unfinished_tasks_does_not_connect_vectors(self):
        with patch.object(self.vectors, "_connect", side_effect=RuntimeError("vector service is offline")):
            self.assertEqual(knowledge.recover_interrupted_ingestions(), 0)

    def test_markdown_loader_uses_same_configured_raw_directory(self):
        from app.services.knowledge import knowledge_loader
        markdown = self.root / "MinerU_markdown_07-SPIN销售巨人_fixture.md"
        markdown.write_text("# Buying questions\n" + "Understand customer needs and sales challenges. " * 5, encoding="utf-8")
        class LoaderVectors:
            _collection = SimpleNamespace(count=lambda: 0)
            def __init__(self):
                self.chunks = []
            def _connect(self):
                pass
            def add_chunks(self, chunks):
                self.chunks.extend(chunks)
                return True
        vectors = LoaderVectors()
        with patch.object(knowledge_loader, "settings", SimpleNamespace(KNOWLEDGE_DATA_DIR=str(self.root)), create=True), \
                patch.object(knowledge_loader, "get_vector_store", return_value=vectors), \
                patch.object(knowledge_loader.KnowledgeLoader, "_instance", None), \
                patch.object(knowledge_loader.KnowledgeLoader, "_loaded", False):
            loader = knowledge_loader.KnowledgeLoader()
            self.assertGreater(len(vectors.chunks), 0)
            self.assertEqual(vectors.chunks[0].source, "SPIN销售巨人")


if __name__ == "__main__":
    unittest.main()
