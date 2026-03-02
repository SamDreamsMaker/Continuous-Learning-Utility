"""CLU Community Skills Registry — publish generated skills and sync community skills.

Uses only Python stdlib (urllib) — no external dependencies required.

Registry format (GitHub repo: Continuous-Learning-Utility/clu-skills):
    registry.json          — index with all skills + SHA-256 hashes
    skills/<name>/
        skill.yaml
        prompt.md

registry.json schema:
    {
        "version": 1,
        "updated_at": "<ISO timestamp>",
        "skills": [
            {
                "name": "unity-animation",
                "version": "1.0.0",
                "description": "...",
                "tags": ["unity"],
                "author": "<anonymous-instance-hash>",
                "sha256": {
                    "skill.yaml": "<hex>",
                    "prompt.md":  "<hex>"
                }
            }
        ]
    }
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache dir for community registry skills (4th tier, separate from user skills)
_REGISTRY_CACHE_DIR = os.path.expanduser("~/.clu/registry-cache")
_REGISTRY_STATE_FILE = ".registry_state.json"

# Files that constitute a complete skill (currently only YAML + prompt)
_SKILL_FILES = ("skill.yaml", "prompt.md")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    """Summary of a registry sync operation."""
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # security failures
    errors: list[str] = field(default_factory=list)
    registry_skill_count: int = 0

    @property
    def changed(self) -> int:
        return len(self.added) + len(self.updated)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "registry_skill_count": self.registry_skill_count,
            "changed": self.changed,
        }


# ---------------------------------------------------------------------------
# GitHub API helpers (urllib-only, no requests)
# ---------------------------------------------------------------------------

def _github_api(
    path: str,
    method: str = "GET",
    body: dict | None = None,
    token: str = "",
) -> dict:
    """Make a GitHub API request and return parsed JSON."""
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "CLU-skills-registry/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps(body).encode("utf-8") if body else None
    if data:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} → {e.code}: {body_text[:300]}") from e


def _fetch_raw(url: str) -> str:
    """Fetch a raw URL (for registry.json or skill files) and return text."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CLU-skills-registry/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}") from e


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _raw_url_for_file(registry_url: str, path: str) -> str:
    """Convert a GitHub repo URL to a raw.githubusercontent.com URL."""
    # Accept either https://github.com/owner/repo or owner/repo
    m = re.match(r"(?:https?://github\.com/)?([^/]+/[^/]+?)(?:\.git)?$", registry_url.rstrip("/"))
    if not m:
        raise ValueError(f"Cannot parse registry_url: {registry_url!r}")
    owner_repo = m.group(1)
    return f"https://raw.githubusercontent.com/{owner_repo}/main/{path}"


# ---------------------------------------------------------------------------
# Sync (pull)
# ---------------------------------------------------------------------------

def sync(
    registry_url: str,
    cache_dir: str | None = None,
    skill_manager_invalidate_fn=None,
) -> SyncResult:
    """Pull new/updated community skills from the registry.

    Downloads registry.json, compares with locally cached state,
    and installs new or updated skills after running all security checks.

    Args:
        registry_url: GitHub repo URL for the registry.
        cache_dir: Directory to install registry skills (default: ~/.clu/registry-cache).
        skill_manager_invalidate_fn: Optional callback to reset the SkillManager singleton.

    Returns:
        SyncResult with counts of added/updated/skipped/error skills.
    """
    from skills.loader import SkillLoader

    result = SyncResult()
    install_dir = cache_dir or _REGISTRY_CACHE_DIR
    os.makedirs(install_dir, exist_ok=True)

    # 1. Fetch registry index
    try:
        index_url = _raw_url_for_file(registry_url, "registry.json")
        raw_index = _fetch_raw(index_url)
        index = json.loads(raw_index)
    except Exception as e:
        result.errors.append(f"Cannot fetch registry index: {e}")
        logger.error("Registry sync failed: %s", e)
        return result

    registry_skills: list[dict] = index.get("skills", [])
    result.registry_skill_count = len(registry_skills)

    # 2. Load local state
    state_path = os.path.join(install_dir, _REGISTRY_STATE_FILE)
    local_state: dict[str, str] = {}  # name → version
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                local_state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass

    loader = SkillLoader(user_skills_dir=install_dir)

    # 3. Process each skill in the registry
    for skill_entry in registry_skills:
        name = skill_entry.get("name", "")
        version = skill_entry.get("version", "0.0.0")
        sha256s: dict[str, str] = skill_entry.get("sha256", {})

        if not name:
            continue

        # Skip if already on this version
        if local_state.get(name) == version:
            continue

        action = "update" if name in local_state else "add"
        skill_dir = os.path.join(install_dir, name)
        os.makedirs(skill_dir, exist_ok=True)

        try:
            _download_and_install_skill(
                name=name,
                skill_entry=skill_entry,
                skill_dir=skill_dir,
                registry_url=registry_url,
                sha256s=sha256s,
                loader=loader,
            )
            local_state[name] = version
            if action == "add":
                result.added.append(name)
            else:
                result.updated.append(name)
            logger.info("Registry skill '%s' v%s installed", name, version)

        except SecurityError as e:
            result.skipped.append(f"{name}: {e}")
            logger.warning("Skipping registry skill '%s': %s", name, e)
            # Remove partial download
            import shutil
            shutil.rmtree(skill_dir, ignore_errors=True)
        except Exception as e:
            result.errors.append(f"{name}: {e}")
            logger.error("Error installing registry skill '%s': %s", name, e)

    # 4. Save updated local state
    try:
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(local_state, fh, indent=2)
    except OSError as e:
        logger.warning("Could not save registry state: %s", e)

    # 5. Invalidate SkillManager so next request picks up new skills
    if skill_manager_invalidate_fn and result.changed:
        try:
            skill_manager_invalidate_fn()
        except Exception as e:
            logger.warning("SkillManager invalidation failed: %s", e)

    logger.info(
        "Registry sync complete: +%d added, ~%d updated, %d skipped, %d errors",
        len(result.added), len(result.updated), len(result.skipped), len(result.errors),
    )
    return result


def _download_and_install_skill(
    name: str,
    skill_entry: dict,
    skill_dir: str,
    registry_url: str,
    sha256s: dict[str, str],
    loader,
) -> None:
    """Download all files for one skill and validate them."""
    file_contents: dict[str, str] = {}

    for fname in _SKILL_FILES:
        raw_url = _raw_url_for_file(registry_url, f"skills/{name}/{fname}")
        try:
            content = _fetch_raw(raw_url)
        except Exception as e:
            raise RuntimeError(f"Cannot download {fname}: {e}") from e

        # SHA-256 integrity check against registry index
        expected_hash = sha256s.get(fname)
        if expected_hash:
            actual_hash = _sha256(content)
            if actual_hash != expected_hash:
                raise SecurityError(
                    f"SHA-256 mismatch for {fname}: expected {expected_hash[:16]}… "
                    f"got {actual_hash[:16]}…"
                )

        file_contents[fname] = content

    # Write files to disk before running loader security checks
    for fname, content in file_contents.items():
        fpath = os.path.join(skill_dir, fname)
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(content)

    # Secret scanning (uses existing SkillLoader._scan_secrets)
    secret_hits = loader._scan_secrets(skill_dir)
    if secret_hits:
        raise SecurityError(f"Secrets detected: {secret_hits[0]}")

    # Prompt injection check
    prompt_content = file_contents.get("prompt.md", "")
    if prompt_content:
        _, injection_hits = loader._sanitize_prompt(prompt_content)
        if injection_hits:
            raise SecurityError(f"Prompt injection detected: {injection_hits[0]}")

    # Attempt full manifest load as final validation
    manifest = loader._load_one(skill_dir, "registry")
    if manifest is None:
        raise RuntimeError("Skill failed manifest validation after download")


class SecurityError(Exception):
    """Raised when a downloaded skill fails security checks."""


# ---------------------------------------------------------------------------
# Registry status (local)
# ---------------------------------------------------------------------------

def get_sync_status(cache_dir: str | None = None) -> dict:
    """Return local registry state metadata."""
    install_dir = cache_dir or _REGISTRY_CACHE_DIR
    state_path = os.path.join(install_dir, _REGISTRY_STATE_FILE)

    installed: dict[str, str] = {}
    last_modified: float = 0.0

    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                installed = json.load(fh)
            last_modified = os.path.getmtime(state_path)
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "installed_count": len(installed),
        "installed": installed,
        "last_sync": last_modified or None,
        "cache_dir": install_dir,
    }


# ---------------------------------------------------------------------------
# Publish (push)
# ---------------------------------------------------------------------------

def publish(
    skill_dir: str,
    skill_name: str,
    github_token: str,
    registry_repo: str = "clu-community/clu-skills",
) -> str:
    """Publish a locally generated skill to the community registry via GitHub API.

    Creates a new branch in the registry repo, commits the skill files,
    and opens a pull request.

    Args:
        skill_dir: Local directory containing skill.yaml and prompt.md.
        skill_name: Skill name (used for branch and directory names).
        github_token: GitHub PAT with repo + pull_request write scope.
        registry_repo: "owner/repo" of the community registry.

    Returns:
        PR URL string.

    Raises:
        RuntimeError: On any GitHub API error.
        ValueError: If required files are missing or token is empty.
    """
    if not github_token:
        raise ValueError("github_token is required for publishing")

    # Read skill files
    file_contents: dict[str, str] = {}
    for fname in _SKILL_FILES:
        fpath = os.path.join(skill_dir, fname)
        if not os.path.isfile(fpath):
            raise ValueError(f"Required file missing: {fpath}")
        with open(fpath, "r", encoding="utf-8") as fh:
            file_contents[fname] = fh.read()

    # Parse version from skill.yaml
    import yaml
    parsed_yaml = yaml.safe_load(file_contents["skill.yaml"])
    version = str(parsed_yaml.get("version", "1.0.0"))
    description = str(parsed_yaml.get("description", "Auto-generated CLU skill"))
    tags = list(parsed_yaml.get("tags", []))

    owner, repo = registry_repo.split("/", 1)
    branch_name = f"clu-skill-{skill_name}-{version}-{int(time.time())}"

    # 1. Get main branch SHA
    ref_data = _github_api(f"/repos/{owner}/{repo}/git/refs/heads/main", token=github_token)
    base_sha = ref_data["object"]["sha"]

    # 2. Create new branch
    _github_api(
        f"/repos/{owner}/{repo}/git/refs",
        method="POST",
        body={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        token=github_token,
    )
    logger.debug("Created branch '%s' in %s", branch_name, registry_repo)

    # 3. Commit skill files
    sha256s: dict[str, str] = {}
    for fname, content in file_contents.items():
        sha256s[fname] = _sha256(content)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        _github_api(
            f"/repos/{owner}/{repo}/contents/skills/{skill_name}/{fname}",
            method="PUT",
            body={
                "message": f"Add skill: {skill_name} v{version}",
                "content": encoded,
                "branch": branch_name,
            },
            token=github_token,
        )
        logger.debug("Committed %s", fname)

    # 4. Update registry.json (fetch → merge → push)
    try:
        reg_raw = _github_api(
            f"/repos/{owner}/{repo}/contents/registry.json",
            token=github_token,
        )
        existing_content = base64.b64decode(reg_raw["content"].replace("\n", "")).decode("utf-8")
        index = json.loads(existing_content)
        file_sha = reg_raw["sha"]
    except Exception:
        # registry.json doesn't exist yet
        index = {"version": 1, "skills": []}
        file_sha = None

    # Remove any existing entry for this skill then add new one
    index["skills"] = [s for s in index.get("skills", []) if s.get("name") != skill_name]
    index["skills"].append({
        "name": skill_name,
        "version": version,
        "description": description,
        "tags": tags,
        "author": _anonymous_id(),
        "sha256": sha256s,
    })
    index["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"

    reg_body: dict = {
        "message": f"Update registry: add {skill_name} v{version}",
        "content": base64.b64encode(json.dumps(index, indent=2).encode("utf-8")).decode("ascii"),
        "branch": branch_name,
    }
    if file_sha:
        reg_body["sha"] = file_sha

    _github_api(
        f"/repos/{owner}/{repo}/contents/registry.json",
        method="PUT",
        body=reg_body,
        token=github_token,
    )

    # 5. Open pull request
    pr = _github_api(
        f"/repos/{owner}/{repo}/pulls",
        method="POST",
        body={
            "title": f"Add skill: {skill_name} v{version}",
            "body": (
                f"Auto-generated CLU skill submitted by an agent instance.\n\n"
                f"**Skill:** `{skill_name}` v{version}\n"
                f"**Description:** {description}\n"
                f"**Tags:** {', '.join(tags)}\n\n"
                f"SHA-256 hashes:\n"
                + "\n".join(f"- `{k}`: `{v[:16]}…`" for k, v in sha256s.items())
            ),
            "head": branch_name,
            "base": "main",
        },
        token=github_token,
    )
    pr_url = pr.get("html_url", "")
    logger.info("PR created for skill '%s': %s", skill_name, pr_url)
    return pr_url


def _anonymous_id() -> str:
    """Derive a stable anonymous identifier from the machine (no PII)."""
    import socket
    raw = socket.gethostname() + str(os.getpid())
    return "anon-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Cache directory accessor (for SkillLoader 4th tier)
# ---------------------------------------------------------------------------

def registry_cache_dir() -> str:
    return _REGISTRY_CACHE_DIR


# ---------------------------------------------------------------------------
# Browse (list available without downloading)
# ---------------------------------------------------------------------------

def list_available(
    registry_url: str,
    cache_dir: str | None = None,
) -> list[dict]:
    """Fetch the registry index and return available skills with install status.

    Does NOT download any skill files — only reads the registry.json index.

    Args:
        registry_url: GitHub repo URL for the registry.
        cache_dir: Local registry cache directory (default: ~/.clu/registry-cache).

    Returns:
        List of dicts with keys:
            name, version, description, tags, installed, installed_version,
            update_available
    """
    install_dir = cache_dir or _REGISTRY_CACHE_DIR

    # Load local state
    state_path = os.path.join(install_dir, _REGISTRY_STATE_FILE)
    local_state: dict[str, str] = {}
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                local_state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass

    # Fetch remote index
    index_url = _raw_url_for_file(registry_url, "registry.json")
    raw_index = _fetch_raw(index_url)
    index = json.loads(raw_index)

    result: list[dict] = []
    for entry in index.get("skills", []):
        name = entry.get("name", "")
        if not name:
            continue
        installed_version = local_state.get(name)
        result.append({
            "name": name,
            "version": entry.get("version", "0.0.0"),
            "description": entry.get("description", ""),
            "tags": entry.get("tags", []),
            "author": entry.get("author", ""),
            "installed": installed_version is not None,
            "installed_version": installed_version,
            "update_available": (
                installed_version is not None
                and installed_version != entry.get("version", "0.0.0")
            ),
        })
    return result


def install_one(
    name: str,
    registry_url: str,
    cache_dir: str | None = None,
    skill_manager_invalidate_fn=None,
) -> dict:
    """Download and install a single skill from the registry by name.

    Args:
        name: Skill name as it appears in the registry index.
        registry_url: GitHub repo URL for the registry.
        cache_dir: Local registry cache directory (default: ~/.clu/registry-cache).
        skill_manager_invalidate_fn: Optional callback to reset SkillManager.

    Returns:
        dict with keys: ok, name, version

    Raises:
        RuntimeError: If the skill is not found in the registry or download fails.
        SecurityError: If the skill fails security checks.
    """
    from skills.loader import SkillLoader

    install_dir = cache_dir or _REGISTRY_CACHE_DIR
    os.makedirs(install_dir, exist_ok=True)

    # Fetch registry index to find the skill entry
    index_url = _raw_url_for_file(registry_url, "registry.json")
    raw_index = _fetch_raw(index_url)
    index = json.loads(raw_index)

    skill_entry = next(
        (s for s in index.get("skills", []) if s.get("name") == name),
        None,
    )
    if skill_entry is None:
        raise RuntimeError(f"Skill '{name}' not found in registry index")

    version = skill_entry.get("version", "0.0.0")
    sha256s: dict[str, str] = skill_entry.get("sha256", {})

    skill_dir = os.path.join(install_dir, name)
    os.makedirs(skill_dir, exist_ok=True)

    loader = SkillLoader(user_skills_dir=install_dir)

    try:
        _download_and_install_skill(
            name=name,
            skill_entry=skill_entry,
            skill_dir=skill_dir,
            registry_url=registry_url,
            sha256s=sha256s,
            loader=loader,
        )
    except SecurityError:
        import shutil
        shutil.rmtree(skill_dir, ignore_errors=True)
        raise

    # Update local state
    state_path = os.path.join(install_dir, _REGISTRY_STATE_FILE)
    local_state: dict[str, str] = {}
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                local_state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    local_state[name] = version
    try:
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(local_state, fh, indent=2)
    except OSError as e:
        logger.warning("Could not update registry state: %s", e)

    if skill_manager_invalidate_fn:
        try:
            skill_manager_invalidate_fn()
        except Exception as e:
            logger.warning("SkillManager invalidation failed: %s", e)

    logger.info("Registry skill '%s' v%s installed via install_one", name, version)
    return {"ok": True, "name": name, "version": version}
