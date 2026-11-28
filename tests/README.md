# Tests

Run from the repository root with Python 3.8 or newer; no dependencies are required:

```sh
python -m unittest discover -s tests -v
python tests/smoke.py
```

Fixtures create synthetic transcript JSONL and registry JSON in a temporary config
directory. Unit tests load the extensionless program with `SourceFileLoader`, patch
its config paths, boot time and liveness, and disable temporary-folder filtering
only where synthetic working folders need it. No real Claude configuration is read.

The smoke test starts the CLI with `CLAUDE_CONFIG_DIR` pointing to the fixture,
checks `list --json`, and checks `-y --dry-run` using a fake Claude binary. Its
working folder is a unique temporary directory under the real user's home, so
normal temporary-folder filtering remains enabled even for checkouts under
`/tmp`. That folder and the separate temporary config are cleaned up on exit.
No terminal windows, browsers, or Claude processes are launched.

CI runs these commands on Linux, macOS and Windows with Python 3.8 and 3.13.
