# Contributing

Thanks for helping. Bug reports, fixes and reports from platforms we haven't tested yet are all welcome.

## Ground rules

- **One file, standard library only.** `cc-session-restore` is a single script with no dependencies, so people can clone it and run it. Please don't add third-party imports, a build step or extra files that the script needs at runtime.
- **Python 3.8 or newer.** Don't use features from later versions (`str.removeprefix`, `list[int]` annotations, `match`, parenthesised context managers, and so on). To check, run the script under 3.8, for example with [uv](https://docs.astral.sh/uv/): `uv run --python 3.8 python cc-session-restore list`.
- **Read-only.** The tool only reads Claude Code's files. It must never write to, move or delete anything under the Claude config folder.
- **Keep the docs in step.** If you change a flag, environment variable or behaviour, update both the `--help` text at the top of the script and `README.md`.

## Testing without opening windows

Running the tool for real opens a terminal tab for every session it resumes, and `--gui` opens your browser. While you work on it, use the options below so nothing pops up and none of your real sessions are touched.

### A fake config folder

The tool reads everything from `CLAUDE_CONFIG_DIR` (default `~/.claude`). Point it at a throwaway folder with made-up sessions:

```bash
export CLAUDE_CONFIG_DIR="$(mktemp -d)"
export CC_SESSION_RESTORE_CLAUDE_BIN=echo   # run `echo` instead of `claude`
id=11111111-2222-3333-4444-555555555555
mkdir -p ~/ccsr-demo "$CLAUDE_CONFIG_DIR/projects/demo" "$CLAUDE_CONFIG_DIR/sessions"

# A transcript: the session's folder, and that it was started from the CLI.
printf '%s\n' "{\"cwd\": \"$HOME/ccsr-demo\", \"entrypoint\": \"cli\"}" \
  '{"type": "custom-title", "customTitle": "demo session"}' \
  > "$CLAUDE_CONFIG_DIR/projects/demo/$id.jsonl"

# A leftover registry file from a process that started before the last boot,
# so the session shows as "was open when the machine went down".
printf '%s\n' "{\"pid\": 999999, \"sessionId\": \"$id\", \"startedAt\": 1000, \"entrypoint\": \"cli\", \"kind\": \"interactive\"}" \
  > "$CLAUDE_CONFIG_DIR/sessions/999999.json"

./cc-session-restore list   # [x]  1  demo session  just now  ~/ccsr-demo
```

Things to know:

- A session's folder (`cwd`) must exist and must **not** be inside a temp folder (`/tmp`, `/var/folders`, ...). Sessions in temp folders are skipped on purpose, so keep the fake session folder somewhere like `~/ccsr-demo`. The config folder itself can live in `/tmp`.
- `CLAUDE_CONFIG_DIR` and the other variables are read when the script starts, so export them before running it.
- Delete the fake folders when you're done.

### Print commands instead of running them

`--dry-run` prints the command that would open each session instead of running it:

```bash
./cc-session-restore -y --dry-run                        # all pre-checked sessions
./cc-session-restore --open "$id" --dry-run --terminal kitty
```

Use `--terminal NAME` to see the command for a terminal you don't have; any name from `--help` works.

`--dry-run` works with the text picker, `-y` and `--open`. **It does not apply to `--gui`**: the page's Open button always launches.

### The browser page

`--gui --no-browser` serves the page without opening a browser and prints its URL. The link works once, so open it in one browser tab, or with `curl`:

```bash
./cc-session-restore --gui --no-browser --port 8765
```

To try the Open button without new windows, run the tool inside a throwaway tmux server with a fake `claude`. Sessions then open as windows of that tmux server, run `echo`, and close:

```bash
tmux -L ccsr-test        # then, inside it, with the variables above set:
./cc-session-restore --gui --no-browser
```

### Before you open a pull request

- Try your change against the fake config folder above, on Python 3.8 and a current Python.
- If you changed a launcher, paste its `--dry-run` output into the pull request, and say whether you ran it on a real machine.
- Don't commit or paste real session ids, titles, folder paths or transcript contents. Use made-up ones like the example above.

## Reporting bugs and security issues

Open a [bug report](https://github.com/mitchjablonski/cc-session-restore/issues/new/choose). For security issues, follow [SECURITY.md](SECURITY.md) instead and don't open a public issue.
