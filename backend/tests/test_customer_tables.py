"""Regression tests for dynamic customer-table imports and review states."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "customer-table-test-secret-longer-than-thirty-two")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.customers import router, _batch_delete_rows, _confirm_all_uncertain
from app.core.security import create_access_token
from app.database import Base, get_db
from app.models import CustomerTable, CustomerTableRow, User
from app.services.customer_tables import analyze_table


class CustomerTableServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_headerless_phone_column_is_inferred(self):
        result = await analyze_table(
            "phones.csv",
            "13812345678\n13987654321\n".encode("utf-8"),
            use_ai=False,
        )
        self.assertEqual(result["columns"][0]["semantic_type"], "phone")
        self.assertIsNone(result["columns"][0]["source_header"])
        self.assertGreater(result["columns"][0]["confidence"], 0.9)

    async def test_xlsx_header_and_invalid_phone_cell_are_detected(self):
        from io import BytesIO
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "客户列表"
        sheet.append(["客户名单"])
        sheet.append(["日期", "姓名", "电话", "金额"])
        sheet.append(["2026-11-01", "张三", "13812345678", "100"])
        sheet.append(["2026-11-02", "李四", "请见微信", "200"])
        buffer = BytesIO()
        workbook.save(buffer)
        result = await analyze_table("customers.xlsx", buffer.getvalue(), use_ai=False)
        self.assertEqual(result["name"], "客户名单")
        phone_column = next(column for column in result["columns"] if column["label"] == "电话")
        self.assertEqual(phone_column["semantic_type"], "phone")
        self.assertEqual(len(result["rows"][0]["uncertain"]), 0)
        self.assertTrue(any(item["column_key"] == phone_column["key"] for item in result["rows"][1]["uncertain"]))
    async def test_embedded_customer_fields_are_split(self):
        contents = (
            "客户姓名：张三，客户电话：13812345678，销售经理\n"
            "客户姓名：李四，客户电话：13987654321，采购主管\n"
        ).encode("utf-8")
        result = await analyze_table("embedded.csv", contents, use_ai=False)
        labels = [column["label"] for column in result["columns"]]
        self.assertIn("客户电话", labels)
        phone_column = next(column for column in result["columns"] if column["label"] == "客户电话")
        self.assertEqual(result["rows"][0]["cells"][phone_column["key"]], "13812345678")


class CustomerTableApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            "sqlite:///" + str(Path(self.tmp.name) / "test.db"),
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.user_id = str(uuid.uuid4())
        self.other_id = str(uuid.uuid4())
        with self.sessions() as db:
            db.add_all([
                User(id=self.user_id, email="one@example.com", username="one", hashed_password="unused"),
                User(id=self.other_id, email="two@example.com", username="two", hashed_password="unused"),
            ])
            db.commit()

        def database():
            with self.sessions() as db:
                yield db

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def headers(self, user_id):
        return {"Authorization": "Bearer " + create_access_token(user_id)}

    def _import_phone_table(self):
        with patch(
            "app.services.customer_tables._refine_with_llm",
            new=AsyncMock(side_effect=lambda columns, *_: columns),
        ):
            response = self.client.post(
                "/api/v1/customer-tables/import",
                files={"file": ("phones.csv", b"13812345678\n13987654321\n", "text/csv")},
                headers=self.headers(self.user_id),
            )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_import_edit_confirm_delete_and_ownership(self):
        imported = self._import_phone_table()
        table_id = imported["id"]
        row = imported["rows"][0]
        row_id = row["id"]
        self.assertEqual(imported["columns"][0]["semantic_type"], "phone")

        with self.sessions() as db:
            record = db.get(CustomerTableRow, row_id)
            record.uncertain = [{
                "column_key": imported["columns"][0]["key"],
                "label": "电话",
                "value": "13812345678",
                "reason": "需要确认",
                "reviewed": False,
            }]
            db.commit()

        updated = self.client.patch(
            f"/api/v1/customer-tables/{table_id}/rows/{row_id}",
            json={
                "cells": {imported["columns"][0]["key"]: "13800000000"},
                "confirm_all": True,
            },
            headers=self.headers(self.user_id),
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["cells"][imported["columns"][0]["key"]], "13800000000")
        self.assertTrue(updated.json()["uncertain"][0]["reviewed"])

        self.assertEqual(
            self.client.get(f"/api/v1/customer-tables/{table_id}", headers=self.headers(self.other_id)).status_code,
            404,
        )
        deleted = self.client.delete(
            f"/api/v1/customer-tables/{table_id}", headers=self.headers(self.user_id)
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        with self.sessions() as db:
            self.assertIsNone(db.get(CustomerTable, table_id))


    def test_batch_helpers_confirm_and_delete_rows(self):
        table_id = str(uuid.uuid4())
        row_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        with self.sessions() as db:
            table = CustomerTable(
                id=table_id,
                user_id=self.user_id,
                name="批量测试",
                columns=[{"key": "col_1", "label": "电话", "semantic_type": "phone", "confidence": 1}],
                row_count=2,
            )
            db.add(table)
            for position, row_id in enumerate(row_ids, start=1):
                db.add(CustomerTableRow(
                    id=row_id,
                    table_id=table_id,
                    position=position,
                    cells={"col_1": f"1380000000{position}"},
                    original_cells={},
                    uncertain=[{
                        "column_key": "col_1",
                        "label": "电话",
                        "value": f"1380000000{position}",
                        "reason": "需要确认",
                        "reviewed": False,
                    }],
                ))
            db.commit()
            table = db.get(CustomerTable, table_id)
            self.assertEqual(_confirm_all_uncertain(db, table), 2)
            self.assertTrue(all(item["reviewed"] for row in table.rows for item in row.uncertain))
            result = _batch_delete_rows(db, table, row_ids)
            self.assertEqual(result.deleted_count, 2)
            self.assertEqual(result.remaining_rows, 0)
            self.assertEqual(db.query(CustomerTableRow).filter(CustomerTableRow.table_id == table_id).count(), 0)
    def test_batch_confirm_and_batch_delete_are_transactional_and_owned(self):
        imported = self._import_phone_table()
        table_id = imported["id"]
        row_ids = [row["id"] for row in imported["rows"]]
        column_key = imported["columns"][0]["key"]
        with self.sessions() as db:
            for row_id in row_ids:
                row = db.get(CustomerTableRow, row_id)
                row.uncertain = [{
                    "column_key": column_key,
                    "label": "电话",
                    "value": row.cells[column_key],
                    "reason": "需要确认",
                    "reviewed": False,
                }]
            db.commit()

        denied = self.client.post(
            f"/api/v1/customer-tables/{table_id}/uncertain/confirm-all",
            headers=self.headers(self.other_id),
        )
        self.assertEqual(denied.status_code, 404)

        confirmed = self.client.post(
            f"/api/v1/customer-tables/{table_id}/uncertain/confirm-all",
            headers=self.headers(self.user_id),
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json(), {"confirmed_count": 2, "remaining_count": 0})
        with self.sessions() as db:
            for row_id in row_ids:
                row = db.get(CustomerTableRow, row_id)
                self.assertTrue(row.uncertain[0]["reviewed"])

        denied_delete = self.client.post(
            f"/api/v1/customer-tables/{table_id}/rows/batch-delete",
            json={"row_ids": row_ids},
            headers=self.headers(self.other_id),
        )
        self.assertEqual(denied_delete.status_code, 404)

        deleted = self.client.post(
            f"/api/v1/customer-tables/{table_id}/rows/batch-delete",
            json={"row_ids": row_ids},
            headers=self.headers(self.user_id),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json(), {"deleted_count": 2, "remaining_rows": 0})
        with self.sessions() as db:
            self.assertEqual(db.query(CustomerTableRow).filter(CustomerTableRow.table_id == table_id).count(), 0)
            self.assertEqual(db.get(CustomerTable, table_id).row_count, 0)


if __name__ == "__main__":
    unittest.main()