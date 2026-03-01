"""Tests for skills/pattern_analyzer.py."""

import pytest

from skills.pattern_analyzer import PatternAnalyzer, SkillCandidate, _jaccard, build_existing_skill_keywords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_outcomes(n: int, keywords: list, success: bool = True) -> list[dict]:
    return [
        {
            "ts": 1700000000.0 + i,
            "task": f"task {i}",
            "keywords": keywords,
            "tools_used": ["read_file", "write_file"],
            "file_extensions": [".cs"],
            "tokens": 1000,
            "iterations": 5,
            "success": success,
            "session_id": f"s{i}",
            "project_name": "unity",
            "skill_names": [],
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Jaccard
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        a = frozenset(["unity", "coroutine"])
        assert _jaccard(a, a) == 1.0

    def test_disjoint_sets(self):
        a = frozenset(["unity"])
        b = frozenset(["python"])
        assert _jaccard(a, b) == 0.0

    def test_partial_overlap(self):
        a = frozenset(["unity", "coroutine"])
        b = frozenset(["unity", "physics"])
        # intersection=1, union=3 → 1/3
        assert abs(_jaccard(a, b) - 1/3) < 1e-9

    def test_empty_sets(self):
        assert _jaccard(frozenset(), frozenset(["unity"])) == 0.0
        assert _jaccard(frozenset(), frozenset()) == 0.0


# ---------------------------------------------------------------------------
# PatternAnalyzer
# ---------------------------------------------------------------------------

class TestPatternAnalyzer:
    def test_no_outcomes_returns_empty(self):
        analyzer = PatternAnalyzer(outcomes=[])
        assert analyzer.find_candidates() == []

    def test_below_min_occurrences_excluded(self):
        outcomes = _make_outcomes(2, ["unity", "coroutine"])
        analyzer = PatternAnalyzer(outcomes=outcomes, min_occurrences=3)
        assert analyzer.find_candidates() == []

    def test_below_min_success_rate_excluded(self):
        outcomes = (
            _make_outcomes(3, ["unity", "animation"], success=True)
            + _make_outcomes(7, ["unity", "animation"], success=False)
        )
        # success_rate = 3/10 = 0.30, below 0.7
        analyzer = PatternAnalyzer(outcomes=outcomes, min_occurrences=3, min_success_rate=0.7)
        assert analyzer.find_candidates() == []

    def test_valid_candidate_returned(self):
        outcomes = _make_outcomes(5, ["unity", "animation", "coroutine"])
        analyzer = PatternAnalyzer(outcomes=outcomes, min_occurrences=3, min_success_rate=0.5)
        candidates = analyzer.find_candidates()
        assert len(candidates) >= 1
        c = candidates[0]
        assert c.occurrences >= 3
        assert c.success_rate >= 0.5
        assert isinstance(c.suggested_name, str)
        assert len(c.suggested_name) > 0

    def test_existing_skill_overlap_filters_duplicates(self):
        outcomes = _make_outcomes(5, ["unity", "csharp"])
        existing_kws = [["unity", "csharp", "monobehaviour"]]  # overlaps heavily
        analyzer = PatternAnalyzer(
            outcomes=outcomes,
            existing_skill_keywords=existing_kws,
            min_occurrences=3,
        )
        # overlap should be >= 0.5, so candidate excluded
        candidates = analyzer.find_candidates()
        assert len(candidates) == 0

    def test_max_5_candidates_returned(self):
        outcomes = []
        for group in [
            ["python", "testing"], ["docker", "container"],
            ["javascript", "frontend"], ["sql", "database"],
            ["rust", "memory"], ["kotlin", "android"],
        ]:
            outcomes += _make_outcomes(4, group)

        analyzer = PatternAnalyzer(outcomes=outcomes, min_occurrences=3, min_success_rate=0.0)
        candidates = analyzer.find_candidates()
        assert len(candidates) <= 5

    def test_candidates_sorted_by_score(self):
        outcomes_big = _make_outcomes(10, ["unity", "shader"])
        outcomes_small = _make_outcomes(4, ["python", "testing"])
        analyzer = PatternAnalyzer(
            outcomes=outcomes_big + outcomes_small,
            min_occurrences=3,
            min_success_rate=0.0,
        )
        candidates = analyzer.find_candidates()
        if len(candidates) >= 2:
            assert candidates[0].score >= candidates[1].score

    def test_task_samples_capped_at_5(self):
        outcomes = _make_outcomes(20, ["unity", "coroutine"])
        analyzer = PatternAnalyzer(outcomes=outcomes, min_occurrences=3)
        candidates = analyzer.find_candidates()
        if candidates:
            assert len(candidates[0].task_samples) <= 5

    def test_to_dict_serializable(self):
        outcomes = _make_outcomes(5, ["unity", "animation"])
        analyzer = PatternAnalyzer(outcomes=outcomes, min_occurrences=3)
        candidates = analyzer.find_candidates()
        if candidates:
            d = candidates[0].to_dict()
            assert "keyword_cluster" in d
            assert "suggested_name" in d
            assert "occurrences" in d
            assert "success_rate" in d
            assert isinstance(d["score"], float)


# ---------------------------------------------------------------------------
# build_existing_skill_keywords
# ---------------------------------------------------------------------------

class TestBuildExistingSkillKeywords:
    def test_extracts_keywords_from_skills(self):
        class MockPrompt:
            keywords = ["unity", "csharp"]

        class MockSkill:
            tags = ["game", "physics"]
            prompt = MockPrompt()

        class MockManager:
            skills = [MockSkill()]

        result = build_existing_skill_keywords(MockManager())
        assert len(result) == 1
        kws = result[0]
        assert "unity" in kws
        assert "game" in kws

    def test_empty_manager(self):
        class MockManager:
            skills = []
        assert build_existing_skill_keywords(MockManager()) == []

    def test_skill_with_no_prompt(self):
        class MockSkill:
            tags = ["debug"]
            prompt = None

        class MockManager:
            skills = [MockSkill()]

        result = build_existing_skill_keywords(MockManager())
        assert len(result) == 1
        assert "debug" in result[0]
