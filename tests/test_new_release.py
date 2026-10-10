"""Exercise releases using disposable repositories and a local bare remote."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONSTANTS = "disk_ha/constants/DDiskHA.py"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="disk-ha-release-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
                        GIT_AUTHOR_NAME="Release Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="Release Test", GIT_COMMITTER_EMAIL="test@example.invalid")
        self.git("init", "-b", "main")
        self.git("init", "--bare", str(self.root / "remote.git"))
        self.git("remote", "add", "origin", str(self.root / "remote.git"))
        for name in ("scripts/new-release.sh", CONSTANTS, "CHANGELOG.md"):
            destination = self.repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        # Start every fixture before its first release, independently of this checkout's version.
        (self.repo / CONSTANTS).write_text(
            'from typing import Final\n\nclass DDiskHA:\n    VERSION: Final[str] = "0.0.1"\n    CMDB_CODENAME: Final[str] = "Scaffolding"\n')
        (self.repo / "CHANGELOG.md").write_text(
            '# Changelog\n\n## [Unreleased]\n\n### Summary\n\nFirst feature.\n')
        self.git("add", ".")
        self.git("commit", "-m", "Initial project")
        self.git("branch", "dev")
        self.git("push", "origin", "main", "dev")
        self.git("switch", "-c", "feat/maint-0.1.0")
        (self.repo / "feature.txt").write_text("Feature content\n")
        self.git("add", ".")
        self.git("commit", "-m", "Add feature")

    def command(self, *args, check=True):
        return subprocess.run(args, cwd=self.repo, env=self.env, text=True,
                              capture_output=True, check=check, timeout=20)

    def git(self, *args):
        return self.command("git", *args).stdout.strip()

    def release(self, *args):
        # Give the release script a terminal for its interactive confirmation.
        master, slave = os.openpty()
        try:
            os.write(master, b"y\n")
            return subprocess.run(
                ["bash", "scripts/new-release.sh", *args], cwd=self.repo,
                env=self.env, stdin=slave, text=True, capture_output=True, timeout=20)
        finally:
            os.close(slave)
            os.close(master)

    def assert_rejected(self, args, error):
        before = self.git("show-ref")
        branch = self.git("branch", "--show-current")
        result = self.release(*args)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(error, result.stderr)
        self.assertEqual(self.git("show-ref"), before)
        self.assertEqual(self.git("branch", "--show-current"), branch)

    def test_release_publishes_matching_branches_and_annotated_tag(self):
        changelog = (self.repo / "CHANGELOG.md").read_text()
        result = self.release("0.1.0", "First release")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("branch", "--show-current"), "feat/maint-0.1.1")
        commit = self.git("rev-parse", "HEAD")
        for ref in ("main", "dev", "origin/main", "origin/dev", "v0.1.0^{commit}"):
            self.assertEqual(self.git("rev-parse", ref), commit)
        self.assertEqual(self.git("cat-file", "-t", "v0.1.0"), "tag")
        self.assertIn('VERSION: Final[str] = "0.1.0"', (self.repo / CONSTANTS).read_text())
        self.assertIn('CMDB_CODENAME: Final[str] = "First release"', (self.repo / CONSTANTS).read_text())
        released = (self.repo / "CHANGELOG.md").read_text()
        self.assertIn("## [0.1.0] - ", released)
        self.assertEqual(released.count("## [Unreleased]"), 1)
        self.assertEqual(released.split("### Summary", 1)[1], changelog.split("### Summary", 1)[1])
        self.assertEqual(self.git("status", "--porcelain"), "")
        remote = self.git("ls-remote", "origin")
        self.assertIn("refs/tags/v0.1.0", remote)
        self.assertNotIn("refs/heads/feat/maint-0.1.1", remote)

    def test_prerelease_and_explicit_next_branch(self):
        result = self.release("0.1.0-rc.1+build.01", "Candidate", "feat/next")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("branch", "--show-current"), "feat/next")
        self.assertIn('"0.1.0-rc.1+build.01"', (self.repo / CONSTANTS).read_text())

    def test_invalid_arguments_leave_refs_unchanged(self):
        for version in ("v0.1.0", "01.2.3", "0.1.0-01", "0.1.0-rc.01", "0.1.0/evil"):
            with self.subTest(version=version):
                self.assert_rejected((version, "Release"), "Use a version")
        self.assert_rejected(("0.1.0", "  "), "A release message is required")
        self.assert_rejected(("0.1.0", "Release", "dev"), "Next feature branch already exists")

    def test_dirty_tree_and_main_branch_are_rejected(self):
        (self.repo / "uncommitted.txt").write_text("Pending work")
        self.assert_rejected(("0.1.0", "Release"), "Commit or stash")
        self.git("switch", "main")
        self.assert_rejected(("0.1.0", "Release"), "Run from a feature branch")

    def test_duplicate_version_is_rejected(self):
        with (self.repo / CONSTANTS).open("a") as stream:
            stream.write('    VERSION: Final[str] = "0.0.2"\n')
        self.git("add", ".")
        self.git("commit", "-m", "Duplicate version")
        self.assert_rejected(("0.1.0", "Release"), "Cannot read disk-ha release constants")

    def test_help_uses_current_version_without_a_versioned_branch(self):
        self.git("switch", "-c", "feat/setup")
        result = self.release("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Likely next version: 0.0.2", result.stdout)
        self.assertEqual(self.git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
