"""
Probes for the sieve-referee v1.5.2 lane (RF-T09..RF-T13, red-first).

The library-side file-reading path (`collect_txt_documents` in
sieve_referee.io_utils) is new in this lane: the v1.5.1 CLI builds `skipped`
in its own loop, so `batch_evaluate` (which receives already-read text) never
carries it. The tests import the new name inside the test functions so the
red run fails per-test with ImportError instead of breaking collection.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

from sieve_referee.evaluator import batch_evaluate  # noqa: E402

# Pins measured against the released 1.5.1 tree (main e90e586) on 2026-11-07.
# --json stdout, dashboard line stripped, encoded utf-8.
PIN_JSON_NOSKIP_SHA256 = "f00867304c3fa03353cb1de7b8b7b6cf032ceeab4ae3c47beb86321722bc0a55"
PIN_JSON_SKIP_SHA256 = "f7a5b90d5a2800ef1902552d1522d83e19dccf27c52d47d5735dfd9182a2359f"
PIN_DASH_NOSKIP_SHA256 = "f4b99100e3e84d76777fd84160da8605ba5de56acf65b78492e2658a5da56571"
PIN_DASH_SKIP_SHA256 = "b43ba043f6709ed4478ec99038d931162866fe1f3f08a64b41911de7c273e410"
PIN_STDERR_SKIP = "Skipped 1 file(s): empty_input=1"

GOOD_A = "Alpha beta gamma document text\n"
GOOD_B = "Alpha beta gamma another text\n"


def _run_cli(target_dir: str, out_dir: str):
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "sieve_referee.cli", target_dir,
         "--json", "--output-dir", out_dir],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestRfT09LibrarySkipped(unittest.TestCase):
    def test_rf_t09_library_path_reports_skipped_like_cli(self):
        """RF-T09: the library file-reading path returns (documents, skipped)
        with the same shape and the same closed vocabulary reasons as the CLI;
        empty and unreadable files are listed."""
        from sieve_referee.io_utils import collect_txt_documents

        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.txt").write_text(GOOD_A, encoding="utf-8")
            Path(td, "b.txt").write_text(GOOD_B, encoding="utf-8")
            Path(td, "empty.txt").write_bytes(b"")
            Path(td, "bad.txt").write_bytes(b"\x81\xff")

            docs, skipped = collect_txt_documents(td)

            # read_text_with_reason は NFKC 正規化 + strip 済みの本文を返す
            self.assertEqual(
                docs,
                {"a.txt": "Alpha beta gamma document text",
                 "b.txt": "Alpha beta gamma another text"},
            )
            self.assertEqual(
                [entry["path"] for entry in skipped],
                ["bad.txt", "empty.txt"],
            )
            self.assertEqual(
                {entry["reason"] for entry in skipped},
                {"empty_input", "unreadable"},
            )

            # Same judgment as the CLI: run the CLI on the same directory and
            # compare its `skipped` payload with the library result.
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir))
            self.assertEqual(proc.returncode, 0)
            json_text = "\n".join(
                line for line in proc.stdout.splitlines()
                if not line.startswith("Standard HTML report generated:")
            )
            payload = json.loads(json_text)
            self.assertEqual(payload["skipped"], skipped)


class TestRfT10NoSkips(unittest.TestCase):
    def test_rf_t10_no_skips_gives_empty_list_and_batch_evaluate_unchanged(self):
        """RF-T10: when nothing is skipped the list is empty, and
        batch_evaluate keeps its existing return type and keys."""
        from sieve_referee.io_utils import collect_txt_documents

        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.txt").write_text(GOOD_A, encoding="utf-8")
            Path(td, "b.txt").write_text(GOOD_B, encoding="utf-8")
            docs, skipped = collect_txt_documents(td)
            self.assertEqual(skipped, [])

        results = batch_evaluate(
            {"a.txt": GOOD_A, "b.txt": GOOD_B}
        )
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        res = results[0]
        # Existing keys (attributes) unchanged
        self.assertEqual(res.item_id, "a.txt")
        self.assertEqual(res.matched_peer_id, "b.txt")
        self.assertEqual(res.mask, "1110")
        self.assertEqual(res.evaluation_signal.value, "RED")


class TestRfT11ClosedVocabulary(unittest.TestCase):
    def test_rf_t11_reasons_in_closed_vocabulary_no_exception_text(self):
        """RF-T11: reasons stay within the existing v1.5.1 vocabulary
        (empty_input / unreadable) and no exception message or file content is
        reported — each entry carries exactly `path` and `reason`."""
        from sieve_referee.io_utils import collect_txt_documents

        with tempfile.TemporaryDirectory() as td:
            Path(td, "empty.txt").write_bytes(b"")
            Path(td, "blank.txt").write_text("   \n", encoding="utf-8")
            Path(td, "bad.txt").write_bytes(b"\x81\xff")
            _, skipped = collect_txt_documents(td)

        vocabulary = {"empty_input", "unreadable"}
        self.assertEqual(len(skipped), 3)
        for entry in skipped:
            self.assertEqual(set(entry.keys()), {"path", "reason"})
            self.assertIn(entry["reason"], vocabulary)


class TestRfT12Molds(unittest.TestCase):
    def test_rf_t12_cli_output_byte_identical_to_1_5_1_pins(self):
        """RF-T12: --json stdout and the standard dashboard HTML are byte
        identical to the 1.5.1 pins, with and without skipped files."""
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.txt").write_text(GOOD_A, encoding="utf-8")
            Path(td, "b.txt").write_text(GOOD_B, encoding="utf-8")
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir))
            self.assertEqual(proc.returncode, 0)
            json_text = "\n".join(
                line for line in proc.stdout.splitlines()
                if not line.startswith("Standard HTML report generated:")
            )
            self.assertEqual(_sha256_text(json_text), PIN_JSON_NOSKIP_SHA256)
            self.assertEqual(proc.stderr, "")
            dash = (out_dir / "sieve_dashboard.html").read_text(encoding="utf-8")
            self.assertEqual(_sha256_text(dash), PIN_DASH_NOSKIP_SHA256)

        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.txt").write_text(GOOD_A, encoding="utf-8")
            Path(td, "b.txt").write_text(GOOD_B, encoding="utf-8")
            Path(td, "empty.txt").write_bytes(b"")
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir))
            self.assertEqual(proc.returncode, 0)
            json_text = "\n".join(
                line for line in proc.stdout.splitlines()
                if not line.startswith("Standard HTML report generated:")
            )
            self.assertEqual(_sha256_text(json_text), PIN_JSON_SKIP_SHA256)
            self.assertEqual(proc.stderr.strip(), PIN_STDERR_SKIP)
            dash = (out_dir / "sieve_dashboard.html").read_text(encoding="utf-8")
            self.assertEqual(_sha256_text(dash), PIN_DASH_SKIP_SHA256)


class TestRfT13VersionChangelog(unittest.TestCase):
    def test_rf_t13_version_and_changelog_consistent(self):
        """RF-T13: pyproject version is 1.5.2 and CHANGELOG.md documents it."""
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "1.5.2"', pyproject)
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("[1.5.2]", changelog)


if __name__ == "__main__":
    unittest.main()
