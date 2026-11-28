# Contributing

Thanks for helping. Bug reports, fixes and reports from platforms we haven't tested are all welcome.

## Ground rules

- **One file, standard library only.** The whole tool is `cc-session-restore`. Don't add runtime dependencies, extra modules or a package layout. People run it straight from a clone.
- **Python 3.8 or newer.** Don't use anything newer than 3.8, such as `match`, `str.removeprefix`, `list[str]`-style annotations or the `|` union operator. Check your change with an old interpreter:

  ```bash
  uv run --python 3.8 python ./cc-session-restore --help
  uv run --python 3.8 python ./cc-session-restore list
  ```

- **No real session data.** Never commit real session names, ids, transcripts or paths, including in tests, screenshots and issue text. Use made-up data like the example below.
- **One pull request per issue**, against `main`.

## Testing without opening windows

The tool opens terminal windows and a browser for real. While you work on it, point it at fake data and a fake `claude`, and keep it away from your desktop.

### 1. A fake config folder

`CLAUDE_CONFIG_DIR` tells the tool where to find Claude Code's files. Make a small one:

```bash
T=$(mktemp -d)
P=~/ccsr-demo-project                  # the session's folder: must exist, and not be under /tmp
ID=11111111-2222-3333-4444-555555555555
mkdir -p "$T/claude/projects/demo" "$T/claude/sessions" "$P"

# A transcript: its first line with a cwd gives the folder; entrypoint must be "cli".
printf '{"type":"user","cwd":"%s","entrypoint":"cli"}\n{"type":"custom-title","customTitle":"demo session"}\n' \
  "$P" > "$T/claude/projects/demo/$ID.jsonl"

# A leftover registry file whose process started long before the last boot,
# so the session shows as "was open" and gets pre-checked.
printf '{"pid":999999,"sessionId":"%s","startedAt":1000000000000,"entrypoint":"cli","kind":"interactive"}\n' \
  "$ID" > "$T/claude/sessions/999999.json"

export CLAUDE_CONFIG_DIR="$T/claude"
```

Sessions whose folder is in a temp directory (`/tmp`, `/private/tmp`, `/var/folders` or the system temp folder) or doesn't exist are skipped, which is why `P` lives in your home folder. Delete it when you're done.

### 2. A fake `claude`

`CC_SESSION_RESTORE_CLAUDE_BIN` replaces the `claude` command. Use a script that just records how it was called, and give its full path, because sessions start in a login shell with its own `PATH`:

```bash
printf '#!/bin/sh\necho "claude $*" >> "%s/calls.log"\n' "$T" > "$T/fake-claude"
chmod +x "$T/fake-claude"
export CC_SESSION_RESTORE_CLAUDE_BIN="$T/fake-claude"
```

### 3. `--dry-run`

`--dry-run` prints the launch command for each session instead of running it. Use `--terminal` to see what any launcher would run, even one you don't have:

```bash
./cc-session-restore list
./cc-session-restore --json
./cc-session-restore -y --dry-run --terminal kitty
./cc-session-restore --dry-run --terminal iterm --open "$ID"
```

`--dry-run` has no effect on `--gui`.

### 4. The web page: `--gui --no-browser`

`--no-browser` prints the page's URL and doesn't open a browser. You can drive it with `curl`:

```bash
./cc-session-restore --gui --no-browser          # prints cc-session-restore: http://127.0.0.1:PORT/?t=TOKEN
curl -c jar "http://127.0.0.1:PORT/?t=TOKEN" >/dev/null    # swaps the token for a cookie
curl -b jar http://127.0.0.1:PORT/api/sessions
```

Clicking **Open** (or POSTing to `/api/open`) really launches sessions, so do it only with step 5 in place.

### 5. Real launches in a private tmux server

To run real launches without new windows, run them in a tmux server of their own. Inside tmux, the tool uses `tmux new-window`, which goes to the server named in `$TMUX`:

```bash
tmux -L ccsr-test new-session -d
export TMUX="$(tmux -L ccsr-test display -p '#{socket_path}'),0,0"

./cc-session-restore -y                          # or --gui --no-browser, then POST to /api/open
sleep 2; cat "$T/calls.log"                      # claude --resume 1111...
tmux -L ccsr-test kill-server
```

Each session starts in a login shell, which can take a moment, so give it a second or two before reading the log. The fake `claude` exits straight away, so its tmux window closes again.

## Reporting bugs

Use the [bug report form](https://github.com/mitchjablonski/cc-session-restore/issues/new?template=bug_report.yml). For security problems, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
