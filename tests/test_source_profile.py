"""Protect reproducibility and the user's source tree when applying profiles."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import source_profile as profiles, audit_artifacts


class SourceProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        self.repo = self.source / "subprojects" / "fixture"
        self.repo.mkdir(parents=True)
        self.command(self.source, "init", "-q")
        self.command(self.repo, "init", "-q")
        (self.repo / "meson.build").write_bytes(b"project('fixture')\n")
        (self.repo / "worker.c").write_bytes(b'const char *name = "original";\n')
        self.commit(self.repo)
        self.commit(self.source)
        before = (self.repo / "worker.c").read_bytes()
        after = before.replace(b"original", b"custom")
        self.profile = {
            "name": "fixture", "prefix": "custom", "scope": "test", "limitations": [],
            "modules": [{"path": "subprojects/fixture",
                         "commit": self.command(self.repo, "rev-parse", "HEAD").strip(),
                         "files": [{"path": "worker.c", "before_sha256": profiles.digest(before),
                                    "after_sha256": profiles.digest(after),
                                    "replacements": [{"old": "original", "new": "custom", "count": 1}]}]}],
        }

    def command(self, repo, *args):
        return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.PIPE, text=True)

    def commit(self, repo):
        self.command(repo, "add", ".")
        self.command(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                     "commit", "-qm", "fixture")

    def test_preflight_does_not_write_and_application_is_repeatable(self):
        profiles.check_and_apply(self.source, self.profile)
        self.assertIn(b"original", (self.repo / "worker.c").read_bytes())
        first = profiles.check_and_apply(self.source, self.profile, apply=True)
        second = profiles.check_and_apply(self.source, self.profile, apply=True)
        self.assertEqual(first, second)
        self.assertIn(b"custom", (self.repo / "worker.c").read_bytes())
        with self.assertRaisesRegex(RuntimeError, "upstream source checkout contains changes"):
            profiles.check_and_apply(self.source, None, apply=True)

    def test_user_edits_to_profile_file_are_rejected(self):
        (self.repo / "worker.c").write_bytes(b"user changes\n")
        with self.assertRaisesRegex(RuntimeError, "Unexpected original source"):
            profiles.check_and_apply(self.source, self.profile, apply=True)
        self.assertEqual((self.repo / "worker.c").read_bytes(), b"user changes\n")

    def test_unrelated_and_staged_edits_are_rejected(self):
        (self.repo / "meson.build").write_bytes(b"unrelated change\n")
        self.command(self.repo, "add", "meson.build")
        with self.assertRaisesRegex(RuntimeError, "Unexpected changes"):
            profiles.check_and_apply(self.source, self.profile, apply=True)
        self.assertIn(b"original", (self.repo / "worker.c").read_bytes())

    def test_failed_preflight_never_applies_first_file(self):
        profile = deepcopy(self.profile)
        change = deepcopy(profile["modules"][0]["files"][0])
        change["path"] = "meson.build"
        profile["modules"][0]["files"].append(change)
        with self.assertRaisesRegex(RuntimeError, "Unexpected original source"):
            profiles.check_and_apply(self.source, profile, apply=True)
        self.assertIn(b"original", (self.repo / "worker.c").read_bytes())

    def test_profile_digest_changes_with_patch_and_normalizes_line_endings(self):
        profile = deepcopy(self.profile)
        profile["limitations"].append("changed")
        self.assertNotEqual(profiles.provenance(profile)["source_profile_sha256"],
                            profiles.provenance(self.profile)["source_profile_sha256"])
        (self.repo / "worker.c").write_bytes((self.repo / "worker.c").read_bytes().replace(b"\n", b"\r\n"))
        profiles.check_and_apply(self.source, self.profile, apply=True)
        self.assertIn(b"custom", (self.repo / "worker.c").read_bytes())

    def test_profile_paths_cannot_escape_checkout(self):
        for path in ("../outside", "/outside", "C:/outside", "..\\outside"):
            with self.assertRaisesRegex(RuntimeError, "Unsafe profile path"):
                profiles.safe_path(path)

    def test_staged_profile_upgrades_an_existing_profile_state(self):
        original = (self.repo / "worker.c").read_bytes()
        intermediate = original.replace(b"original", b"first")
        final = intermediate.replace(b"first", b"final")
        (self.repo / "worker.c").write_bytes(intermediate)
        change = {
            "path": "worker.c",
            "before_sha256": profiles.digest(original),
            "after_sha256": profiles.digest(final),
            "steps": [
                {"before_sha256": profiles.digest(original),
                 "after_sha256": profiles.digest(intermediate),
                 "replacements": [{"old": "original", "new": "first", "count": 1}]},
                {"before_sha256": profiles.digest(intermediate),
                 "after_sha256": profiles.digest(final),
                 "replacements": [{"old": "first", "new": "final", "count": 1}]},
            ],
        }
        self.assertEqual(profiles.transformed(intermediate, change), final)
        self.assertEqual(profiles.transformed(original, change), final)
        self.assertEqual(profiles.transformed(final, change), final)

    def test_binary_audit_counts_chunk_boundaries_and_both_encodings(self):
        path = self.source / "fixture.bin"
        marker = b"gum-js-loop"
        path.write_bytes(b"\x00" * (1024 * 1024 - 3) + marker + b"\x00" +
                         "gum-js-loop".encode("utf-16-le") + b"\x00" * 60 + marker)
        self.assertEqual(audit_artifacts.scan_file(path), {
            "gum-js-loop (utf-8)": 2, "gum-js-loop (utf-16-le)": 1})


if __name__ == "__main__":
    unittest.main()
