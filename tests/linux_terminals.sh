#!/usr/bin/env bash
# Opens two sessions in a real terminal and checks that a fake `claude` ran in each
# with the right folder and arguments. CI only: it opens real windows, so run it
# under xvfb-run (see .github/workflows/linux-terminals.yml), never on your desktop.
#
#   tests/linux_terminals.sh TERMINAL [check-title]
set -euo pipefail
term=$1
check_title=${2:-}
repo=$(cd "$(dirname "$0")/.." && pwd)

# Not under /tmp: cc-session-restore skips sessions in temp folders.
work=$(mktemp -d "$HOME/csr-test.XXXXXX")
out="$work/out"
mkdir -p "$out" "$work/bin" "$work/config/projects/p"
proj="$work/proj dir/it's \"q\" \$HOME"
mkdir -p "$proj"

# Fake claude: record the folder and arguments, then stay open for a while so the
# window can be inspected and the next session finds the terminal still running.
cat > "$work/bin/claude" <<EOF
#!/bin/sh
{ pwd -P; for a in "\$@"; do printf '%s\n' "\$a"; done; } > "$out/\$2.tmp"
mv "$out/\$2.tmp" "$out/\$2.txt"
sleep 20
EOF
chmod +x "$work/bin/claude"

python3 - "$work/config/projects/p" "$proj" <<'EOF'
import json, sys
folder, cwd = sys.argv[1:]
titles = {"s1": "-dash title one", "s2": "title two"}
for sid, title in titles.items():
    with open(f"{folder}/{sid}.jsonl", "w") as f:
        f.write(json.dumps({"cwd": cwd, "entrypoint": "cli", "type": "user"}) + "\n")
        f.write(json.dumps({"type": "custom-title", "customTitle": title}) + "\n")
EOF

export CLAUDE_CONFIG_DIR="$work/config"
export CC_SESSION_RESTORE_CLAUDE_BIN="$work/bin/claude"
export CC_SESSION_RESTORE_CLAUDE_ARGS='--model "a b"'
unset TMUX WEZTERM_PANE KITTY_WINDOW_ID KONSOLE_VERSION GNOME_TERMINAL_SCREEN GNOME_TERMINAL_SERVICE

wait_for() {
    for _ in $(seq 120); do
        [ -e "$1" ] && return 0
        sleep 0.5
    done
    echo "FAIL: $term never ran claude ($1 missing)"
    exit 1
}

check() {  # session id, expected window title
    local sid=$1 title=$2 got want
    wait_for "$out/$sid.txt"
    got=$(cat "$out/$sid.txt")
    want=$(printf '%s\n%s\n%s\n%s\n%s' "$(cd "$proj" && pwd -P)" --resume "$sid" --model "a b")
    if [ "$got" != "$want" ]; then
        echo "FAIL: $term $sid"; echo "--- want"; echo "$want"; echo "--- got"; echo "$got"
        exit 1
    fi
    echo "ok: $term $sid ran in the right folder with the right arguments"
    if [ -n "$check_title" ]; then
        # The window shows the title of its active tab, which is the newest one.
        sleep 1
        if ! xdotool search --name "${title#-}" >/dev/null; then
            echo "FAIL: $term has no window titled '$title'. Windows:"
            xdotool search --name . getwindowname %@ || true
            exit 1
        fi
        echo "ok: $term window titled '$title'"
    fi
}

echo "+ $("$repo/cc-session-restore" --dry-run --terminal "$term" --open s1)"
"$repo/cc-session-restore" --terminal "$term" --open s1
check s1 "-dash title one"

# Second session while the first is still open: tab-capable terminals add a tab
# to the running instance (wezterm: `cli spawn`, as when run from inside wezterm).
if [ "$term" = wezterm ]; then
    export WEZTERM_PANE=0
fi
echo "+ $("$repo/cc-session-restore" --dry-run --terminal "$term" --open s2)"
"$repo/cc-session-restore" --terminal "$term" --open s2
check s2 "title two"
