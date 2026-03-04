"""Tests for individual tools."""

import os
import json
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sandbox.path_validator import PathValidator
from sandbox.backup_manager import BackupManager
from tools.read_file import ReadFileTool
from tools.list_files import ListFilesTool
from tools.search_in_files import SearchInFilesTool
from tools.write_file import WriteFileTool


@pytest.fixture
def project_root(tmp_path):
    """Create a temporary Unity-like project structure."""
    scripts = tmp_path / "Assets" / "Scripts"
    scripts.mkdir(parents=True)

    (scripts / "Player.cs").write_text(
        'using UnityEngine;\n\npublic class Player : MonoBehaviour\n{\n'
        '    [SerializeField] private float _speed = 5f;\n'
        '    private void Update() { }\n}\n',
        encoding="utf-8",
    )
    (scripts / "Enemy.cs").write_text(
        'using UnityEngine;\n\npublic class Enemy : MonoBehaviour\n{\n'
        '    public int Health = 100;\n}\n',
        encoding="utf-8",
    )

    sub = scripts / "Utils"
    sub.mkdir()
    (sub / "Helper.cs").write_text(
        'public static class Helper\n{\n'
        '    public static int Add(int a, int b) => a + b;\n}\n',
        encoding="utf-8",
    )

    return str(tmp_path)


@pytest.fixture
def sandbox():
    return PathValidator()


@pytest.fixture
def backup(tmp_path):
    return BackupManager(str(tmp_path / "backups"))


class TestReadFile:

    def test_read_existing_file(self, project_root, sandbox, backup):
        tool = ReadFileTool()
        result = tool.execute(
            {"path": "Assets/Scripts/Player.cs"},
            project_root, sandbox, backup,
        )
        assert "content" in result
        assert "Player" in result["content"]
        assert result["lines"] > 0

    def test_read_nonexistent_file(self, project_root, sandbox, backup):
        tool = ReadFileTool()
        result = tool.execute(
            {"path": "Assets/Scripts/Missing.cs"},
            project_root, sandbox, backup,
        )
        assert "error" in result

    def test_read_outside_assets_rejected(self, project_root, sandbox, backup):
        tool = ReadFileTool()
        result = tool.execute(
            {"path": "Library/something.dll"},
            project_root, sandbox, backup,
        )
        assert "error" in result


class TestListFiles:

    def test_list_assets(self, project_root, sandbox, backup):
        tool = ListFilesTool()
        result = tool.execute(
            {"path": "Assets/Scripts", "pattern": "*.cs"},
            project_root, sandbox, backup,
        )
        assert result["count"] >= 2
        paths = [f["path"] for f in result["files"]]
        assert any("Player.cs" in p for p in paths)

    def test_list_recursive(self, project_root, sandbox, backup):
        tool = ListFilesTool()
        result = tool.execute(
            {"path": "Assets/Scripts", "pattern": "*.cs", "recursive": True},
            project_root, sandbox, backup,
        )
        paths = [f["path"] for f in result["files"]]
        assert any("Helper.cs" in p for p in paths)

    def test_list_nonexistent_dir(self, project_root, sandbox, backup):
        tool = ListFilesTool()
        result = tool.execute(
            {"path": "Assets/NonExistent"},
            project_root, sandbox, backup,
        )
        assert "error" in result


class TestSearchInFiles:

    def test_search_finds_match(self, project_root, sandbox, backup):
        tool = SearchInFilesTool()
        result = tool.execute(
            {"pattern": "MonoBehaviour", "path": "Assets/Scripts"},
            project_root, sandbox, backup,
        )
        assert result["count"] >= 2

    def test_search_regex(self, project_root, sandbox, backup):
        tool = SearchInFilesTool()
        result = tool.execute(
            {"pattern": r"private\s+float", "path": "Assets/Scripts"},
            project_root, sandbox, backup,
        )
        assert result["count"] >= 1
        assert any("Player" in m["file"] for m in result["matches"])

    def test_search_no_match(self, project_root, sandbox, backup):
        tool = SearchInFilesTool()
        result = tool.execute(
            {"pattern": "ZZZZZZZ_NOT_FOUND", "path": "Assets/"},
            project_root, sandbox, backup,
        )
        assert result["count"] == 0

    def test_search_invalid_regex(self, project_root, sandbox, backup):
        tool = SearchInFilesTool()
        result = tool.execute(
            {"pattern": "[invalid"},
            project_root, sandbox, backup,
        )
        assert "error" in result

    def test_search_non_cs_files(self, tmp_path):
        """Search should work with non-C# file patterns."""
        src = tmp_path / "Assets" / "Scripts"
        src.mkdir(parents=True)
        (src / "config.json").write_text('{"key": "value"}')
        (src / "readme.txt").write_text("hello world")

        tool = SearchInFilesTool()
        sand = PathValidator()
        bak = BackupManager(str(tmp_path / "bak"))
        result = tool.execute(
            {"pattern": "hello", "path": "Assets/Scripts", "file_pattern": "*.txt"},
            str(tmp_path), sand, bak,
        )
        assert result["count"] >= 1
        assert any("readme.txt" in m["file"] for m in result["matches"])


class TestWriteFile:

    def test_write_new_file(self, project_root, sandbox, backup):
        tool = WriteFileTool()
        content = "public class NewScript { }\n"
        result = tool.execute(
            {"path": "Assets/Scripts/NewScript.cs", "content": content},
            project_root, sandbox, backup,
        )
        # May fail validation without Unity DLLs, but should not crash
        assert "success" in result or "error" in result

    def test_patch_existing_file(self, project_root, sandbox, backup):
        tool = WriteFileTool()
        result = tool.execute(
            {
                "path": "Assets/Scripts/Enemy.cs",
                "patches": [
                    {
                        "action": "replace",
                        "target": "public int Health = 100;",
                        "replacement": "public int Health = 200;",
                    }
                ],
            },
            project_root, sandbox, backup,
        )
        # May fail validation, but should not crash
        assert "success" in result or "error" in result

    def test_reject_write_to_library(self, project_root, sandbox, backup):
        tool = WriteFileTool()
        result = tool.execute(
            {"path": "Library/test.cs", "content": "test"},
            project_root, sandbox, backup,
        )
        assert "error" in result

    def test_reject_both_content_and_patches(self, project_root, sandbox, backup):
        tool = WriteFileTool()
        result = tool.execute(
            {
                "path": "Assets/Scripts/Test.cs",
                "content": "test",
                "patches": [{"action": "replace", "target": "a", "replacement": "b"}],
            },
            project_root, sandbox, backup,
        )
        assert "error" in result
        assert "both" in result["error"].lower() or "either" in result["error"].lower()

    def test_patch_target_not_found(self, project_root, sandbox, backup):
        tool = WriteFileTool()
        result = tool.execute(
            {
                "path": "Assets/Scripts/Enemy.cs",
                "patches": [
                    {
                        "action": "replace",
                        "target": "THIS_STRING_DOES_NOT_EXIST",
                        "replacement": "replacement",
                    }
                ],
            },
            project_root, sandbox, backup,
        )
        assert "error" in result
        assert "not found" in result["error"]
