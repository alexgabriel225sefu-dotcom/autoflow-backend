"""Make the suite collectable by pytest without rewriting 61 test files.

The tests here are executable scripts: they assert at module level, print a
readable report and call sys.exit(). That design is deliberate — each file can
be run on its own (`python tests/test_ledger.py`) and reads as a description of
the failure it prevents, which is most of their value.

pytest imports test modules to collect them, so `sys.exit(0)` at import time
raised SystemExit during collection and pytest bailed out with INTERNALERROR
before running anything. The whole suite was uncollectable.

The fix is to change how pytest RUNS them, not what they assert. Each file is
collected as a single item and executed in a subprocess, exactly as CI and a
developer run it. Exit code 0 passes; anything else fails and the script's own
output becomes the failure report.

Rejected alternatives, and why:
  * wrapping each file's body in `if __name__ == "__main__"` — 61 files
    reindented, every assertion inside a function, and the diff would bury the
    real changes in this branch.
  * removing the sys.exit() calls — they are the exit status CI depends on.
  * making the assertions pytest-native — the same 61 files rewritten, with a
    real chance of weakening an assertion in translation. The spec forbids
    exactly that, and it is the right thing to forbid.

A subprocess per file is slower than in-process collection. For a suite that
runs in about a minute that is the cheaper trade.
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Each script declares itself a development environment; user_store now refuses
# to start in production without a shared backend and an encryption key.
CHILD_ENV = {
    "APP_ENV": "test",
    "ALLOW_PLAINTEXT_DEV_STORAGE": "true",
    "ALLOW_LOCAL_BACKEND_DEV": "true",
    "PAPER_TRADING": "true",
}


class ScriptFailure(Exception):
    """Carries the script's own output as the failure report."""


class ScriptItem(pytest.Item):
    def __init__(self, *, name, parent, script):
        super().__init__(name, parent)
        self.script = script

    def runtest(self):
        env = dict(os.environ)
        for k, v in CHILD_ENV.items():
            env.setdefault(k, v)
        r = subprocess.run([sys.executable, self.script],
                           capture_output=True, text=True, cwd=ROOT, env=env,
                           timeout=600)
        if r.returncode != 0:
            raise ScriptFailure(
                f"{os.path.basename(self.script)} exited {r.returncode}\n\n"
                f"{r.stdout[-6000:]}\n{r.stderr[-3000:]}")

    def repr_failure(self, excinfo, style=None):
        if isinstance(excinfo.value, ScriptFailure):
            return str(excinfo.value)
        return super().repr_failure(excinfo, style)

    def reportinfo(self):
        return self.script, 0, self.name


class ScriptFile(pytest.File):
    def collect(self):
        yield ScriptItem.from_parent(self, name=self.path.name,
                                     script=str(self.path))


def pytest_collect_file(parent, file_path):
    """Collect every test_*.py here as one script item.

    `run_all.py` is the project's own runner and would recurse if collected.
    """
    if file_path.suffix == ".py" and file_path.name.startswith("test_") \
            and file_path.parent.name == "tests":
        return ScriptFile.from_parent(parent, path=file_path)
    return None
