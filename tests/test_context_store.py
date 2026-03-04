"""Tests for ContextStore: CRUD, scopes, persistence, edge cases."""

import json
import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator.context_store import ContextStore, ContextItem, VALID_SCOPES


@pytest.fixture
def store(tmp_path):
    return ContextStore(project_path=str(tmp_path))


class TestContextItem:

    def test_to_dict_roundtrip(self):
        item = ContextItem(id="abc", name="test", content="hello", scope="coder")
        d = item.to_dict()
        restored = ContextItem.from_dict(d)
        assert restored.id == "abc"
        assert restored.name == "test"
        assert restored.content == "hello"
        assert restored.scope == "coder"
        assert restored.enabled is True

    def test_from_dict_invalid_scope(self):
        item = ContextItem.from_dict({"id": "1", "name": "x", "content": "y", "scope": "invalid"})
        assert item.scope == "always"

    def test_from_dict_missing_fields(self):
        item = ContextItem.from_dict({})
        assert item.id == ""
        assert item.name == ""
        assert item.enabled is True
        assert item.scope == "always"


class TestContextStoreCRUD:

    def test_add_and_list(self, store):
        assert store.list_items() == []
        item = store.add_item("rule1", "Do X")
        items = store.list_items()
        assert len(items) == 1
        assert items[0].name == "rule1"
        assert items[0].content == "Do X"
        assert items[0].enabled is True
        assert items[0].id == item.id

    def test_add_strips_name(self, store):
        item = store.add_item("  padded  ", "content")
        assert item.name == "padded"

    def test_add_invalid_scope_falls_back(self, store):
        item = store.add_item("r", "c", scope="bogus")
        assert item.scope == "always"

    def test_update_item(self, store):
        item = store.add_item("r", "c")
        updated = store.update_item(item.id, name="new_name", enabled=False)
        assert updated.name == "new_name"
        assert updated.enabled is False

    def test_update_nonexistent(self, store):
        assert store.update_item("nope", name="x") is None

    def test_update_scope_validation(self, store):
        item = store.add_item("r", "c", scope="coder")
        store.update_item(item.id, scope="invalid")
        assert store.list_items()[0].scope == "coder"  # unchanged

    def test_delete_item(self, store):
        item = store.add_item("r", "c")
        assert store.delete_item(item.id) is True
        assert store.list_items() == []

    def test_delete_nonexistent(self, store):
        assert store.delete_item("nope") is False

    def test_get_item_by_name(self, store):
        store.add_item("MyRule", "c")
        assert store.get_item_by_name("myrule") is not None  # case-insensitive
        assert store.get_item_by_name("  MyRule  ") is not None  # strips
        assert store.get_item_by_name("other") is None


class TestContextStorePersistence:

    def test_persists_to_disk(self, tmp_path):
        store1 = ContextStore(project_path=str(tmp_path))
        store1.add_item("rule1", "content1")
        store1.add_item("rule2", "content2")

        store2 = ContextStore(project_path=str(tmp_path))
        items = store2.list_items()
        assert len(items) == 2
        assert items[0].name == "rule1"

    def test_corrupted_file(self, tmp_path):
        ctx_dir = tmp_path / ".clu"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "user-context.json").write_text("not json", encoding="utf-8")
        store = ContextStore(project_path=str(tmp_path))
        assert store.list_items() == []  # graceful fallback


class TestContextStoreScopes:

    def test_get_active_text_always(self, store):
        store.add_item("rule1", "Always do X")
        text = store.get_active_text()
        assert "Always do X" in text

    def test_get_active_text_role_filter(self, store):
        store.add_item("coding", "Use PascalCase", scope="coder")
        store.add_item("general", "Be concise", scope="always")
        text = store.get_active_text(role="coder")
        assert "PascalCase" in text
        assert "Be concise" in text

    def test_get_active_text_wrong_role(self, store):
        store.add_item("coding", "Use PascalCase", scope="coder")
        text = store.get_active_text(role="tester")
        assert "PascalCase" not in text

    def test_get_active_text_disabled_excluded(self, store):
        item = store.add_item("rule", "content")
        store.update_item(item.id, enabled=False)
        assert store.get_active_text() == ""

    def test_get_active_text_empty(self, store):
        assert store.get_active_text() == ""
