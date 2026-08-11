"""PowerDeck plugin entry point.

Decky 3.x with api_version=1 does `main.Plugin = module.Plugin()` and
calls async methods on that instance. So the Plugin class with all
callables + the `_main` / `_unload` lifecycle hooks has to be
reachable from this module's `Plugin` symbol.

The actual logic lives in `powerdeck.plugin.Plugin`. We re-export it
so the two import paths (dev repo + installed plugin) behave
identically.
"""

import sys
import os

# Ensure the plugin root is on sys.path so `import powerdeck` works in
# both the repo layout and the installed layout (Decky flattens all
# files to the plugin root).
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import decky_plugin  # noqa: E402 - must come after sys.path setup

from powerdeck.plugin import Plugin  # noqa: E402 - Decky looks this up by name
