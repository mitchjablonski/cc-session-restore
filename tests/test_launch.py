"""Launch command construction only: never open a terminal or run Claude."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shlex
import unittest
from unittest import mock


def load_script():
    loader = importlib.machinery.SourceFileLoader(
        "restore_launch_tests", str(Path(__file__).resolve().parents[1] / "cc-session-restore"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


restore = load_script()


class LaunchCommandTests(unittest.TestCase):
    def setUp(self):
        self.session = {
            "cwd": '/fake dir/quo\'te "double"; & % ^ 雪',
            "title": 'Title "quoted"; & % ^ 雪',
            "id": "01234567-abcd_ABC9",
        }
        self.binary = '/fake bin/claude\'s "tool"; & % ^ 雪'
        self.shell = ["/fake shell/bash", "-l", "-i", "-c"]
        patches = [
            mock.patch.object(restore, "CLAUDE_BIN", self.binary),
            mock.patch.object(restore, "CLAUDE_ARGS", '--model "fake model"'),
            mock.patch.object(restore, "IS_WINDOWS", False),
            mock.patch.object(restore, "login_shell", return_value=self.shell),
            mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Fake Distro 雪"}, clear=True),
            mock.patch.object(restore.subprocess, "Popen", side_effect=AssertionError("process launched")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def assert_inner(self, inner):
        self.assertEqual(shlex.split(inner),
                         [self.binary, "--resume", self.session["id"], "--model", "fake model"])

    def test_resume_ids_are_one_shell_argument(self):
        for session_id in ("a", "01234567-abcd_ABC9", "A" * 128,
                           "hostile id ' \"; & % ^ 雪"):
            with self.subTest(session_id=session_id):
                session = dict(self.session, id=session_id)
                argv, _ = restore.launch_cmd(session, "xterm")
                self.assertEqual(shlex.split(argv[-1]),
                                 [self.binary, "--resume", session_id, "--model", "fake model"])

    def test_linux_terminals_preserve_arguments(self):
        s = self.session
        prefixes = {
            "gnome-terminal": ["gnome-terminal", "--tab", "--title", s["title"], "--working-directory", s["cwd"], "--"],
            "konsole": ["konsole", "--new-tab", "--workdir", s["cwd"], "-e"],
            "xfce4-terminal": ["xfce4-terminal", "--tab", "--title", s["title"], "--working-directory", s["cwd"], "-x"],
            "kitty": ["kitty", "--directory", s["cwd"], "--title", s["title"]],
            "wezterm": ["wezterm", "start", "--cwd", s["cwd"], "--"],
            "alacritty": ["alacritty", "--working-directory", s["cwd"], "--title", s["title"], "-e"],
            "x-terminal-emulator": ["x-terminal-emulator", "-e"],
            "xterm": ["xterm", "-T", s["title"], "-e"],
        }
        for terminal, prefix in prefixes.items():
            with self.subTest(terminal=terminal):
                argv, kwargs = restore.launch_cmd(s, terminal)
                self.assertEqual(argv[:-1], prefix + self.shell)
                self.assert_inner(argv[-1])
                self.assertEqual(kwargs, {"cwd": s["cwd"]})

    def test_wezterm_existing_pane(self):
        with mock.patch.dict(os.environ, {"WEZTERM_PANE": "fake-pane"}):
            argv, _ = restore.launch_cmd(self.session, "wezterm")
        self.assertEqual(argv[:3], ["wezterm", "cli", "spawn"])
        self.assertEqual(argv[3:6], ["--cwd", self.session["cwd"], "--"])
        self.assert_inner(argv[-1])

    def test_tmux_shell_command_round_trip(self):
        argv, kwargs = restore.launch_cmd(self.session, "tmux")
        self.assertEqual(argv[:-1], ["tmux", "new-window", "-n", self.session["title"], "-c", self.session["cwd"]])
        shell = shlex.split(argv[-1])
        self.assertEqual(shell[:-1], self.shell)
        self.assert_inner(shell[-1])
        self.assertEqual(kwargs, {})

    def test_applescript_escapes_embedded_shell_command(self):
        for terminal in ("iterm", "macos-terminal"):
            with self.subTest(terminal=terminal):
                argv, kwargs = restore.launch_cmd(self.session, terminal)
                self.assertEqual(argv[:2], ["osascript", "-e"])
                # Decode just the AppleScript literal, independently of its encoder.
                marker = "write text " if terminal == "iterm" else "do script "
                literal = argv[2].split(marker, 1)[1].splitlines()[0]
                self.assertTrue(literal.startswith('"') and literal.endswith('"'))
                encoded = literal[1:-1]
                decoded = ""
                i = 0
                while i < len(encoded):
                    if encoded[i] == "\\":
                        i += 1
                        self.assertIn(encoded[i], ('"', "\\"))
                    decoded += encoded[i]
                    i += 1
                parts = shlex.split(decoded)
                self.assertEqual(parts[:3], ["cd", self.session["cwd"], "&&"])
                self.assertEqual(parts[3:], [self.binary, "--resume", self.session["id"], "--model", "fake model"])
                self.assertEqual(kwargs, {})

    def test_wsl_preserves_shell_after_terminal_separator_escape(self):
        argv, kwargs = restore.launch_cmd(self.session, "wsl")
        decoded = [arg.replace("\\;", ";") for arg in argv]
        self.assertEqual(decoded[:-1], ["wt.exe", "-w", restore.WINDOW_NAME, "new-tab", "--title", self.session["title"], "wsl.exe", "-d", "Fake Distro 雪", "--cd", self.session["cwd"], "-e"] + self.shell)
        self.assert_inner(decoded[-1])
        self.assertTrue(all(";" not in arg.replace("\\;", "") for arg in argv))
        self.assertEqual(kwargs, {})

    def test_native_windows_terminal_and_console_routes(self):
        # Safe inputs here: cmd.exe escaping of untrusted executable paths is
        # tracked separately by the native Windows launch issue.
        with mock.patch.object(restore, "CLAUDE_BIN", "fake-claude"), mock.patch.object(restore, "CLAUDE_ARGS", "--verbose"), mock.patch.object(restore, "IS_WINDOWS", True):
            command = ["cmd", "/k", "fake-claude", "--resume", self.session["id"], "--verbose"]
            argv, kwargs = restore.launch_cmd(self.session, "windows-console")
            self.assertEqual(argv, command)
            self.assertEqual(kwargs, {"cwd": self.session["cwd"], "creationflags": 0x10, "console": True})
            argv, kwargs = restore.launch_cmd(self.session, "windows-terminal")
            self.assertEqual(argv, ["wt.exe", "-w", restore.WINDOW_NAME, "new-tab", "--title", self.session["title"].replace(";", "\\;"), "-d", self.session["cwd"].replace(";", "\\;")] + command)
            self.assertEqual(kwargs, {})

    def test_dry_run_never_spawns_or_checks_installed_terminal(self):
        messages = []
        with mock.patch.object(restore.shutil, "which", side_effect=AssertionError("which called")):
            errors = restore.launch([self.session], dry_run=True, terminal="tmux", log=messages.append)
        self.assertEqual(errors, [])
        self.assertEqual(len(messages), 1)
        self.assertEqual(shlex.split(messages[0]), restore.launch_cmd(self.session, "tmux")[0])

    def test_unknown_terminal_and_missing_wsl_distro_fail(self):
        with self.assertRaisesRegex(SystemExit, "unknown terminal"):
            restore.launch_cmd(self.session, "fake-terminal")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "only works inside WSL"):
                restore.launch_cmd(self.session, "wsl")


if __name__ == "__main__":
    unittest.main()
