"""Regression tests for the helper-process environment.

Decky runs plugins inside a PyInstaller bundle whose forkserver exports
LD_LIBRARY_PATH pointing at the extracted bundle.  The bundle ships a
libtinfo built against a newer glibc, so any shell script the plugin
spawns fails to start:

    /bin/bash: /usr/lib/libc.so.6: version `GLIBC_2.42' not found
    (required by /tmp/_MEIxxxx/libtinfo.so.6)

That made jelos-set-setting fail silently from the plugin, so the
cooling profile was never written and the fan kept running the curve
of the previous profile.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import tests.conftest  # noqa: F401  - installs the fake decky_plugin

from powerdeck._env import clean_env
from powerdeck.hardware import fan


class CleanEnvTests(unittest.TestCase):
    def test_library_loader_variables_are_removed(self):
        with mock.patch.dict(os.environ, {
            "LD_LIBRARY_PATH": "/tmp/_MEIxxxx",
            "LD_PRELOAD": "/tmp/_MEIxxxx/libfoo.so",
        }):
            env = clean_env()
        self.assertNotIn("LD_LIBRARY_PATH", env)
        self.assertNotIn("LD_PRELOAD", env)

    def test_bundle_python_variables_are_removed(self):
        with mock.patch.dict(os.environ, {
            "PYTHONHOME": "/tmp/_MEIxxxx",
            "PYTHONPATH": "/tmp/_MEIxxxx/base_library.zip",
        }):
            env = clean_env()
        self.assertNotIn("PYTHONHOME", env)
        self.assertNotIn("PYTHONPATH", env)

    def test_unrelated_python_variables_are_kept(self):
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/home/deck/mylibs"}):
            env = clean_env()
        self.assertEqual(env.get("PYTHONPATH"), "/home/deck/mylibs")

    def test_other_variables_are_preserved(self):
        with mock.patch.dict(os.environ, {"HOME": "/root", "PATH": "/usr/bin"}):
            env = clean_env()
        self.assertEqual(env.get("HOME"), "/root")
        self.assertEqual(env.get("PATH"), "/usr/bin")


class FanHelperEnvironmentTests(unittest.TestCase):
    """The fan helpers must run with a sanitised environment."""

    def _captured_env(self, target):
        """Return the env the fan module passes to subprocess.run."""
        captured = {}

        def fake_run(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(fan.subprocess, "run", fake_run):
            with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEIxxxx"}):
                getattr(fan, target)()
        return captured

    def test_reload_uses_a_clean_environment(self):
        captured = self._captured_env("_reload_jelos_fancontrol")
        self.assertIsNotNone(captured.get("env"))
        self.assertNotIn("LD_LIBRARY_PATH", captured["env"])

    def test_set_jelos_profile_uses_a_clean_environment(self):
        captured = {}

        def fake_run(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(fan, "_has_jelos_fan", return_value=True):
            with mock.patch.object(fan.subprocess, "run", fake_run):
                with mock.patch.object(fan, "_reload_jelos_fancontrol"):
                    with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEIxxxx"}):
                        fan._set_jelos_profile("quiet")
        self.assertIsNotNone(captured.get("env"))
        self.assertNotIn("LD_LIBRARY_PATH", captured["env"])

    def test_failed_write_is_reported(self):
        """A helper that could not run must not be reported as success."""
        def fake_run(cmd, *args, **kwargs):
            return mock.Mock(returncode=1, stdout="",
                              stderr="version `GLIBC_2.42' not found")

        with mock.patch.object(fan, "_has_jelos_fan", return_value=True):
            with mock.patch.object(fan.subprocess, "run", fake_run):
                with mock.patch.object(fan, "_reload_jelos_fancontrol") as reload_mock:
                    result = fan._set_jelos_profile("quiet")
        self.assertFalse(result)
        # The daemon must not be told to reload a profile that was
        # never written.
        reload_mock.assert_not_called()

    def test_successful_write_reloads_the_daemon(self):
        def fake_run(cmd, *args, **kwargs):
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(fan, "_has_jelos_fan", return_value=True):
            with mock.patch.object(fan.subprocess, "run", fake_run):
                with mock.patch.object(fan, "_reload_jelos_fancontrol") as reload_mock:
                    result = fan._set_jelos_profile("quiet")
        self.assertTrue(result)
        reload_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
