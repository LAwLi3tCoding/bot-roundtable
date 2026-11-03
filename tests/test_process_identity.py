"""Synthetic Linux process identities; no signals or real process metadata."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import local_runtime as runtime


def stat(state="S", start="12345"):
    return "42 (synthetic (worker)) " + " ".join([state] + ["0"] * 18 + [start] + ["0"] * 5)


class ProcessIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = runtime.private_dir(Path(self.temp.name).resolve() / "instance")
        self.config = {"identity": "synthetic-identity"}
        self.argv = [
            "synthetic-python",
            str(Path(runtime.__file__).resolve()),
            "_serve",
            "--state-dir",
            str(self.directory),
            "--component",
            "server",
            "--identity",
            self.config["identity"],
        ]

    def tearDown(self):
        self.temp.cleanup()

    def capture(self, states=None, argv=None, boot="synthetic-boot"):
        states = states or [stat(), stat()] * 3
        with (
            patch.object(runtime.sys, "platform", "linux"),
            patch.object(Path, "read_text", side_effect=[boot, *states]),
            patch.object(
                Path, "read_bytes", return_value=("\0".join(argv or self.argv) + "\0").encode()
            ),
        ):
            return runtime.process_stamp(42)

    def record(self, stamp):
        runtime.write_json(
            self.directory / "server.pid.json",
            {"pid": 42, "stamp": stamp, "identity": self.config["identity"], "component": "server"},
            replace=True,
        )

    def test_kernel_identity_ignores_ps_wall_time_display(self):
        with patch.object(
            runtime, "legacy_process_stamp", side_effect=["time-one command", "time-two command"]
        ) as ps:
            first = self.capture()
            second = self.capture()
        self.assertEqual(first, second)
        ps.assert_not_called()
        self.assertEqual(json.loads(first[6:])[:2], ["synthetic-boot", "12345"])

    def test_pid_reuse_or_changed_boot_or_argv_never_owned(self):
        original = self.capture()
        self.record(original)
        foreign = self.argv.copy()
        foreign[-1] = "different-instance"
        changes = [
            self.capture(states=[stat(start="999"), stat(start="999")]),
            self.capture(boot="different-boot"),
            self.capture(argv=foreign),
            self.capture(argv=self.argv + ["extra"]),
        ]
        for changed in changes:
            with (
                self.subTest(changed=changed),
                patch.object(runtime.sys, "platform", "linux"),
                patch.object(runtime, "process_stamp", return_value=changed),
                self.assertRaisesRegex(runtime.Failure, "pid_ownership_mismatch"),
            ):
                runtime.owned(self.directory, self.config, "server")
        with patch.object(runtime, "process_stamp", return_value=original):
            self.assertEqual(runtime.owned(self.directory, self.config, "server"), 42)

    def test_exact_argv_rejects_command_embedded_in_another_argument(self):
        foreign = self.capture(argv=["synthetic-python", "foreign-script", " ".join(self.argv[1:])])
        self.record(foreign)
        with (
            patch.object(runtime, "process_stamp", return_value=foreign),
            self.assertRaisesRegex(runtime.Failure, "pid_ownership_mismatch"),
        ):
            runtime.owned(self.directory, self.config, "server")

    def test_exit_and_pid_reuse_during_snapshot(self):
        self.assertEqual(self.capture(states=[stat(), stat("Z")]), "")
        self.assertEqual(self.capture(states=[stat(), stat("X")]), "")
        with self.assertRaisesRegex(runtime.Failure, "process_identity_uncertain"):
            self.capture(states=[stat(), stat(start="999")])
        with (
            patch.object(runtime.sys, "platform", "linux"),
            patch.object(Path, "read_text", side_effect=["synthetic-boot", FileNotFoundError()]),
        ):
            self.assertEqual(runtime.process_stamp(42), "")

    def test_exit_transition_with_empty_command_is_rechecked(self):
        with (
            patch.object(runtime.sys, "platform", "linux"),
            patch.object(
                Path, "read_text", side_effect=["synthetic-boot", stat(), stat(), stat(), stat("Z")]
            ),
            patch.object(Path, "read_bytes", return_value=b""),
            patch.object(runtime.time, "sleep"),
        ):
            self.assertEqual(runtime.process_stamp(42), "")

    def test_unreadable_metadata_fails_closed(self):
        with (
            patch.object(runtime.sys, "platform", "linux"),
            patch.object(Path, "read_text", side_effect=PermissionError()),
            self.assertRaisesRegex(runtime.Failure, "process_identity_unavailable"),
        ):
            runtime.process_stamp(42)
        with self.assertRaisesRegex(runtime.Failure, "process_identity_uncertain"):
            self.capture(argv=[""])

    def test_legacy_pidfile_keeps_strict_stamp_and_exact_command_checks(self):
        current = self.capture()
        self.record("synthetic-legacy-stamp")
        with (
            patch.object(runtime.sys, "platform", "linux"),
            patch.object(runtime, "process_stamp", return_value=current),
            patch.object(runtime, "legacy_process_stamp", return_value="synthetic-legacy-stamp"),
        ):
            self.assertEqual(runtime.owned(self.directory, self.config, "server"), 42)
        with (
            patch.object(runtime.sys, "platform", "linux"),
            patch.object(runtime, "process_stamp", return_value=current),
            patch.object(runtime, "legacy_process_stamp", return_value="different-stamp"),
            self.assertRaisesRegex(runtime.Failure, "pid_ownership_mismatch"),
        ):
            runtime.owned(self.directory, self.config, "server")

    def test_non_linux_retains_ps_fallback(self):
        with (
            patch.object(runtime.sys, "platform", "darwin"),
            patch.object(runtime, "legacy_process_stamp", return_value="synthetic-ps-stamp"),
        ):
            self.assertEqual(runtime.process_stamp(42), "synthetic-ps-stamp")
