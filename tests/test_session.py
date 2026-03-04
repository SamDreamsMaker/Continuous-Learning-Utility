"""Tests for SessionManager: save/load/list/delete/rename, ID generation, path traversal."""

import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator.session import SessionManager


@pytest.fixture
def mgr(tmp_path):
    return SessionManager(sessions_dir=str(tmp_path))


class TestSessionSaveLoad:

    def test_save_and_load(self, mgr):
        mgr.save("test_001", messages=[{"role": "user", "content": "hi"}],
                  project_path="/proj", task="do stuff",
                  budget_state={"raw_total_tokens": 100},
                  files_modified=[])
        session = mgr.load("test_001")
        assert session is not None
        assert session["id"] == "test_001"
        assert session["task"] == "do stuff"
        assert session["budget"]["raw_total_tokens"] == 100
        assert len(session["messages"]) == 1

    def test_load_nonexistent(self, mgr):
        assert mgr.load("nope") is None

    def test_save_with_name(self, mgr):
        mgr.save("s1", [], "/proj", "task", {}, [], name="My Session")
        session = mgr.load("s1")
        assert session["name"] == "My Session"


class TestSessionList:

    def test_list_sessions(self, mgr):
        mgr.save("s1", [], "/proj", "task1", {"raw_total_tokens": 10}, [])
        mgr.save("s2", [], "/proj", "task2", {"raw_total_tokens": 20}, [])
        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        # Each summary has budget
        ids = {s["id"] for s in sessions}
        assert "s1" in ids
        assert "s2" in ids

    def test_list_sessions_filter_project(self, mgr):
        mgr.save("s1", [], "/proj_a", "task1", {}, [])
        mgr.save("s2", [], "/proj_b", "task2", {}, [])
        sessions = mgr.list_sessions(project_path="/proj_a")
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s1"

    def test_list_sessions_empty(self, mgr):
        assert mgr.list_sessions() == []


class TestSessionDeleteRename:

    def test_delete(self, mgr):
        mgr.save("s1", [], "/p", "t", {}, [])
        assert mgr.delete("s1") is True
        assert mgr.load("s1") is None

    def test_delete_nonexistent(self, mgr):
        assert mgr.delete("nope") is False

    def test_rename(self, mgr):
        mgr.save("s1", [], "/p", "t", {}, [])
        assert mgr.rename("s1", "New Name") is True
        session = mgr.load("s1")
        assert session["name"] == "New Name"

    def test_rename_nonexistent(self, mgr):
        assert mgr.rename("nope", "x") is False


class TestSessionGenerateId:

    def test_id_format(self, mgr):
        sid = mgr.generate_id()
        # Format: YYYYMMDD_HHMMSS_hexhex
        parts = sid.split("_")
        assert len(parts) == 3
        assert len(parts[0]) == 8  # date
        assert len(parts[1]) == 6  # time
        assert len(parts[2]) == 6  # hex

    def test_ids_unique(self, mgr):
        ids = {mgr.generate_id() for _ in range(50)}
        assert len(ids) == 50  # all unique thanks to random suffix


class TestSessionPathTraversal:

    def test_traversal_blocked_on_save(self, mgr):
        with pytest.raises(ValueError):
            mgr.save("../../etc/passwd", [], "/p", "t", {}, [])

    def test_traversal_blocked_on_load(self, mgr):
        with pytest.raises(ValueError):
            mgr.load("../secret")

    def test_traversal_blocked_on_delete(self, mgr):
        with pytest.raises(ValueError):
            mgr.delete("..\\windows\\system32")

    def test_traversal_blocked_on_rename(self, mgr):
        with pytest.raises(ValueError):
            mgr.rename("../../../etc/shadow", "x")

    def test_valid_ids_allowed(self, mgr):
        mgr.save("valid-id_123", [], "/p", "t", {}, [])
        assert mgr.load("valid-id_123") is not None
