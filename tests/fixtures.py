"""Synthetic Claude files; no user configuration is read by these helpers."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load_app():
    loader = importlib.machinery.SourceFileLoader("cc_session_restore_test", str(ROOT / "cc-session-restore"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Fixture:
    def __init__(self, cwd=None):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "config"
        self.projects = self.config / "projects" / "encoded-project"
        self.registry = self.config / "sessions"
        self.projects.mkdir(parents=True)
        self.registry.mkdir()
        self.cwd = Path(cwd) if cwd else self.root / "work-project"
        self.cwd.mkdir(exist_ok=True)

    def transcript(self, sid, when, lines=None, cwd=None, entrypoint="cli"):
        path = self.projects / (sid + ".jsonl")
        rows = [{"cwd": str(cwd or self.cwd), "entrypoint": entrypoint}] + (lines or [])
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        os.utime(str(path), (when, when))
        return path

    def session(self, sid, when, **extra):
        data = {"sessionId": sid, "pid": 2147483647, "startedAt": 1000,
                "updatedAt": when * 1000, "entrypoint": "cli", "kind": "interactive"}
        data.update(extra)
        path = self.registry / (str(len(list(self.registry.iterdir()))) + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        os.utime(str(path), (when, when))
        return path

    def close(self):
        self.temp.cleanup()
