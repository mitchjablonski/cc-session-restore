# cc-session-restore

Reopen all your [Claude Code](https://claude.com/claude-code) sessions after a restart, in one click.

If you keep several Claude Code sessions open, a reboot means opening a terminal for each one, `cd`-ing into each project and running `claude --resume`, over and over. This tool lists your recent sessions, pre-checks the ones that were open when the machine went down, and reopens them all in new terminal tabs (or windows, for terminals without tabs).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshot-dark.png">
  <img alt="The cc-session-restore picker" src="docs/screenshot-light.png" width="720">
</picture>

> **Unofficial.** This is a community tool, not made by or affiliated with Anthropic.

Works on **macOS**, **Linux**, **Windows**, and **WSL** (Claude Code in WSL, opened in Windows Terminal). It's a single Python 3.8+ file with no dependencies.

## Install

With [pipx](https://pipx.pypa.io) or [uv](https://docs.astral.sh/uv/), straight from GitHub (macOS, Linux, WSL):

```bash
pipx install git+https://github.com/mitchjablonski/cc-session-restore
# or
uv tool install git+https://github.com/mitchjablonski/cc-session-restore

cc-session-restore --install
```

This puts `cc-session-restore` on your PATH. Update with `pipx upgrade cc-session-restore` or `uv tool upgrade cc-session-restore`.

**Native Windows:** pipx and uv installs don't run there. The command they add has no `.exe` wrapper, so Windows can't start it. Use the clone below instead.

Or clone it and run the file directly. This works everywhere, including native Windows:

```bash
git clone https://github.com/mitchjablonski/cc-session-restore
cd cc-session-restore
./cc-session-restore --install      # Windows: python cc-session-restore --install
```

Run it with the same Python, on the same side (Windows or WSL), as your Claude Code install. `--install` adds a **Claude Code sessions** launcher. The launcher runs the script with the exact Python that ran `--install` (for pipx or uv, the tool's own environment), so it keeps working until you uninstall or move the tool or that Python. If you do, run `--install` again. It refuses to run from a one-off `uvx` or `pipx run`, whose environments get cleaned up. Where the launcher goes:

| Where Claude Code runs | Launcher |
|---|---|
| WSL | Windows Start menu shortcut |
| Windows | Start menu shortcut |
| Linux | App menu entry (`~/.local/share/applications`) |
| macOS | `~/Applications/Claude Code sessions.command` (drag it to the Dock) |

To have the picker open automatically when you log in, copy that launcher into your startup items. On Windows, that's the `shell:startup` folder.

If you cloned it, it's also handy on your PATH: `ln -s "$PWD/cc-session-restore" ~/.local/bin/`

## Use

Open **Claude Code sessions**, or run `cc-session-restore --gui`. A page opens in your browser:

- **Checked** sessions were open when the machine went down. Click **Open** (or press Enter) to reopen them.
- **Greyed-out** sessions are already running, so they can't be opened twice.
- Click a row (or press Space on it) to toggle it. **Double-click** a row to open just that one session.
- If a session fails to open, the page says which one and why.

The page is served on `127.0.0.1` only. Its link works once and is swapped for a private cookie. That first load also gives the page a second per-run secret, kept only in that browser tab, which every request must carry. Browsers share cookies across local ports, so a server on another port could receive the cookie, but without the secret it can't list or open sessions. The page can't be shown in a frame on another site. It shuts down after you open sessions, or after 15 minutes idle.

### In the terminal

```bash
cc-session-restore              # interactive picker
cc-session-restore list         # just print the list
cc-session-restore doctor       # show diagnostics for a bug report
cc-session-restore -y           # reopen all pre-checked sessions, no questions
cc-session-restore -n 30        # show more sessions
cc-session-restore --dry-run    # print the commands instead of running them
```

### Terminals

Sessions open in the first match:

| Platform | Terminal |
|---|---|
| WSL | Windows Terminal tab running `wsl.exe` |
| Windows | Windows Terminal tab, else a new console window |
| Inside tmux | new tmux window |
| macOS | iTerm2 (tabs) if you use it or have it installed, else Terminal.app (a window per session) |
| Linux | the terminal you're in (WezTerm, kitty, Konsole, GNOME Terminal), else the first installed of gnome-terminal, konsole, xfce4-terminal, kitty, wezterm, alacritty, x-terminal-emulator, xterm |

On Linux, xfce4-terminal and WezTerm open each session in a new tab. GNOME Terminal does that only when you run cc-session-restore from inside GNOME Terminal, and Konsole only with "Run all Konsole windows in a single process" turned on. Otherwise, and in kitty, Alacritty and xterm, each session gets its own window.

To pick one yourself, use `--terminal NAME` or set `CC_SESSION_RESTORE_TERMINAL`. Run `--help` for the full list of names.

On native Windows, the launcher uses the built-in Windows PowerShell to pass arguments safely to `cmd /k`. The default `claude` command resolves through `PATH`, including npm's `.cmd` shim. An explicit `.ps1` path runs in PowerShell and respects your existing execution policy; use the `.cmd` shim if unsigned scripts are blocked. Extra flags use Windows quoting, for example `--model opus --name="two words"`. Literal double quotes, newlines and NUL characters inside arguments are rejected for `cmd` launchers. Spaces and `&`, `^`, `%`, `!`, `(` and `)` are supported.

Native Windows `--dry-run` prints a command to paste into **PowerShell**, including the original working folder for the console fallback. The encoded portion carries arguments literally; it does not download or run another script. See [Windows verification](docs/windows-testing.md) for automated coverage and remaining desktop checks.

### Settings

| Environment variable | What it does |
|---|---|
| `CC_SESSION_RESTORE_TERMINAL` | terminal to open sessions in |
| `CC_SESSION_RESTORE_CLAUDE_ARGS` | extra flags for every resumed session, e.g. `--model opus` |
| `CC_SESSION_RESTORE_CLAUDE_BIN` | command to run instead of `claude` |
| `CLAUDE_CONFIG_DIR` | Claude Code's config folder, if not `~/.claude` |

## How it works

It only reads files Claude Code already keeps on your machine. Nothing is sent anywhere, and nothing is modified.

- **Which sessions exist, and when you last used them:** each session's transcript, `~/.claude/projects/<project>/<session-id>.jsonl`. Its folder, title and file time tell the tool where the session ran and how recently.
- **Which ones were open when the machine went down:** while a session runs, Claude Code keeps `~/.claude/sessions/<pid>.json`, and removes it on a clean exit. A restart leaves the file behind. If that file's process started before the machine's last boot, the session was open when it went down.
- **Old leftovers aren't pre-checked:**
  - files from earlier crashes, more than a week older than the newest leftover or more than two weeks before the last boot;
  - files for sessions that were used again afterwards.
- **Reopening:** each session runs `claude --resume <session-id>` in its original folder, in a new terminal tab or window.

Only sessions you started yourself in a terminal are listed. SDK and background runs, and sessions whose folder no longer exists, are skipped.

## Caveats

- **This depends on Claude Code's internal files.** The session registry and transcript layout aren't a public API and may change in any release. If the list comes up empty or wrong, include the output of `cc-session-restore doctor` in your bug report. It reports the environment, registry field changes and why transcripts were skipped. The default output hides paths, session titles and IDs. Use `doctor --verbose` locally to see paths, titles and unknown field names, and review those details before sharing them.
- **Pre-checking is a best guess.** It relies on Claude Code cleaning up its own files. Uncheck anything you don't want.
- **Not every desktop path is tested yet.** WSL + Windows Terminal and tmux are tested, and the Linux terminal launchers are run on CI (headless, under Xvfb). Native Windows has hidden fake-command, process and shortcut integration checks; interactive Windows Terminal tabs and Start menu activation still need a desktop check. The macOS launchers are built from each terminal's documented command line but haven't been run on real machines yet. Reports and fixes are welcome.

## Contributing

Bug reports and fixes are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers the ground rules (one stdlib-only file, Python 3.8+) and how to test without opening real windows. Report bugs with the [bug report form](https://github.com/mitchjablonski/cc-session-restore/issues/new?template=bug_report.yml). For security problems, see [SECURITY.md](SECURITY.md).

## License

MIT
