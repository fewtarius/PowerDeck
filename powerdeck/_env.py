"""Environment sanitising for helper processes.

Decky runs plugins inside a PyInstaller bundle.  The loader starts the
plugin's backend through a forkserver whose LD_LIBRARY_PATH points at
the extracted bundle directory (``/tmp/_MEIxxxx``), so every child
process the plugin spawns inherits it.  The bundle ships its own
``libtinfo.so.6``, which is built against a newer glibc than the
system provides, so a shell script spawned by the plugin fails to
start before it can run a single line:

    /bin/bash: /usr/lib/libc.so.6: version `GLIBC_2.42' not found
    (required by /tmp/_MEIxxxx/libtinfo.so.6)

That made ``jelos-set-setting`` fail silently from the plugin, so the
cooling profile was never written and the fan kept running the curve
of the previous profile.  Strip the variables that point into the
bundle so helper processes run against the system libraries.
"""

from __future__ import annotations

import os

# Variables that make a process load libraries from somewhere other
# than the system.
_LIBRARY_VARS = ("LD_LIBRARY_PATH", "LD_PRELOAD")

# Variables that make a process load Python code from somewhere other
# than the system.
_PYTHON_VARS = ("PYTHONHOME", "PYTHONPATH")


def _points_at_bundle(value: str) -> bool:
    """True when a path-like value references a PyInstaller bundle dir."""
    if not value:
        return False
    return "_MEI" in value


def clean_env() -> dict:
    """Return a copy of the environment that is safe for helper processes.

    The library loader variables are always removed: a child process
    that inherits a path to another distribution's libraries may fail
    to start at all.  The Python variables are only removed when they
    point into a PyInstaller bundle, since a user may legitimately
    have set them.
    """
    env = os.environ.copy()

    for var in _LIBRARY_VARS:
        env.pop(var, None)

    for var in _PYTHON_VARS:
        if _points_at_bundle(env.get(var, "")):
            env.pop(var, None)

    return env
