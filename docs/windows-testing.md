# Native Windows verification

Run the stdlib suite from the repository root:

```powershell
python -m unittest discover -s tests -p test_windows.py -v
```

The `Native Windows launchers` workflow runs it on `windows-latest` with Python 3.8 and 3.13. Tests never start Windows Terminal, open a console window or browser, activate a shortcut, or read real Claude sessions. They replace Claude with temporary fake `.cmd` and `.ps1` files. The exact generated console command runs with captured output and `CREATE_NO_WINDOW` in place of `CREATE_NEW_CONSOLE`. Test input closes `cmd /k` after the fake command exits.

Coverage includes:

- npm-style `.cmd` resolution through `PATH`, received argv and working folder;
- spaces, ampersands, carets, percent signs, exclamation marks, parentheses and apostrophes in fake paths/session data, empty arguments and trailing backslashes;
- Windows extra-argument splitting, including quotes inside `--flag="two words"`;
- running the printed PowerShell dry-run command from a different working folder;
- console fallback flags and inherited keyboard/screen handles (mocked, without opening a window);
- Windows Terminal argv and semicolon escaping (construction only);
- live, terminated and invalid PIDs, 64-bit process handles and boot time;
- a real `.lnk` created and read back through `WScript.Shell` entirely in a temporary directory, and mocked `--install` selection of `pythonw.exe` or `python.exe`.

The explicit `.ps1` integration check skips when the machine blocks unsigned scripts. It does not change execution policy. The default npm `.cmd` path remains covered independently. Literal double quotes or control separators inside `cmd` arguments are rejected before launching rather than passed through ambiguous shell syntax.

## Remaining human desktop checks

Use fake Claude commands and fake session data for these checks too:

1. Windows Terminal: verify that a new tab appears in the named window, the title and original folder are correct, a semicolon in a title/folder stays literal, and several selected sessions open in separate tabs.
2. Console fallback: verify that a visible new console accepts keyboard input, displays output and stays open after the fake command finishes.
3. Start menu: inspect the installed shortcut target, activate it and verify that the picker starts without a console flash. The automated test inspects a temporary shortcut but never creates or activates the real Start menu entry.
4. If using an explicitly configured `.ps1` shim, verify it under the machine's existing execution policy.

The bootstrap uses `-NoProfile`, `cmd /d` and `cmd /v:off`, so profiles, cmd AutoRun hooks and delayed expansion cannot reinterpret session data. It sets argument variables inside the new terminal process; it does not rely on an already-running Windows Terminal server inheriting the picker's environment.
