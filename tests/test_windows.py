"""Native Windows integration checks; never open a window or read real sessions."""
import base64
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "cc-session-restore"
loader = importlib.machinery.SourceFileLoader("restore_windows_tests", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
restore = importlib.util.module_from_spec(spec)
loader.exec_module(restore)


@unittest.skipUnless(os.name == "nt", "native Windows integration")
class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ccsr-windows-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "space & caret^ %CCSR_TEST_EXPAND% ! (x) '"
        self.folder.mkdir()
        self.capture = self.folder / "capture.py"
        self.capture.write_text(
            "import json, os, sys\n"
            "print('CAPTURE:' + json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd()}))\n",
            encoding="utf-8")
        self.shim = self.folder / "fake claude.cmd"
        self.shim.write_text('@"' + sys.executable + '" "%~dp0capture.py" %*\r\n')
        self.session = {"cwd": str(self.folder), "title": "fake; title & !",
                        "id": "session & ^ %CCSR_TEST_EXPAND% ! (x) space"}
        self.env = mock.patch.dict(os.environ, {"CCSR_TEST_EXPAND": "SHOULD_NOT_EXPAND"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_hidden(self, argv, **kw):
        return subprocess.run(argv, input="exit\r\n", text=True, capture_output=True,
                              timeout=30, creationflags=subprocess.CREATE_NO_WINDOW, **kw)

    def captured(self, result):
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        lines = [line for line in result.stdout.splitlines() if line.startswith("CAPTURE:")]
        self.assertTrue(lines, result.stderr + result.stdout)
        line = lines[0]
        return json.loads(line[len("CAPTURE:"):])

    def test_windows_argument_splitting(self):
        self.assertEqual(restore.windows_args('--model opus --name="two words" "" "C:\\a b"'),
                         ["--model", "opus", "--name=two words", "", "C:\\a b"])

    def test_trailing_backslashes_in_cmd_forwarding(self):
        extra = subprocess.list2cmdline([str(self.capture), "C:\\a b\\", "C:\\end\\\\"])
        # As in an npm shim, forward arguments to a native executable with %*.
        code = "import json,os,sys;print('CAPTURE:'+json.dumps({'args':sys.argv[1:],'cwd':os.getcwd()}))"
        fake = self.folder / "fake executable.cmd"
        fake.write_text('@"' + sys.executable + '" -c "' + code + '" %*\r\n')
        with mock.patch.object(restore, "CLAUDE_BIN", str(fake)), \
                mock.patch.object(restore, "CLAUDE_ARGS", extra):
            argv, kw = restore.launch_cmd(self.session, "windows-console")
        result = self.captured(self.run_hidden(argv, cwd=kw["cwd"]))
        self.assertEqual(result["args"], ["--resume", self.session["id"], str(self.capture),
                                          "C:\\a b\\", "C:\\end\\\\"])

    def test_cmd_rejects_literal_quotes_without_launching(self):
        lines = []
        with mock.patch.object(restore, "CLAUDE_BIN", str(self.shim)), \
                mock.patch.object(restore, "CLAUDE_ARGS", '--value \\\"quoted\\\"'), \
                mock.patch.object(restore.subprocess, "Popen") as popen:
            errors = restore.launch([self.session], terminal="windows-console", log=lines.append)
        self.assertIn("double quotes", errors[0])
        popen.assert_not_called()

    def test_console_launch_keeps_keyboard_and_screen_handles(self):
        with mock.patch.object(restore, "CLAUDE_BIN", str(self.shim)), \
                mock.patch.object(restore, "CLAUDE_ARGS", ""), \
                mock.patch.object(restore.subprocess, "Popen") as popen, \
                mock.patch.object(restore.time, "sleep"), mock.patch("builtins.print"):
            self.assertEqual(restore.launch([self.session], terminal="windows-console"), [])
        kw = popen.call_args[1]
        self.assertEqual(kw, {"cwd": str(self.folder), "creationflags": subprocess.CREATE_NEW_CONSOLE})

    def test_detection_prefers_windows_terminal_then_console(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(restore, "IS_WSL", False), \
                mock.patch.object(restore.shutil, "which", return_value="wt.exe"):
            self.assertEqual(restore.detect_terminal(), "windows-terminal")
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(restore, "IS_WSL", False), \
                mock.patch.object(restore.shutil, "which", return_value=None):
            self.assertEqual(restore.detect_terminal(), "windows-console")

    def test_exact_console_command_runs_cmd_shim_in_original_folder(self):
        with mock.patch.object(restore, "CLAUDE_BIN", str(self.shim)), \
                mock.patch.object(restore, "CLAUDE_ARGS", '--name="two words" "" "a&b^%!()"'):
            argv, kw = restore.launch_cmd(self.session, "windows-console")
        self.assertTrue(kw.pop("console"))
        self.assertEqual(kw.pop("creationflags"), subprocess.CREATE_NEW_CONSOLE)
        result = self.captured(self.run_hidden(argv, **kw))
        self.assertEqual(os.path.normcase(result["cwd"]), os.path.normcase(str(self.folder)))
        self.assertEqual(result["args"], ["--resume", self.session["id"], "--name=two words", "", "a&b^%!()"])

    def test_path_resolves_npm_style_cmd_shim(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.folder) + os.pathsep + os.environ["PATH"]}), \
                mock.patch.object(restore, "CLAUDE_BIN", "fake claude"), \
                mock.patch.object(restore, "CLAUDE_ARGS", ""):
            argv, kw = restore.launch_cmd(self.session, "windows-console")
        result = self.captured(self.run_hidden(argv, cwd=kw["cwd"]))
        self.assertEqual(result["args"], ["--resume", self.session["id"]])

    def test_explicit_powershell_shim(self):
        policy = self.run_hidden(["powershell.exe", "-NoProfile", "-Command", "Get-ExecutionPolicy"])
        if any(p in policy.stdout for p in ("Restricted", "AllSigned")):
            self.skipTest("local policy blocks unsigned .ps1 files; policy is preserved")
        shim = self.folder / "fake claude.ps1"
        q = lambda s: "'" + str(s).replace("'", "''") + "'"
        shim.write_text("& " + q(sys.executable) + " " + q(self.capture) + " @args\n")
        with mock.patch.object(restore, "CLAUDE_BIN", str(shim)), \
                mock.patch.object(restore, "CLAUDE_ARGS", '"a&b^%!()"'):
            argv, kw = restore.launch_cmd(self.session, "windows-console")
        raw = self.run_hidden(argv, cwd=kw["cwd"])
        if "running scripts is disabled" in raw.stderr or "is not digitally signed" in raw.stderr:
            self.skipTest("local policy blocks unsigned .ps1 files; policy is preserved")
        result = self.captured(raw)
        self.assertEqual(result["args"], ["--resume", self.session["id"], "a&b^%!()"])

    def test_dry_run_is_runnable_powershell(self):
        lines = []
        with mock.patch.object(restore, "CLAUDE_BIN", str(self.shim)), \
                mock.patch.object(restore, "CLAUDE_ARGS", ""), \
                mock.patch.object(restore.subprocess, "Popen") as popen:
            restore.launch([self.session], dry_run=True, terminal="windows-console", log=lines.append)
            popen.assert_not_called()
        result = self.captured(self.run_hidden(["powershell.exe", "-NoProfile", "-Command", lines[0]]))
        self.assertEqual(result["args"], ["--resume", self.session["id"]])
        self.assertEqual(os.path.normcase(result["cwd"]), os.path.normcase(str(self.folder)))

    def test_windows_terminal_keeps_data_out_of_command_syntax(self):
        with mock.patch.object(restore, "CLAUDE_BIN", str(self.shim)), \
                mock.patch.object(restore, "CLAUDE_ARGS", ""):
            argv, kw = restore.launch_cmd(self.session, "windows-terminal")
        self.assertEqual(argv[0], "wt.exe")
        self.assertIn("fake\\; title & !", argv)
        self.assertIn(str(self.folder), argv)
        self.assertEqual(kw, {})
        script = base64.b64decode(argv[-1]).decode("utf-16-le")
        self.assertIn("/d /v:off /s /k", script)
        self.assertIn(self.session["id"], script)

    def test_live_dead_and_invalid_pids_and_boot_time(self):
        self.assertTrue(restore._alive_windows(os.getpid()))
        for pid in (0, -1, True, None, 2 ** 32 + os.getpid()):
            self.assertFalse(restore._alive_windows(pid))
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertTrue(restore._alive_windows(proc.pid))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
        self.assertFalse(restore._alive_windows(proc.pid))
        boot = restore.boot_time()
        self.assertIsInstance(boot, float)
        self.assertLess(boot, time.time())
        self.assertGreater(boot, 0)

    def test_real_shortcut_readback_in_temporary_folder(self):
        shortcut = self.folder / "test sessions.lnk"
        arguments = subprocess.list2cmdline([str(SCRIPT), "--gui"])
        restore.windows_shortcut("powershell.exe", sys.executable, arguments, self.folder, shortcut)
        q = "'" + str(shortcut).replace("'", "''") + "'"
        result = self.run_hidden(["powershell.exe", "-NoProfile", "-Command",
                                  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + q + ");"
                                  "$s | Select-Object TargetPath,Arguments,WorkingDirectory,WindowStyle | ConvertTo-Json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["TargetPath"].lower(), sys.executable.lower())
        self.assertEqual(data["Arguments"], arguments)
        self.assertEqual(data["WorkingDirectory"], str(self.folder))
        self.assertEqual(data["WindowStyle"], 7)

    def test_install_selects_pythonw_with_console_fallback(self):
        for exists in (True, False):
            with self.subTest(pythonw=exists), mock.patch.object(restore, "IS_WSL", False), \
                    mock.patch.object(restore.Path, "exists", return_value=exists), \
                    mock.patch.object(restore, "windows_shortcut") as shortcut, \
                    mock.patch("builtins.print"):
                restore.install()
            args = shortcut.call_args[0]
            expected = Path(sys.executable).with_name("pythonw.exe") if exists else sys.executable
            self.assertEqual(str(args[1]), str(expected))
            self.assertEqual(args[2], subprocess.list2cmdline([str(SCRIPT), "--gui"]))


if __name__ == "__main__":
    unittest.main()
