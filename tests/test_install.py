"""--install, --install --autostart, --uninstall and --gui --only-if-restorable (issue #6).

Every path lives in a temp dir: HOME, APPDATA, XDG_* and CLAUDE_CONFIG_DIR are
fakes. The Windows shortcut writer, the browser and the terminal launcher are
replaced, so nothing touches the real Start menu or Startup folder, and nothing
opens.
"""
import base64
import configparser
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "cc-session-restore"
FAKE_SID = "11111111-2222-3333-4444-555555555555"


class InstallTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ccsr-install-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / "home"
        self.appdata = self.root / "appdata"
        self.config = self.root / "claude-config"
        for d in (self.home, self.appdata, self.config):
            d.mkdir()
        env = {k: v for k, v in os.environ.items()
               if k not in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "WSL_DISTRO_NAME")}
        env.update({"HOME": str(self.home), "USERPROFILE": str(self.home),
                    "APPDATA": str(self.appdata), "CLAUDE_CONFIG_DIR": str(self.config),
                    "CC_SESSION_RESTORE_CLAUDE_BIN": "fake-claude-never-execute"})
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        loader = importlib.machinery.SourceFileLoader("ccsr_install_under_test", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.m = importlib.util.module_from_spec(spec)
        loader.exec_module(self.m)
        self.m.TEMP_DIRS = set()  # fixtures live in the OS temp folder
        self.shortcuts = []
        self.gui_runs = []
        for name, fake in (
                ("windows_shortcut", lambda *a: self.shortcuts.append(a)),
                ("open_in_browser", self.fail_call("open a browser")),
                ("launch", self.fail_call("launch sessions")),
                ("run_gui", lambda *a, **kw: self.gui_runs.append((a, kw)))):
            p = mock.patch.object(self.m, name, fake)
            p.start()
            self.addCleanup(p.stop)

    def fail_call(self, what):
        def fail(*a, **kw):
            raise AssertionError(f"tests must never {what}")
        return fail

    def platform(self, wsl=False, windows=False, mac=False):
        for name, value in (("IS_WSL", wsl), ("IS_WINDOWS", windows), ("IS_MAC", mac)):
            p = mock.patch.object(self.m, name, value)
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            result = self.m.main(list(argv))
        return result, out.getvalue()


class WindowsInstallTests(InstallTestCase):
    def programs(self):
        return self.appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    def test_wsl_install_autostart_uses_same_launcher_with_flag(self):
        self.platform(wsl=True)
        os.environ["WSL_DISTRO_NAME"] = "FakeDistro"
        self.run_main("--install", "--autostart")
        self.assertEqual(len(self.shortcuts), 2)
        (menu_lnk, *menu), (start_lnk, *start) = self.shortcuts
        self.assertEqual(menu_lnk, self.programs() / "Claude Code sessions.lnk")
        self.assertEqual(start_lnk, self.programs() / "Startup" / "Claude Code sessions.lnk")
        for powershell, target, args, workdir in (menu, start):
            self.assertEqual((powershell, target, workdir), ("powershell.exe", "powershell.exe", "C:\\"))
            self.assertTrue(args.startswith("-NoProfile -WindowStyle Hidden -EncodedCommand "))

        def decoded(args):
            return base64.b64decode(args.split()[-1]).decode("utf-16-le")
        menu_cmd, start_cmd = decoded(menu[2]), decoded(start[2])
        self.assertTrue(menu_cmd.startswith("Start-Process wsl.exe -WindowStyle Hidden -ArgumentList '-d FakeDistro "))
        self.assertTrue(menu_cmd.endswith(f'"./{SCRIPT.name}" --gui\''))
        self.assertEqual(start_cmd, menu_cmd[:-1] + " --only-if-restorable'")

    def test_wsl_install_without_autostart_adds_only_start_menu(self):
        self.platform(wsl=True)
        os.environ["WSL_DISTRO_NAME"] = "FakeDistro"
        self.run_main("--install")
        self.assertEqual([s[0] for s in self.shortcuts], [self.programs() / "Claude Code sessions.lnk"])

    def test_wsl_install_refuses_double_quote_path(self):
        self.platform(wsl=True)
        os.environ["WSL_DISTRO_NAME"] = "FakeDistro"
        with mock.patch.object(self.m.sys, "executable", '/opt/py"thon/bin/python3'), \
                self.assertRaises(SystemExit):
            self.run_main("--install", "--autostart")
        self.assertEqual(self.shortcuts, [])

    def test_windows_install_autostart(self):
        self.platform(windows=True)
        pydir = self.root / "Python"
        pydir.mkdir()
        (pydir / "pythonw.exe").touch()
        with mock.patch.object(self.m.sys, "executable", str(pydir / "python.exe")):
            self.run_main("--install", "--autostart")
        self.assertEqual(self.shortcuts, [
            (self.programs() / "Claude Code sessions.lnk", "powershell", pydir / "pythonw.exe",
             f'"{SCRIPT}" --gui', SCRIPT.parent),
            (self.programs() / "Startup" / "Claude Code sessions.lnk", "powershell",
             pydir / "pythonw.exe", f'"{SCRIPT}" --gui --only-if-restorable', SCRIPT.parent),
        ])

    def test_uninstall_removes_both_shortcuts(self):
        self.platform(windows=True)
        menu = self.programs() / "Claude Code sessions.lnk"
        startup = self.programs() / "Startup" / "Claude Code sessions.lnk"
        other = self.programs() / "Startup" / "Something else.lnk"
        startup.parent.mkdir(parents=True)
        for f in (menu, startup, other):
            f.touch()
        _, out = self.run_main("--uninstall")
        self.assertFalse(menu.exists())
        self.assertFalse(startup.exists())
        self.assertTrue(other.exists())
        self.assertEqual(out.count("Removed "), 2)
        self.assertEqual(self.shortcuts, [])

    def test_uninstall_with_nothing_installed(self):
        self.platform(wsl=True)
        _, out = self.run_main("--uninstall")
        self.assertIn("Nothing to remove", out)

    def test_wsl_appdata_from_wslenv_is_used_as_is(self):
        self.platform(wsl=True)
        with mock.patch.object(self.m.subprocess, "run", self.fail_call("run a subprocess")):
            self.assertEqual(self.m.windows_programs_dir(), self.programs())


class MacInstallTests(InstallTestCase):
    def test_install_autostart_writes_launch_agent(self):
        self.platform(mac=True)
        self.run_main("--install", "--autostart")
        command = self.home / "Applications" / "Claude Code sessions.command"
        self.assertTrue(os.access(command, os.X_OK))
        self.assertTrue(command.read_text().rstrip().endswith(" --gui"))
        agent = self.home / "Library" / "LaunchAgents" / "com.github.mitchjablonski.cc-session-restore.plist"
        with open(agent, "rb") as f:
            plist = plistlib.load(f)
        self.assertEqual(plist, {
            "Label": "com.github.mitchjablonski.cc-session-restore",
            "RunAtLoad": True,
            "ProgramArguments": [sys.executable, str(SCRIPT), "--gui", "--only-if-restorable"],
        })

    def test_install_without_autostart_and_uninstall(self):
        self.platform(mac=True)
        self.run_main("--install")
        command = self.home / "Applications" / "Claude Code sessions.command"
        self.assertTrue(command.exists())
        self.assertFalse((self.home / "Library").exists())
        self.run_main("--install", "--autostart")
        _, out = self.run_main("--uninstall")
        self.assertFalse(command.exists())
        self.assertEqual(list((self.home / "Library" / "LaunchAgents").iterdir()), [])
        self.assertEqual(out.count("Removed "), 2)


class LinuxInstallTests(InstallTestCase):
    def read_desktop(self, path):
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read(path, encoding="utf-8")
        return parser["Desktop Entry"]

    def test_install_autostart_writes_desktop_files(self):
        self.platform()
        self.run_main("--install", "--autostart")
        quoted = f'"{sys.executable}" "{SCRIPT}"'
        menu = self.read_desktop(self.home / ".local/share/applications/cc-session-restore.desktop")
        self.assertEqual(menu["Exec"], quoted + " --gui")
        self.assertEqual(menu["Categories"], "Development;")
        auto = self.read_desktop(self.home / ".config/autostart/cc-session-restore.desktop")
        self.assertEqual(auto["Type"], "Application")
        self.assertEqual(auto["Name"], "Claude Code sessions")
        self.assertEqual(auto["Exec"], quoted + " --gui --only-if-restorable")
        self.assertEqual(auto["Terminal"], "false")
        self.assertEqual(auto["X-GNOME-Autostart-enabled"], "true")

    def test_xdg_dirs_and_uninstall(self):
        self.platform()
        os.environ["XDG_CONFIG_HOME"] = str(self.root / "cfg")
        os.environ["XDG_DATA_HOME"] = str(self.root / "data")
        self.run_main("--install", "--autostart")
        menu = self.root / "data/applications/cc-session-restore.desktop"
        auto = self.root / "cfg/autostart/cc-session-restore.desktop"
        self.assertTrue(menu.exists() and auto.exists())
        self.run_main("--uninstall")
        self.assertFalse(menu.exists() or auto.exists())

    def test_install_without_autostart(self):
        self.platform()
        self.run_main("--install")
        self.assertFalse((self.home / ".config/autostart").exists())

    def test_autostart_needs_install(self):
        self.platform()
        with self.assertRaises(SystemExit):
            self.run_main("--autostart")
        self.assertFalse((self.home / ".config").exists())


class OnlyIfRestorableTests(InstallTestCase):
    def session(self, was_open):
        project = self.root / "project"
        project.mkdir()
        folder = self.config / "projects" / "fake-project"
        folder.mkdir(parents=True)
        (folder / (FAKE_SID + ".jsonl")).write_text(json.dumps(
            {"type": "user", "cwd": str(project), "entrypoint": "cli", "sessionId": FAKE_SID}) + "\n")
        if was_open:  # a leftover registry file for a process that no longer exists
            (self.config / "sessions").mkdir()
            now_ms = int(time.time() * 1000)
            (self.config / "sessions" / "999999.json").write_text(json.dumps(
                {"pid": 999999, "sessionId": FAKE_SID, "cwd": str(project), "startedAt": now_ms,
                 "updatedAt": now_ms, "kind": "interactive", "entrypoint": "cli"}))

    def gui(self):
        with mock.patch.object(self.m, "is_alive", lambda d: False):
            return self.run_main("--gui", "--only-if-restorable", "--no-browser")

    def test_no_sessions_exits_silently(self):
        result, out = self.gui()
        self.assertEqual((result, out, self.gui_runs, self.m.FAILED), (False, "", [], []))

    def test_nothing_prechecked_exits_silently(self):
        self.session(was_open=False)
        result, out = self.gui()
        self.assertEqual((result, out, self.gui_runs, self.m.FAILED), (False, "", [], []))

    def test_prechecked_session_opens_picker(self):
        self.session(was_open=True)
        self.gui()
        self.assertEqual(len(self.gui_runs), 1)
        self.assertEqual(self.gui_runs[0][1]["browser"], False)

    def test_plain_gui_still_opens_without_prechecked(self):
        self.session(was_open=False)
        self.run_main("--gui", "--no-browser")
        self.assertEqual(len(self.gui_runs), 1)

    def test_exit_code_is_zero(self):
        # Real process, empty config: exits before serving. --no-browser in case it didn't.
        proc = subprocess.run([sys.executable, str(SCRIPT), "--gui", "--only-if-restorable",
                               "--no-browser"], capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
