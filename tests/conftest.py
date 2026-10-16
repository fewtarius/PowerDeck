"""Test bootstrap for PowerDeck backend regression tests.

The real `decky_plugin` module only exists inside the Decky runtime
(it is injected by plugin_loader with environment variables pointing at
the user's home). To exercise the real `powerdeck` backend in a
plain `python3 -m unittest` invocation we inject a minimal fake that
provides the attributes the backend actually imports:

  * DECKY_PLUGIN_SETTINGS_DIR -> redirected to a per-test tmp dir so
    profile JSON is never written to the developer's real config.
  * logger -> no-op stand-ins so tests stay quiet unless they opt in.
  * migration helpers (migrate_*) -> no-ops.
  * Plugin -> a bare attribute marker (not used in tests but referenced
    by some type stubs).

`sys.path` is then extended so `import powerdeck` resolves to the repo
checkout rather than any installed copy.
"""
from __future__ import annotations

import os
import sys
import types
import tempfile

# Point the plugin at a throwaway settings dir *before* the backend
# imports anything that reads DECKY_PLUGIN_SETTINGS_DIR.
_TEST_SETTINGS = tempfile.mkdtemp(prefix="powerdeck-test-")
os.environ["DECKY_PLUGIN_SETTINGS_DIR"] = _TEST_SETTINGS
os.environ.setdefault("DECKY_PLUGIN_RUNTIME_DIR", tempfile.mkdtemp(prefix="powerdeck-rt-"))

# Stub `decky_plugin` before importing the backend.
if "decky_plugin" not in sys.modules:
    _fake = types.ModuleType("decky_plugin")

    class _FakeLogger:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def debug(self, *a, **k): pass

    _fake.logger = _FakeLogger()
    _fake.DECKY_PLUGIN_SETTINGS_DIR = _TEST_SETTINGS
    _fake.HOME = os.path.expanduser("~")
    _fake.USER = os.environ.get("USER", "deck")
    _fake.DECKY_VERSION = "test"
    # Migration helpers - the backend imports them at module load.
    _fake.migrate_any = lambda *a, **k: {}
    _fake.migrate_settings = lambda *a, **k: {}
    _fake.migrate_runtime = lambda *a, **k: {}
    _fake.migrate_logs = lambda *a, **k: {}
    # Decky plugins expose `Plugin` via the module for the type stubs.
    _fake.Plugin = object
    sys.modules["decky_plugin"] = _fake

# Make the repo importable as `powerdeck` and `main`.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_REPO,):
    if p not in sys.path:
        sys.path.insert(0, p)
