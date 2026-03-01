"""Pattern analyzer — discovers recurring task patterns in outcome data.

Reads data/outcomes.jsonl and clusters tasks by shared keywords to surface
"skill candidates": patterns that appear frequently with high success rates
and are not already covered by an existing skill.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Minimum keyword overlap (Jaccard) to merge two tasks into the same cluster
_CLUSTER_JACCARD_THRESHOLD = 0.25

# Max candidates returned to the dashboard
_MAX_CANDIDATES = 5


@dataclass
class SkillCandidate:
    """A recurring pattern that could be codified as a new CLU skill."""
    keyword_cluster: list[str]       # representative keywords for this pattern
    suggested_name: str              # e.g. "unity-animation"
    occurrences: int                 # number of tasks that matched
    success_rate: float              # 0.0–1.0
    task_samples: list[str]          # up to 5 representative task texts
    tools_used: list[str]            # most-used tools in these tasks
    file_extensions: list[str]       # most-touched file types
    existing_skill_overlap: float    # 0.0 = no overlap with current skills
    score: float = 0.0               # occurrences × success_rate (for ranking)

    def to_dict(self) -> dict:
        return {
            "keyword_cluster": self.keyword_cluster,
            "suggested_name": self.suggested_name,
            "occurrences": self.occurrences,
            "success_rate": round(self.success_rate, 2),
            "task_samples": self.task_samples,
            "tools_used": self.tools_used,
            "file_extensions": self.file_extensions,
            "existing_skill_overlap": round(self.existing_skill_overlap, 2),
            "score": round(self.score, 2),
        }


class PatternAnalyzer:
    """Finds recurring patterns in outcome data and proposes skill candidates.

    Args:
        outcomes: List of outcome dicts from OutcomeTracker.load()
        existing_skill_keywords: Keywords already covered by loaded skills
            (used to avoid proposing duplicates).
        min_occurrences: Pattern must appear at least this many times.
        min_success_rate: Pattern tasks must succeed at least this often.
    """

    def __init__(
        self,
        outcomes: list[dict],
        existing_skill_keywords: list[list[str]] | None = None,
        min_occurrences: int = 3,
        min_success_rate: float = 0.7,
    ):
        self.outcomes = outcomes
        self.existing_kw_sets: list[frozenset[str]] = [
            frozenset(kws) for kws in (existing_skill_keywords or [])
        ]
        self.min_occurrences = min_occurrences
        self.min_success_rate = min_success_rate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_candidates(self) -> list[SkillCandidate]:
        """Run the full analysis pipeline and return ranked candidates."""
        if not self.outcomes:
            return []

        clusters = self._cluster_outcomes()
        candidates: list[SkillCandidate] = []

        for cluster_kws, records in clusters.items():
            if len(records) < self.min_occurrences:
                continue

            success_rate = sum(1 for r in records if r.get("success")) / len(records)
            if success_rate < self.min_success_rate:
                continue

            kw_list = sorted(cluster_kws)
            overlap = self._overlap_with_existing(cluster_kws)
            if overlap >= 0.5:
                continue  # already well-covered by an existing skill

            tools_counter: Counter[str] = Counter()
            ext_counter: Counter[str] = Counter()
            samples: list[str] = []

            for r in records:
                for t in (r.get("tools_used") or []):
                    tools_counter[t] += 1
                for e in (r.get("file_extensions") or []):
                    ext_counter[e] += 1
                if len(samples) < 5:
                    samples.append(r.get("task", "")[:200])

            score = len(records) * success_rate
            candidate = SkillCandidate(
                keyword_cluster=kw_list,
                suggested_name=self._suggest_name(kw_list),
                occurrences=len(records),
                success_rate=success_rate,
                task_samples=samples,
                tools_used=[t for t, _ in tools_counter.most_common(5)],
                file_extensions=[e for e, _ in ext_counter.most_common(5)],
                existing_skill_overlap=overlap,
                score=score,
            )
            candidates.append(candidate)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:_MAX_CANDIDATES]

    # ------------------------------------------------------------------
    # Clustering (greedy Jaccard merge)
    # ------------------------------------------------------------------

    def _cluster_outcomes(self) -> dict[frozenset[str], list[dict]]:
        """Group outcomes into clusters based on keyword overlap."""
        clusters: list[tuple[frozenset[str], list[dict]]] = []

        for record in self.outcomes:
            kws = frozenset(record.get("keywords") or [])
            if not kws:
                continue

            best_idx: int | None = None
            best_score = 0.0

            for i, (cluster_kws, _) in enumerate(clusters):
                j = _jaccard(kws, cluster_kws)
                if j >= _CLUSTER_JACCARD_THRESHOLD and j > best_score:
                    best_score = j
                    best_idx = i

            if best_idx is not None:
                # Merge into best cluster: union of keywords, keep top N by freq
                merged_kws, records = clusters[best_idx]
                # Grow cluster keywords: keep common core + most frequent additions
                all_kws = merged_kws | kws
                # Keep up to 10 keywords (most representative)
                freq: Counter[str] = Counter()
                for r in records + [record]:
                    for k in (r.get("keywords") or []):
                        freq[k] += 1
                top_kws = frozenset(k for k, _ in freq.most_common(10))
                clusters[best_idx] = (top_kws, records + [record])
            else:
                clusters.append((kws, [record]))

        return {kws: records for kws, records in clusters}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _overlap_with_existing(self, cluster_kws: frozenset[str]) -> float:
        """Return max Jaccard overlap between cluster and any existing skill."""
        if not self.existing_kw_sets:
            return 0.0
        return max(_jaccard(cluster_kws, existing) for existing in self.existing_kw_sets)

    @staticmethod
    def _suggest_name(keywords: list[str]) -> str:
        """Derive a hyphenated skill name from the top keywords."""
        # Use up to 3 keywords, shortest first to keep names tidy
        chosen = sorted(keywords[:6], key=len)[:3]
        raw = "-".join(w.lower() for w in chosen if w.isalpha())
        # Sanitize to slug format
        slug = re.sub(r"[^a-z0-9-]", "-", raw).strip("-")
        return slug or "auto-skill"


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two keyword sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def build_existing_skill_keywords(skill_manager) -> list[list[str]]:
    """Extract keyword lists from all loaded skills for overlap detection."""
    result: list[list[str]] = []
    for skill in skill_manager.skills:
        kws: list[str] = list(skill.tags or [])
        if skill.prompt and skill.prompt.keywords:
            kws.extend(skill.prompt.keywords)
        if kws:
            result.append(kws)
    return result
