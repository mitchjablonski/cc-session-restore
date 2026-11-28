"""Exercise the actual CLI with fake data and command printing only."""
import json
import os
import subprocess
import sys
import time

from fixtures import Fixture, ROOT


def main():
    # The repository is a real working folder, outside the OS temporary tree.
    fx = Fixture(cwd=ROOT)
    try:
        now = time.time()
        fx.transcript("smoke-session", now, [{"type": "custom-title", "customTitle": "Synthetic smoke"}])
        fx.session("smoke-session", now)
        env = os.environ.copy()
        env.update(CLAUDE_CONFIG_DIR=str(fx.config),
                   CC_SESSION_RESTORE_CLAUDE_BIN="fake-claude-never-executed",
                   CC_SESSION_RESTORE_CLAUDE_ARGS="")

        def run(*args):
            return subprocess.run([sys.executable, str(ROOT / "cc-session-restore")] + list(args),
                                  env=env, check=True, capture_output=True, text=True, timeout=20).stdout

        payload = json.loads(run("list", "--json"))
        sessions = payload["sessions"]
        assert len(sessions) == 1, payload
        assert sessions[0]["id"] == "smoke-session", payload
        assert sessions[0]["title"] == "Synthetic smoke", payload
        assert sessions[0]["checked"] and not sessions[0]["running"], payload
        output = run("-y", "--dry-run", "--terminal", "windows-console" if os.name == "nt" else "xterm")
        assert "fake-claude-never-executed" in output and "smoke-session" in output, output
        print("CLI JSON discovery and dry-run passed with synthetic data and fake Claude binary.")
    finally:
        fx.close()


if __name__ == "__main__":
    main()
