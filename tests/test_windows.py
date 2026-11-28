"""Native Windows integration checks; never open a window or read real sessions."""
import base64
import re
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


# Every character PowerShell reads as a single quote, plus $(), a backtick and ;.
HOSTILE = "' \u2018 \u2019 \u201a \u201b $(calc) `x ;"
# The same without U+201B, which isn't in the ANSI code page WScript.Shell needs.
HOSTILE_ANSI = "' \u2018 \u2019 \u201a $(calc) `x ;"
EXPR = re.compile(r"\(\[System\.Text\.Encoding\]::UTF8\.GetString\("
                  r"\[System\.Convert\]::FromBase64String\('([A-Za-z0-9+/=]*)'\)\)\)")
PLAIN = re.compile(r"'([A-Za-z0-9._=+/-]*)'")


def ps_values(source):
    """The string values in generated PowerShell, and the source with them cut out."""
    values = [base64.b64decode(m).decode("utf-8") for m in EXPR.findall(source)]
    return values, EXPR.sub("<EXPR>", source)


def ps_args(line):
    """Decode a printed '& a b c' line made only of ps_literal() values."""
    tokens = re.findall(EXPR.pattern + "|" + PLAIN.pattern, line)
    rebuilt = " ".join(("'" + p + "'") if not b else restore.ps_literal(base64.b64decode(b).decode("utf-8"))
                            for b, p in tokens)
    assert rebuilt == line.strip(), (rebuilt, line)  # nothing else in the line
    args = [base64.b64decode(b).decode("utf-8") if b else p for b, p in tokens]
    return args


def assert_no_raw(test, source, values):
    """No quote-like, $() or backtick outside base64, and no raw untrusted value."""
    _, rest = ps_values(source)
    rest = PLAIN.sub("<LIT>", rest)
    for bad in ("'", "\u2018", "\u2019", "\u201a", "\u201b", "$(", "`"):
        test.assertNotIn(bad, rest, source)
    for v in values:
        test.assertNotIn(v, source)


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
        self.folder = Path(self.temp.name) / ("space & caret^ %CCSR_TEST_EXPAND% ! (x) \u00e9 \u65e5\u672c "
                                              + HOSTILE)
        self.folder.mkdir()
        self.capture = self.folder / "capture.py"
        self.capture.write_text(
            "import json, os, sys\n"
            "print('CAPTURE:' + json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd()}))\n",
            encoding="utf-8")
        self.shim = self.folder / "fake claude.cmd"
        self.shim.write_text('@"' + sys.executable + '" "%~dp0capture.py" %*\r\n')
        self.session = {"cwd": str(self.folder), "title": "fake; title & ! " + HOSTILE,
                        "id": "session & ^ %CCSR_TEST_EXPAND% ! (x) space \u00e9 \u65e5\u672c " + HOSTILE}
        self.env = mock.patch.dict(os.environ, {"CCSR_TEST_EXPAND": "SHOULD_NOT_EXPAND"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_hidden(self, argv, **kw):
        kw.setdefault("errors", "replace")  # cmd echoes non-ASCII folders in the OEM code page
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
        self.assertTrue(os.path.samefile(result["cwd"], self.folder))
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
        q = restore.ps_literal
        # A BOM makes Windows PowerShell read the non-ASCII path as UTF-8.
        shim.write_text("& " + q(sys.executable) + " " + q(self.capture) + " @args\n",
                        encoding="utf-8-sig")
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
        self.assertTrue(os.path.samefile(result["cwd"], self.folder))

    def test_windows_terminal_keeps_data_out_of_command_syntax(self):
        with mock.patch.object(restore, "CLAUDE_BIN", str(self.shim)), \
                mock.patch.object(restore, "CLAUDE_ARGS", ""):
            argv, kw = restore.launch_cmd(self.session, "windows-terminal")
        self.assertEqual(argv[0], "wt.exe")
        self.assertIn(restore.wt(["fake; title & ! " + HOSTILE])[0], argv)
        self.assertNotIn("-d", argv)  # wt would expand %CCSR_TEST_EXPAND% in -d
        self.assertEqual(kw, {})
        script = base64.b64decode(argv[-1]).decode("utf-16-le")
        self.assertTrue(script.startswith("Set-Location -LiteralPath " + restore.ps_literal(self.folder) + ";"))
        assert_no_raw(self, script, [str(self.folder), self.session["id"]])
        self.assertIn("/d /v:off /s /k", script)
        self.assertIn(self.session["id"], ps_values(script)[0])

    def test_windows_terminal_bootstrap_runs_in_original_folder(self):
        with mock.patch.object(restore, "CLAUDE_BIN", str(self.shim)), \
                mock.patch.object(restore, "CLAUDE_ARGS", ""):
            argv, _ = restore.launch_cmd(self.session, "windows-terminal")
        # Run only what wt would start in the tab, hidden and from elsewhere.
        bootstrap = argv[argv.index("powershell.exe"):]
        result = self.captured(self.run_hidden(bootstrap, cwd=os.path.expanduser("~")))
        self.assertTrue(os.path.samefile(result["cwd"], self.folder))
        self.assertEqual(result["args"], ["--resume", self.session["id"]])

    def test_pid_reuse_is_dead(self):
        now_ms = time.time() * 1000
        self.assertTrue(restore._alive_windows(os.getpid(), now_ms))
        self.assertFalse(restore._alive_windows(os.getpid(), now_ms - 3600 * 1000))

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
        # WScript.Shell can't save shortcuts outside the ANSI code page, so this
        # folder keeps the shell metacharacters but not the non-ASCII part.
        folder = Path(self.temp.name) / ("space & caret^ %CCSR_TEST_EXPAND% ! (x) " + HOSTILE_ANSI)
        folder.mkdir()
        shortcut = folder / "test sessions.lnk"
        arguments = subprocess.list2cmdline([str(SCRIPT), "--gui"])
        restore.windows_shortcut("powershell.exe", sys.executable, arguments, folder, shortcut)
        q = restore.ps_literal(shortcut)
        result = self.run_hidden(["powershell.exe", "-NoProfile", "-Command",
                                  "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                                  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + q + ");"
                                  "$s | Select-Object TargetPath,Arguments,WorkingDirectory,WindowStyle | ConvertTo-Json"],
                                 encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["TargetPath"].lower(), sys.executable.lower())
        self.assertEqual(data["Arguments"], arguments)
        self.assertEqual(data["WorkingDirectory"], str(folder))
        self.assertEqual(data["WindowStyle"], 7)

    def test_install_rejects_non_ansi_paths_before_powershell(self):
        with mock.patch.object(restore.subprocess, "run") as run, \
                self.assertRaises(SystemExit) as cm:
            restore.windows_shortcut("powershell.exe", sys.executable, "--gui", self.folder,
                                     self.folder / "x.lnk")
        run.assert_not_called()
        self.assertIn("code page", str(cm.exception))

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


def ps51_join(args):
    """Windows PowerShell 5.1's native command line: quote only on whitespace
    outside quotes, never escape, and drop empty arguments."""
    out = []
    for a in args:
        if not a:
            continue
        quoted, needs = False, False
        for c in a:
            if c == '"':
                quoted = not quoted
            elif c.isspace() and not quoted:
                needs = True
        out.append('"' + a + '"' if needs else a)
    return " ".join(out)


def argv_w(line):
    """CommandLineToArgvW's rules for the arguments after argv[0]."""
    args, cur, have, quoted, i = [], "", False, False, 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            n = len(line[i:]) - len(line[i:].lstrip("\\"))
            if line[i + n:i + n + 1] == '"':
                cur += "\\" * (n // 2)
                if n % 2:
                    cur += '"'
                    i += n + 1
                else:
                    i += n
                have = True
                continue
            cur, have, i = cur + "\\" * n, True, i + n
            continue
        if c == '"':
            if quoted and line[i + 1:i + 2] == '"':
                cur, i = cur + '"', i + 2
                continue
            quoted, have, i = not quoted, True, i + 1
            continue
        if c.isspace() and not quoted:
            if have:
                args.append(cur)
            cur, have, i = "", False, i + 1
            continue
        cur, have, i = cur + c, True, i + 1
    if have:
        args.append(cur)
    return args


class PortableStringTests(unittest.TestCase):
    """Pure string building and mocked ctypes; safe to run on any OS."""

    def dry_run_argv(self, title):
        session = {"cwd": "C:\\Users\\me\\proj", "title": title, "id": "abc"}
        lines = []
        with mock.patch.object(restore, "IS_WINDOWS", True), \
                mock.patch.object(restore, "CLAUDE_BIN", "claude"), \
                mock.patch.object(restore, "CLAUDE_ARGS", ""), \
                mock.patch.object(restore.shutil, "which", return_value=None), \
                mock.patch.object(restore.subprocess, "Popen") as popen:
            errors = restore.launch([session], dry_run=True, terminal="windows-terminal",
                                    log=lines.append)
            popen.assert_not_called()
            argv, _ = restore.launch_cmd(session, "windows-terminal")
        self.assertEqual(errors, [])
        line = lines[0]
        self.assertTrue(line.startswith("& 'wt.exe' "))
        self.assertEqual(ps_args(line[2:]), argv)  # what PowerShell hands wt
        assert_no_raw(self, line, [session["title"]] if len(session["title"]) > 1 else [])
        return argv

    def test_emulators_reproduce_the_reported_split(self):
        self.assertEqual(argv_w(ps51_join(["--title", 'a b" calc.exe "c'])),
                         ["--title", "a b", "calc.exe", "c"])

    def test_dry_run_titles_survive_powershell_5_and_7(self):
        for title, expect in [('a b" calc.exe "c', "a b' calc.exe 'c"),
                              ('Fix "login" bug', "Fix 'login' bug"),
                              ("-x --help", "x --help"), ("trailing \\ \\", "trailing"),
                              ('"', "'"), (" - ", "claude"), ("caf\u00e9 \u65e5\u672c; a", "caf\u00e9 \u65e5\u672c\\; a")]:
            with self.subTest(title=title):
                argv = self.dry_run_argv(title)
                self.assertEqual(argv[argv.index("--title") + 1], expect)
                self.assertEqual(argv_w(ps51_join(argv[1:])), argv[1:])  # Windows PowerShell 5.1
                self.assertEqual(argv_w(subprocess.list2cmdline(argv[1:])), argv[1:])  # PS 7.3+, Popen
                self.assertTrue(all(restore.ps_native_safe(a) for a in argv))

    def test_ps_str_round_trips_any_text(self):
        for value in ("", "plain-1.0", HOSTILE, "C:\\a b\\", "\u00e9 \u65e5\u672c", '"$env:X"'):
            expr = restore.ps_literal(value)
            self.assertEqual(ps_args(expr), [value])
            if value not in ("", "plain-1.0"):
                assert_no_raw(self, expr, [value])

    def hostile_session(self):
        return {"cwd": "C:\\x" + HOSTILE + "\\proj", "title": "t " + HOSTILE, "id": "id" + HOSTILE}

    def test_bootstrap_has_no_raw_untrusted_text(self):
        s = self.hostile_session()
        for claude in ("claude", "C:\\npm\\claude.ps1"):
            with self.subTest(claude=claude), mock.patch.object(restore, "CLAUDE_BIN", claude), \
                    mock.patch.object(restore, "CLAUDE_ARGS", ""), \
                    mock.patch.object(restore.shutil, "which", return_value=None):
                argv, _ = restore.launch_cmd(s, "windows-terminal")
            script = base64.b64decode(argv[-1]).decode("utf-16-le")
            assert_no_raw(self, script, [s["cwd"], s["id"]])
            values, _ = ps_values(script)
            self.assertIn(s["cwd"], values)
            self.assertIn(s["id"], values)

    def test_dry_run_lines_have_no_raw_untrusted_text(self):
        s = self.hostile_session()
        for terminal in ("windows-terminal", "windows-console"):
            lines = []
            with self.subTest(terminal=terminal), mock.patch.object(restore, "IS_WINDOWS", True), \
                    mock.patch.object(restore, "CLAUDE_BIN", "claude"), \
                    mock.patch.object(restore, "CLAUDE_ARGS", ""), \
                    mock.patch.object(restore.shutil, "which", return_value=None), \
                    mock.patch.object(restore.subprocess, "Popen") as popen:
                self.assertEqual(restore.launch([s], dry_run=True, terminal=terminal,
                                                log=lines.append), [])
                popen.assert_not_called()
            assert_no_raw(self, lines[0], [s["cwd"], s["title"], restore.wt_title(s["title"])])
            values, _ = ps_values(lines[0])
            if terminal == "windows-console":
                self.assertEqual(values[0], s["cwd"])  # Set-Location
            else:
                self.assertIn(restore.wt([restore.wt_title(s["title"])])[0], values)

    def test_shortcut_writer_has_no_raw_untrusted_text(self):
        folder = "C:\\x" + HOSTILE
        with mock.patch.object(restore, "IS_WINDOWS", False), \
                mock.patch.object(restore.subprocess, "run") as run:
            restore.windows_shortcut("powershell.exe", folder + "\\python.exe", '"a" ' + HOSTILE,
                                     folder, folder + "\\x.lnk")
        ps = run.call_args[0][0][3]
        assert_no_raw(self, ps, [folder])
        values, _ = ps_values(ps)
        self.assertEqual(values[:4], [folder + "\\x.lnk", folder + "\\python.exe", '"a" ' + HOSTILE, folder])

    @unittest.skipIf(os.name == "nt", "builds a POSIX clone path")
    def test_wsl_install_encodes_the_clone_path(self):
        me = "/home/me/x" + HOSTILE + "/cc-session-restore"
        with mock.patch.object(restore, "IS_WSL", True), \
                mock.patch.object(restore, "__file__", me), \
                mock.patch.object(restore, "ephemeral_install", return_value=False), \
                mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}), \
                mock.patch.object(restore, "windows_shortcut") as shortcut, \
                mock.patch("builtins.print"):
            restore.install()
        arguments = shortcut.call_args[0][2]
        script = base64.b64decode(arguments.split("-EncodedCommand ")[1]).decode("utf-16-le")
        self.assertTrue(script.startswith("Start-Process wsl.exe -WindowStyle Hidden -ArgumentList "))
        assert_no_raw(self, script, [me, str(Path(me).parent)])
        values, _ = ps_values(script)
        self.assertEqual(values, ['-d Ubuntu --cd "%s" -- "%s" "./cc-session-restore" --gui'
                                  % (Path(me).parent, sys.executable or "python3")])

    def test_native_safety_check(self):
        for bad in ("", 'a"b', "C:\\a b\\"):
            self.assertFalse(restore.ps_native_safe(bad))
        for good in ("C:\\", "a b", "x\\"):
            self.assertTrue(restore.ps_native_safe(good))

    def fake_kernel32(self, created_ms, exit_code=259, open_ok=True, times_ok=True):
        ticks = int(created_ms) * 10000 + 116444736000000000
        calls = []

        def open_process(access, inherit, pid):
            calls.append(("open", access, pid))
            return 1234 if open_ok else None

        def exit_code_process(h, code):
            code._obj.value = exit_code
            return 1

        def process_times(h, created, exited, kernel, user):
            created._obj.low, created._obj.high = ticks & 0xffffffff, ticks >> 32
            return 1 if times_ok else 0

        def close(h):
            calls.append(("close", h))
            return 1

        k32 = mock.Mock(spec=["OpenProcess", "GetExitCodeProcess", "GetProcessTimes", "CloseHandle"])
        k32.OpenProcess, k32.GetExitCodeProcess = open_process, exit_code_process
        k32.GetProcessTimes, k32.CloseHandle = process_times, close
        return k32, calls

    def alive(self, k32, started_ms, last_error=0):
        import ctypes
        with mock.patch.object(restore, "_win_dll", return_value=k32) as dll, \
                mock.patch.object(ctypes, "get_last_error", return_value=last_error, create=True):
            result = restore._alive_windows(4242, started_ms)
        dll.assert_called_with("kernel32")
        return result

    def test_alive_windows_checks_creation_time_for_pid_reuse(self):
        started = 1_700_000_000_000
        k32, calls = self.fake_kernel32(started - 500)
        self.assertTrue(self.alive(k32, started))
        self.assertEqual(calls, [("open", 0x1000, 4242), ("close", 1234)])
        k32, _ = self.fake_kernel32(started + restore.PID_REUSE_SLACK_MS - 1)
        self.assertTrue(self.alive(k32, started))
        k32, calls = self.fake_kernel32(started + restore.PID_REUSE_SLACK_MS + 1000)
        self.assertFalse(self.alive(k32, started))  # pid reused by a newer process
        self.assertIn(("close", 1234), calls)
        k32, _ = self.fake_kernel32(started + 3600 * 1000)
        self.assertTrue(self.alive(k32, 0))  # no startedAt: can't check
        k32, _ = self.fake_kernel32(started + 3600 * 1000, times_ok=False)
        self.assertTrue(self.alive(k32, started))
        k32, _ = self.fake_kernel32(started, exit_code=0)
        self.assertFalse(self.alive(k32, started))
        k32, _ = self.fake_kernel32(started, open_ok=False)
        self.assertTrue(self.alive(k32, started, last_error=5))  # access denied
        self.assertFalse(self.alive(k32, started, last_error=87))  # no such process

    def test_is_alive_passes_started_at(self):
        with mock.patch.object(restore, "IS_WINDOWS", True), \
                mock.patch.object(restore, "boot_time", return_value=None), \
                mock.patch.object(restore, "_alive_windows", return_value=False) as alive:
            self.assertFalse(restore.is_alive({"pid": 7, "startedAt": 123}))
        alive.assert_called_once_with(7, 123)


if __name__ == "__main__":
    unittest.main()
