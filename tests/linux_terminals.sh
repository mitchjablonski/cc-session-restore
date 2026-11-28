#!/usr/bin/env bash
# Opens two sessions in a real terminal and checks that a fake `claude` ran in each
# with the right folder and arguments. CI only: it opens real windows, so run it
# under xvfb-run (see .github/workflows/linux-terminals.yml), never on your desktop.
#
#   tests/linux_terminals.sh TERMINAL
#
# Optional environment:
#   CHECK_TITLE=1     check that the window is titled after the newest session
#   WM_CLASS=regex    count the terminal's windows by X class after both sessions...
#   WINDOWS=n         ...and expect n of them (1 = the second session went into a tab)
set -euo pipefail
term=$1
repo=$(cd "$(dirname "$0")/.." && pwd)

# Not under /tmp: cc-session-restore skips sessions in temp folders.
work=$(mktemp -d "$HOME/csr-test.XXXXXX")
out="$work/out"
bin="$work/bin \$HOME \`x\`"
proj="$work/proj dir/it's \"q\" \$HOME \`b\` back\\slash"
mkdir -p "$out" "$bin" "$work/config/projects/p" "$proj"

# Fake claude: record the folder and arguments, then stay open for a while so the
# window can be inspected and the next session finds the terminal still running.
cat > "$bin/claude" <<EOF
#!/bin/sh
{ pwd -P; for a in "\$@"; do printf '%s\n' "\$a"; done; } > "$out/\$2.tmp"
mv "$out/\$2.tmp" "$out/\$2.txt"
sleep 20
EOF
chmod +x "$bin/claude"

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
export CC_SESSION_RESTORE_CLAUDE_BIN="$bin/claude"
export CC_SESSION_RESTORE_CLAUDE_ARGS="--model \"a b\" '\$HOME'"
unset TMUX WEZTERM_PANE KITTY_WINDOW_ID KONSOLE_VERSION GNOME_TERMINAL_SCREEN GNOME_TERMINAL_SERVICE

fail() {
    echo "FAIL: $term: $*"
    exit 1
}

wait_for() {
    for _ in $(seq 120); do
        [ -e "$1" ] && return 0
        sleep 0.5
    done
    fail "never ran claude ($1 missing)"
}

check() {  # session id, expected window title
    local sid=$1 title=$2 got want
    wait_for "$out/$sid.txt"
    got=$(cat "$out/$sid.txt")
    want=$(printf '%s\n' "$(cd "$proj" && pwd -P)" --resume "$sid" --model "a b" '$HOME')
    if [ "$got" != "$want" ]; then
        printf -- '--- want\n%s\n--- got\n%s\n' "$want" "$got"
        fail "$sid got the wrong folder or arguments"
    fi
    echo "ok: $term $sid ran in the right folder with the right arguments"
    if [ -n "${CHECK_TITLE:-}" ]; then
        # The window shows the title of its active tab, which is the newest one.
        # [-] keeps a leading dash in the pattern without xdotool taking it for an option.
        sleep 1
        if ! xdotool search --name "$(printf '%s' "$title" | sed 's/^-/[-]/')" >/dev/null; then
            echo "Windows:"
            xdotool search --name . getwindowname %@ || true
            fail "no window titled '$title'"
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

if [ -n "${WM_CLASS:-}" ]; then
    sleep 1
    n=$(xdotool search --onlyvisible --class "$WM_CLASS" | wc -l)
    xdotool search --onlyvisible --class "$WM_CLASS" getwindowname %@ || true
    [ "$n" = "$WINDOWS" ] || fail "$n visible windows of class $WM_CLASS, expected $WINDOWS"
    echo "ok: $term has $n window(s) for two sessions"
fi
if [ "$term" = wezterm ]; then
    wezterm cli list
    panes=$(wezterm cli list --format json)
    python3 -c '
import json, sys
panes = json.loads(sys.argv[1])
windows, tabs = {p["window_id"] for p in panes}, {p["tab_id"] for p in panes}
assert len(panes) == 2 and len(windows) == 1 and len(tabs) == 2, panes
' "$panes" || fail "expected two tabs in one window"
    echo "ok: wezterm has both sessions as tabs of one window"
fi
