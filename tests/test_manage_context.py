"""Tests for ManageContextTool: list/add/disable/delete, edge cases."""

import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.manage_context import ManageContextTool
from orchestrator.context_store import ContextStore


@pytest.fixture
def tool(tmp_path):
    t = ManageContextTool()
    t._context_store = ContextStore(project_path=str(tmp_path))
    return t


@pytest.fixture
def project_path():
    return "/fake/project"


class TestManageContextNoStore:

    def test_no_store_returns_error(self, project_path):
        tool = ManageContextTool()
        result = tool.execute({"action": "list"}, project_path)
        assert "not available" in result


class TestManageContextList:

    def test_list_empty(self, tool, project_path):
        result = tool.execute({"action": "list"}, project_path)
        assert "No context rules" in result

    def test_list_with_items(self, tool, project_path):
        tool._context_store.add_item("rule1", "Do X")
        tool._context_store.add_item("rule2", "Do Y", scope="coder")
        result = tool.execute({"action": "list"}, project_path)
        assert "rule1" in result
        assert "rule2" in result
        assert "[coder]" in result


class TestManageContextAdd:

    def test_add_success(self, tool, project_path):
        result = tool.execute(
            {"action": "add", "name": "my_rule", "content": "Always do X"},
            project_path,
        )
        assert "added" in result
        assert "my_rule" in result

    def test_add_with_scope(self, tool, project_path):
        result = tool.execute(
            {"action": "add", "name": "r", "content": "c", "scope": "tester"},
            project_path,
        )
        assert "tester" in result

    def test_add_missing_name(self, tool, project_path):
        result = tool.execute({"action": "add", "content": "c"}, project_path)
        assert "Error" in result

    def test_add_missing_content(self, tool, project_path):
        result = tool.execute({"action": "add", "name": "r"}, project_path)
        assert "Error" in result


class TestManageContextDisable:

    def test_disable_success(self, tool, project_path):
        tool._context_store.add_item("rule1", "c")
        result = tool.execute({"action": "disable", "name": "rule1"}, project_path)
        assert "disabled" in result
        assert not tool._context_store.get_item_by_name("rule1").enabled

    def test_disable_already_disabled(self, tool, project_path):
        item = tool._context_store.add_item("rule1", "c")
        tool._context_store.update_item(item.id, enabled=False)
        result = tool.execute({"action": "disable", "name": "rule1"}, project_path)
        assert "already disabled" in result

    def test_disable_not_found(self, tool, project_path):
        result = tool.execute({"action": "disable", "name": "nope"}, project_path)
        assert "No context rule found" in result

    def test_disable_missing_name(self, tool, project_path):
        result = tool.execute({"action": "disable"}, project_path)
        assert "Error" in result


class TestManageContextDelete:

    def test_delete_success(self, tool, project_path):
        tool._context_store.add_item("rule1", "c")
        result = tool.execute({"action": "delete", "name": "rule1"}, project_path)
        assert "deleted" in result
        assert tool._context_store.list_items() == []

    def test_delete_not_found(self, tool, project_path):
        result = tool.execute({"action": "delete", "name": "nope"}, project_path)
        assert "No context rule found" in result


class TestManageContextUnknownAction:

    def test_unknown_action(self, tool, project_path):
        result = tool.execute({"action": "bogus"}, project_path)
        assert "Unknown action" in result
