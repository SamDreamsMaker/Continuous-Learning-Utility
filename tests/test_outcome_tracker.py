"""Tests for orchestrator/outcome_tracker.py."""

import json
import os
import tempfile

import pytest

from orchestrator.outcome_tracker import (
    OutcomeTracker,
    extract_keywords,
    extract_tool_names,
)


# ---------------------------------------------------------------------------
# extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_tech_terms_extracted(self):
        kws = extract_keywords("fix the unity coroutine in player animation")
        assert "unity" in kws
        assert "coroutine" in kws
        assert "animation" in kws

    def test_stopwords_excluded(self):
        kws = extract_keywords("fix the bug in the file")
        assert "the" not in kws
        assert "in" not in kws

    def test_short_words_excluded(self):
        kws = extract_keywords("do it now")
        assert "do" not in kws
        assert "it" not in kws

    def test_long_unknown_words_included(self):
        kws = extract_keywords("refactor PlayerController movement")
        assert "playercontroller" in kws or "PlayerController".lower() in [k.lower() for k in kws]

    def test_max_20_keywords(self):
        long_text = " ".join(f"keyword{i}" for i in range(50))
        kws = extract_keywords(long_text)
        assert len(kws) <= 20

    def test_empty_string(self):
        assert extract_keywords("") == []

    def test_duplicates_not_returned(self):
        kws = extract_keywords("unity unity unity animation animation")
        assert kws.count("unity") == 1
        assert kws.count("animation") == 1


# ---------------------------------------------------------------------------
# extract_tool_names
# ---------------------------------------------------------------------------

class TestExtractToolNames:
    def test_extracts_tool_names_openai_format(self):
        messages = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "tool_calls": [{"name": "read_file", "id": "1"}]},
            {"role": "assistant", "tool_calls": [{"name": "write_file", "id": "2"}]},
        ]
        tools = extract_tool_names(messages)
        assert "read_file" in tools
        assert "write_file" in tools

    def test_extracts_function_format(self):
        messages = [
            {"role": "assistant", "tool_calls": [
                {"function": {"name": "think"}, "id": "3"}
            ]},
        ]
        tools = extract_tool_names(messages)
        assert "think" in tools

    def test_ignores_non_assistant_messages(self):
        messages = [
            {"role": "user", "tool_calls": [{"name": "read_file"}]},
            {"role": "tool", "tool_calls": [{"name": "write_file"}]},
        ]
        tools = extract_tool_names(messages)
        assert tools == []

    def test_no_duplicates(self):
        messages = [
            {"role": "assistant", "tool_calls": [{"name": "read_file"}]},
            {"role": "assistant", "tool_calls": [{"name": "read_file"}]},
        ]
        tools = extract_tool_names(messages)
        assert tools.count("read_file") == 1

    def test_empty_messages(self):
        assert extract_tool_names([]) == []


# ---------------------------------------------------------------------------
# OutcomeTracker
# ---------------------------------------------------------------------------

class TestOutcomeTracker:
    def _make_tracker(self, tmp_path):
        return OutcomeTracker(data_dir=str(tmp_path))

    def test_record_creates_file(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        tracker.record(
            task="fix the unity coroutine",
            tools_used=["read_file", "write_file"],
            files_modified=[{"relative": "Assets/Player.cs"}],
            tokens=1000,
            iterations=5,
            success=True,
        )
        jsonl = tmp_path / "outcomes.jsonl"
        assert jsonl.exists()
        lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_record_schema(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        tracker.record(
            task="fix the unity coroutine",
            tools_used=["read_file"],
            files_modified=[{"relative": "Assets/Player.cs"}],
            tokens=500,
            iterations=3,
            success=True,
            session_id="sess-001",
            project_name="unity",
            skill_names=["unity-support"],
        )
        line = (tmp_path / "outcomes.jsonl").read_text().strip()
        rec = json.loads(line)
        assert rec["task"] == "fix the unity coroutine"
        assert "unity" in rec["keywords"]
        assert rec["tokens"] == 500
        assert rec["iterations"] == 3
        assert rec["success"] is True
        assert rec["session_id"] == "sess-001"
        assert rec["project_name"] == "unity"
        assert "unity-support" in rec["skill_names"]
        assert ".cs" in rec["file_extensions"]

    def test_record_multiple(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        for i in range(5):
            tracker.record(
                task=f"task {i}",
                tools_used=[],
                files_modified=[],
                tokens=100 * i,
                iterations=i,
                success=(i % 2 == 0),
            )
        assert tracker.count() == 5

    def test_load_returns_records(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        for i in range(3):
            tracker.record(
                task=f"task {i}", tools_used=[], files_modified=[],
                tokens=0, iterations=0, success=True,
            )
        records = tracker.load()
        assert len(records) == 3

    def test_load_limit(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        for i in range(10):
            tracker.record(
                task=f"task {i}", tools_used=[], files_modified=[],
                tokens=0, iterations=0, success=True,
            )
        records = tracker.load(limit=3)
        assert len(records) == 3

    def test_count_empty(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        assert tracker.count() == 0

    def test_record_truncates_long_task(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        long_task = "x" * 500
        tracker.record(
            task=long_task, tools_used=[], files_modified=[],
            tokens=0, iterations=0, success=True,
        )
        rec = tracker.load()[0]
        assert len(rec["task"]) == 300

    def test_record_failure_does_not_raise(self, tmp_path):
        """Record with bad inputs must not propagate exceptions."""
        tracker = self._make_tracker(tmp_path)
        # files_modified with missing keys — should be handled gracefully
        tracker.record(
            task="test", tools_used=[], files_modified=[{}],
            tokens=0, iterations=0, success=True,
        )

    def test_load_missing_file_returns_empty(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        assert tracker.load() == []
