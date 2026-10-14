import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "sieve_referee" / "__init__.py"


class TestVersionConsistency(unittest.TestCase):
    """pyproject.toml と sieve_referee/__init__.py の version 一致を機械固定する pin。

    二重管理(pyproject と __init__ の手動同期)による drift を構造的に防止する。
    両ファイルとも直接読んで判定する(install 状態・sys.path・CWD に依存しない)。
    """

    def _extract_version(self, path, pattern, label):
        self.assertTrue(path.exists(), "%s not found: %s" % (label, path))
        text = path.read_text(encoding="utf-8")
        matches = re.findall(pattern, text, re.MULTILINE)
        self.assertEqual(
            len(matches), 1,
            "%s: expected exactly 1 version line, found %d"
            % (label, len(matches)))
        return matches[0]

    def test_pyproject_and_init_versions_match(self):
        pyproject_version = self._extract_version(
            PYPROJECT, r'^version = "([^"]+)"$', "pyproject.toml")
        init_version = self._extract_version(
            INIT_PY, r'^__version__ = "([^"]+)"$', "sieve_referee/__init__.py")
        self.assertEqual(
            pyproject_version, init_version,
            "version drift: pyproject=%r __init__=%r"
            % (pyproject_version, init_version))


if __name__ == "__main__":
    unittest.main()
