from __future__ import annotations

import copy
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from group_insight.history_store import HistoryStore
from group_insight.redaction import redact_report_document
from tests.test_history_center import history_document


class RedactionVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "history.sqlite3"
        self.original = history_document(self.root)

    def save(self, store, document):
        report_id = store.upsert_report(document)
        return store.get_report_detail(report_id)

    def redact(self, source, version):
        return redact_report_document(source, ["themes:0"], version=version,
            exports={"json": str(self.root / f"report-v{version}.json")})

    def test_branches_and_repeated_redaction_are_numbered_under_original(self):
        with HistoryStore(self.path) as store:
            self.assertEqual(self.save(store, self.original)["version_label"], "正常版 v1")
            first = self.redact(self.original, 2)
            self.assertEqual(self.save(store, first)["version_label"], "屏蔽版 v1.1")
            second = self.redact(self.original, 3)
            self.assertEqual(self.save(store, second)["version_label"], "屏蔽版 v1.2")
            third = self.redact(first, 4)
            self.assertEqual(self.save(store, third)["version_label"], "屏蔽版 v1.3")
            labels = {item["version"]: item["version_label"] for item in store.list_report_versions(self.original["metadata"]["report_id"])}
            self.assertEqual(labels, {4: "屏蔽版 v1.3", 3: "屏蔽版 v1.2", 2: "屏蔽版 v1.1", 1: "正常版 v1"})
            hits = store.search_history("清关", version_strategy="all")["items"]
            self.assertIn("屏蔽版 v1.2", {hit["version_label"] for hit in hits})

    def test_distinct_original_and_deleted_sibling_keep_existing_numbers(self):
        with HistoryStore(self.path) as store:
            self.save(store, self.original)
            first = self.redact(self.original, 2)
            self.save(store, first)
            second = self.redact(self.original, 3)
            self.save(store, second)
            original4 = history_document(self.root, version=4)
            self.assertEqual(self.save(store, original4)["version_label"], "正常版 v4")
            self.assertEqual(self.save(store, self.redact(original4, 5))["version_label"], "屏蔽版 v4.1")
            store.delete_report(first["metadata"]["report_id"])
            self.assertEqual(store.get_report_detail(second["metadata"]["report_id"])["version_label"], "屏蔽版 v1.2")
            self.assertEqual(self.save(store, self.redact(second, 6))["version_label"], "屏蔽版 v1.3")
            # 重复索引不能消耗屏蔽编号或改变已展示编号。
            self.assertEqual(self.save(store, second)["version_label"], "屏蔽版 v1.2")
            store.delete_report(self.original["metadata"]["report_id"])
            self.assertEqual(store.get_report_detail(second["metadata"]["report_id"])["version_label"], "屏蔽版 v1.2")

    def test_exported_numbers_survive_missing_source_and_anonymous_names_source(self):
        first = self.redact(self.original, 2)
        first["metadata"].update(redaction_base_version=1, redaction_revision=4)
        with HistoryStore(self.path) as store:
            self.assertEqual(self.save(store, first)["version_label"], "屏蔽版 v1.4")
            anonymous = copy.deepcopy(first)
            anonymous["metadata"].update(report_id="anonymous-example", report_variant="anonymous", source_report_id=first["metadata"]["report_id"])
            detail = self.save(store, anonymous)
            self.assertEqual(detail["version_label"], "匿名版 · 来源屏蔽版 v1.4")
            self.assertEqual(detail["source_version_label"], "屏蔽版 v1.4")

    def legacy_database(self):
        documents = [self.original, self.redact(self.original, 2), self.redact(self.original, 3)]
        with HistoryStore(self.path) as store:
            for document in documents:
                Path(document["metadata"]["exports"]["json"]).write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
                store.upsert_report(document)
            with store.connection:
                for column in ("parent_report_id", "redaction_base_version", "redaction_revision"):
                    store.connection.execute(f"ALTER TABLE reports DROP COLUMN {column}")
                store.connection.execute("PRAGMA user_version=5")
        return documents

    def test_v5_migration_backfills_labels_without_changing_reports_and_keeps_verified_backup(self):
        documents = self.legacy_database()
        before = {path: path.read_bytes() for path in self.root.glob("*.json")}
        with HistoryStore(self.path) as store:
            self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(store.get_report_detail(documents[1]["metadata"]["report_id"])["version_label"], "屏蔽版 v1.1")
            self.assertEqual(store.get_report_detail(documents[2]["metadata"]["report_id"])["version_label"], "屏蔽版 v1.2")
        backups = list(self.root.glob("*.before-v6-*.bak"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(backup.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT count(*) FROM reports").fetchone()[0], 3)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        with HistoryStore(self.path):
            pass
        self.assertEqual(len(list(self.root.glob("*.before-v6-*.bak"))), 1)

    def test_missing_json_identifies_masked_report_without_guessing_source(self):
        documents = self.legacy_database()
        Path(documents[1]["metadata"]["exports"]["json"]).unlink()
        with HistoryStore(self.path) as store:
            detail = store.get_report_detail(documents[1]["metadata"]["report_id"])
            self.assertEqual(detail["version_label"], "屏蔽版 v2")
            self.assertTrue(detail["is_redacted"])

    def test_import_old_reports_uses_numeric_revision_order(self):
        documents = [self.original, self.redact(self.original, 2), self.redact(self.original, 10)]
        for document in documents:
            version = document["metadata"]["version"]
            path = self.root / "群聊" / "报告数据" / f"2026-08-31报告数据_v{version}" / f"群聊_群聊总结_v{version}.json"
            path.parent.mkdir(parents=True)
            document["metadata"]["exports"]["json"] = str(path)
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        with HistoryStore(self.path) as store:
            self.assertEqual(store.import_export_root(self.root)["imported"], 3)
            self.assertEqual(store.get_report_detail(documents[1]["metadata"]["report_id"])["version_label"], "屏蔽版 v1.1")
            self.assertEqual(store.get_report_detail(documents[2]["metadata"]["report_id"])["version_label"], "屏蔽版 v1.2")

    def test_failed_v6_migration_rolls_back_and_preserves_v5_backup(self):
        self.legacy_database()
        def fail(connection):
            connection.execute("ALTER TABLE reports ADD COLUMN parent_report_id TEXT NOT NULL DEFAULT ''")
            raise RuntimeError("failed-v6")
        with patch.object(HistoryStore, "_migrate_v5_to_v6", side_effect=fail), self.assertRaisesRegex(RuntimeError, "failed-v6"):
            HistoryStore(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertNotIn("parent_report_id", {row[1] for row in connection.execute("PRAGMA table_info(reports)")})
            self.assertEqual(connection.execute("SELECT count(*) FROM reports").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
