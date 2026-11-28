"""Doctor diagnostics use synthetic session data and never launch terminals."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "cc-session-restore"


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="doctor-private-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "private-config"
        self.config.mkdir()
        self.cwd = self.root / "private-project"
        self.cwd.mkdir()
        self.env = mock.patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.config),
            "CC_SESSION_RESTORE_CLAUDE_BIN": "fake-claude-never-execute",
            "CC_SESSION_RESTORE_TERMINAL": "windows-console",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        loader = importlib.machinery.SourceFileLoader("doctor_under_test", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.module = importlib.util.module_from_spec(spec)
        loader.exec_module(self.module)
        # Fixtures may live in the OS temp folder; include them as normal projects.
        self.module.TEMP_DIRS = set()

    def registry(self, name, data):
        folder = self.config / "sessions"
        folder.mkdir(exist_ok=True)
        path = folder / (name + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def transcript(self, sid, data):
        folder = self.config / "projects" / "private-project-encoding"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (sid + ".jsonl")
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        return path

    def doctor(self, verbose=False, argv=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output), \
                mock.patch.object(self.module, "is_alive", side_effect=lambda d: d.get("pid") == 111), \
                mock.patch.object(self.module, "launch", side_effect=AssertionError("doctor launched sessions")), \
                mock.patch.object(self.module, "pick", side_effect=AssertionError("doctor opened picker")):
            self.module.main(argv if argv is not None else ["doctor"] + (["--verbose"] if verbose else []))
        return output.getvalue()

    def test_empty_config_reports_environment_and_zero_counts(self):
        output = self.doctor()
        for label in ("Python", "OS", "Terminal", "Boot", "Config directory: found"):
            self.assertIn(label, output)
        self.assertRegex(output.lower(), r"version")
        self.assertIn("Registry files: 0 parsed, 0 unparseable, 0 running, 0 dead", output)
        self.assertIn("Transcripts: 0 scanned, 0 included, 0 skipped", output)
        self.assertNotIn(str(self.config), output)

    def test_registry_counts_and_schema_drift_are_private_by_default(self):
        base = {"sessionId": "private-running-id", "pid": 111,
                "startedAt": 123456789, "entrypoint": "cli", "kind": "interactive"}
        self.registry("running", dict(base, privateUnknownField="private-field-value",
                                      name="private-session-title"))
        self.registry("dead", dict(base, sessionId="private-dead-id", pid=222))
        self.registry("missing", {"sessionId": "private-incomplete-id"})
        self.registry("invalid", ["not an object"])
        (self.config / "sessions" / "broken.json").write_text("{broken", encoding="utf-8")
        output = self.doctor()
        self.assertIn("Registry files: 3 parsed, 2 unparseable, 1 running, 2 dead", output)
        self.assertIn("Missing registry fields (files):", output)
        self.assertRegex(output, r"pid:\s*1")
        self.assertIn("Unknown registry fields: 1 distinct", output)
        for secret in (str(self.config), "private-running-id", "private-dead-id",
                       "private-session-title", "privateUnknownField", "private-field-value"):
            self.assertNotIn(secret, output)

    def test_transcript_skip_counts(self):
        self.transcript("private-included-id", {"cwd": str(self.cwd), "entrypoint": "cli",
                                               "type": "custom-title", "customTitle": "private-title"})
        self.transcript("private-no-cwd-id", {"type": "user", "message": "fake"})
        self.transcript("private-sdk-id", {"cwd": str(self.cwd), "entrypoint": "sdk"})
        self.transcript("private-missing-id", {"cwd": str(self.root / "missing"), "entrypoint": "cli"})
        output = self.doctor()
        self.assertIn("Transcripts: 4 scanned, 1 included, 3 skipped", output)
        for reason, count in (("no cwd", 1), ("SDK/background", 1), ("missing folder", 1), ("unreadable", 0)):
            self.assertIn("  {}: {}".format(reason, count), output)
        for secret in (str(self.cwd), "private-included-id", "private-title", "private-project-encoding"):
            self.assertNotIn(secret, output)

    def test_unreadable_transcript_is_counted_without_private_error(self):
        path = self.transcript("private-unreadable-id", {"cwd": str(self.cwd), "entrypoint": "cli"})
        real_open = open

        def denied(file, *args, **kwargs):
            if Path(file) == path:
                raise PermissionError("private-error-detail " + str(path))
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=denied):
            output = self.doctor()
        self.assertIn("Transcripts: 1 scanned, 0 included, 1 skipped", output)
        self.assertIn("  unreadable: 1", output)
        self.assertNotIn("private-error-detail", output)
        self.assertNotIn(str(path), output)

    def test_verbose_explicitly_reveals_private_details(self):
        self.registry("dead", {"sessionId": "private-verbose-id", "pid": 222,
                               "entrypoint": "cli", "kind": "interactive",
                               "startedAt": 123456789, "privateUnknownField": "fake"})
        self.transcript("private-verbose-id", {"cwd": str(self.cwd), "entrypoint": "cli",
                                              "type": "custom-title", "customTitle": "private-verbose-title"})
        output = self.doctor(verbose=True)
        self.assertIn(str(self.config), output)
        self.assertIn("privateUnknownField", output)
        self.assertIn(str(self.cwd), output)
        self.assertIn("private-verbose-title", output)

    def test_scan_limit_reconciles_scanned_included_and_skipped(self):
        for index in range(4):
            self.transcript("private-limited-{}".format(index), {"type": "user"})
        with mock.patch.object(self.module, "SCAN_LIMIT", 2):
            output = self.doctor()
        self.assertIn("Transcripts: 2 scanned, 0 included, 2 skipped", output)
        self.assertIn("  no cwd: 2", output)

    def test_untrusted_terminal_override_is_private_by_default(self):
        secret = "private-terminal-path-and-title"
        with mock.patch.dict(os.environ, {"CC_SESSION_RESTORE_TERMINAL": secret}):
            output = self.doctor()
        self.assertIn("Terminal", output)
        self.assertNotIn(secret, output)

    def test_headless_linux_and_unknown_boot_time(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.multiple(self.module, IS_WINDOWS=False, IS_MAC=False, IS_WSL=False), \
                mock.patch("shutil.which", return_value=None), \
                mock.patch.object(self.module, "boot_info", return_value=(None, "procfs btime")):
            output = self.doctor()
        self.assertIn("Terminal: none detected", output)
        self.assertIn("Boot time: unknown (procfs btime)", output)

    def test_missing_config_cli_exits_successfully_without_launching(self):
        missing = self.root / "private-nonexistent-config"
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(missing)
        result = subprocess.run([sys.executable, str(SCRIPT), "doctor"], env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Config directory: not found", result.stdout)
        self.assertNotIn(str(missing), result.stdout + result.stderr)

    def test_registry_and_projects_directory_presence(self):
        output = self.doctor()
        self.assertIn("Registry directory: not found", output)
        self.assertIn("Projects directory: not found", output)
        (self.config / "sessions").mkdir()
        (self.config / "projects").mkdir()
        output = self.doctor()
        self.assertIn("Registry directory: found", output)
        self.assertIn("Projects directory: found", output)
        self.assertIn("Unreadable project folders: 0", output)

    def test_unlistable_directories_report_unreadable_without_private_errors(self):
        registry = self.config / "sessions"
        projects = self.config / "projects"
        registry.mkdir()
        projects.mkdir()
        real_iterdir = Path.iterdir
        secret = "private-discovery-error-detail"
        for target, label in ((self.config, "Config"), (registry, "Registry"), (projects, "Projects")):
            with self.subTest(directory=label):
                def denied(path):
                    if path == target:
                        raise PermissionError(secret + " " + str(path))
                    return real_iterdir(path)

                with mock.patch.object(Path, "iterdir", denied):
                    output = self.doctor()
                    verbose = self.doctor(verbose=True)
                self.assertIn(label + " directory: unreadable", output)
                self.assertNotIn(secret, output)
                self.assertNotIn(str(target), output)
                self.assertIn(str(target), verbose)
                self.assertIn(secret, verbose)

    def test_unlistable_project_folder_is_counted_and_other_folders_are_scanned(self):
        self.transcript("private-readable-id", {"cwd": str(self.cwd), "entrypoint": "cli"})
        unreadable = self.config / "projects" / "private-unlistable-project"
        unreadable.mkdir()
        real_iterdir = Path.iterdir
        secret = "private-project-list-error"

        def denied(path):
            if path == unreadable:
                raise OSError(secret + " " + str(path))
            return real_iterdir(path)

        with mock.patch.object(Path, "iterdir", denied):
            output = self.doctor()
            verbose = self.doctor(verbose=True)
        self.assertIn("Projects directory: found", output)
        self.assertIn("Unreadable project folders: 1", output)
        self.assertIn("Transcripts: 1 scanned, 1 included, 0 skipped", output)
        self.assertNotIn(str(unreadable), output)
        self.assertNotIn(secret, output)
        self.assertIn(str(unreadable), verbose)
        self.assertIn(secret, verbose)

    def test_registry_id_counts_are_validated_distinct_and_exclude_running_ids(self):
        base = {"pid": 222, "entrypoint": "cli", "kind": "interactive"}
        for name, sid in (("missing", None), ("number", 123), ("empty", ""),
                          ("bad", "private/invalid-id")):
            data = dict(base)
            if sid is not None:
                data["sessionId"] = sid
            self.registry(name, data)
        self.registry("dead-one", dict(base, sessionId="private-dead-id"))
        self.registry("dead-duplicate", dict(base, sessionId="private-dead-id"))
        self.registry("stale-running", dict(base, sessionId="private-running-id"))
        self.registry("running", dict(base, sessionId="private-running-id", pid=111))
        self.registry("sdk", dict(base, sessionId="private-sdk-id", entrypoint="sdk"))
        self.registry("background", dict(base, sessionId="private-background-id", kind="background"))
        output = self.doctor()
        self.assertIn("Invalid registry session IDs: 4", output)
        self.assertIn("Dead CLI/interactive session IDs: 1", output)
        self.assertIn("Dead files excluded: 4 invalid ID, 2 non-interactive or non-CLI, "
                      "2 duplicate or also running", output)
        self.assertNotIn("private-dead-id", output)
        self.assertNotIn("private-running-id", output)

    def test_doctor_command_after_safe_options_stays_diagnostic(self):
        for argv in (["--verbose", "doctor"], ["-y", "doctor"]):
            with self.subTest(argv=argv):
                output = self.doctor(argv=argv)
                self.assertIn("Registry files:", output)
                self.assertIn("Transcripts:", output)
                if "--verbose" in argv:
                    self.assertIn(str(self.config), output)

    def test_open_doctor_is_a_session_selector_not_a_diagnostic_command(self):
        session = {"id": "doctor", "running": False}
        output = io.StringIO()
        with mock.patch.object(self.module, "recent_sessions", return_value=[session]), \
                mock.patch.object(self.module, "launch", return_value=[]) as launch, \
                mock.patch.object(self.module, "doctor", side_effect=AssertionError("wrong command")), \
                contextlib.redirect_stdout(output):
            self.module.main(["--open", "doctor"])
        launch.assert_called_once_with([session], False, None)
        self.assertNotIn("Registry files:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
