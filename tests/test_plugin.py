"""Regression tests for the PowerDeck backend.

These cover the correctness defects documented in
``scratch/audit-findings-2026-10-15.md`` (D1, D2, D3) plus the apply
routing logic that D3 depends on. Hardware writers are monkey-patched
so the tests are deterministic and require no sysfs / ryzenadj.

Run with::

    python3 -m unittest tests.test_plugin -v

The ``tests/conftest.py`` module installs a fake ``decky_plugin`` and a
tmp settings dir before import; no test should touch real hardware.
"""
from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock

# conftest runs on import via the package; ensure it's loaded.
import tests.conftest  # noqa: F401

from powerdeck import capabilities
from powerdeck import plugin as plugin_module
from powerdeck.hardware import cpu as cpu_mod, tdp as tdp_mod, pstate as pstate_mod
from powerdeck.state import PowerProfile, default_profile


def _caps(active_method: str, native: bool, plat_profile: bool,
          vendor: str = "amd", driver: str = "amd-pstate-epp") -> capabilities.Capabilities:
    """Build a Capabilities object matching a specific power-control scenario."""
    c = capabilities.Capabilities()
    c.power_control.active_method = active_method
    c.power_control.native_tdp_available = native
    c.power_control.platform_profile_available = plat_profile
    c.gpu_vendor = vendor
    c.scaling_driver = driver
    return c


def _run(coro):
    """Await a coroutine in a fresh event loop (Py3.12 has no current loop)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TdpControlAvailabilityTests(unittest.TestCase):
    """D2: has_soft_control must be True only in the soft-fallback branch."""

    def setUp(self):
        tests.conftest  # ensure import side-effects ran
        self.p = plugin_module.Plugin()
        self.p.__dict__.pop("capabilities", None)

    def _avail(self, **kw) -> dict:
        caps = _caps(**kw)
        self.p.capabilities = caps
        return self.p._tdp_control_availability(caps)

    def test_native_tdp_has_no_soft_control(self):
        a = self._avail(active_method="native_tdp", native=True, plat_profile=False)
        self.assertTrue(a["available"])
        self.assertEqual(a["method"], "native_tdp")
        self.assertFalse(a["has_soft_control"])

    def test_intel_rapl_has_no_soft_control(self):
        a = self._avail(active_method="none", native=False, plat_profile=False, vendor="intel")
        self.assertTrue(a["available"])
        self.assertEqual(a["method"], "intel_rapl")
        self.assertFalse(a["has_soft_control"])

    def test_platform_profile_has_no_soft_control(self):
        # ACPI platform_profile OWNS the watt slider -> no soft fallback.
        a = self._avail(active_method="platform_profile", native=False, plat_profile=True)
        self.assertTrue(a["available"])
        self.assertEqual(a["method"], "platform_profile")
        self.assertFalse(a["has_soft_control"])

    def test_soft_fallback_has_soft_control(self):
        # Secure Boot on, no ACPI, no native -> the ONLY TDP path is the
        # governor/EPP soft mapping. has_soft_control must be True here.
        a = self._avail(active_method="none", native=False, plat_profile=False)
        self.assertFalse(a["available"])
        self.assertEqual(a["method"], "soft")
        self.assertTrue(a["has_soft_control"], "soft-only device must advertise has_soft_control")

    def test_soft_fallback_on_amd_with_platform_profile_unavailable(self):
        a = self._avail(active_method="native_tdp", native=False, plat_profile=False, vendor="amd")
        self.assertTrue(a["has_soft_control"])


class ApplyTdpRoutingTests(unittest.TestCase):
    """D3: _apply_tdp must route a soft-only AMD device to _apply_tdp_soft."""

    def setUp(self):
        self.p = plugin_module.Plugin()
        self.p.__dict__.pop("capabilities", None)
        self.p.capabilities = capabilities.Capabilities()
        self.calls = {"set_tdp": [], "soft": [], "native": []}

        def fake_set_tdp(w, *, prefer_native=True):
            self.calls["set_tdp"].append((w, prefer_native))
            return False, "soft_fallback"
        self.p._apply_tdp_soft = lambda w: (self.calls["soft"].append(w), True)[1]
        tdp_mod.set_tdp = fake_set_tdp

    def test_native_device_calls_set_tdp_prefers_native(self):
        self.p.capabilities = _caps(active_method="native_tdp", native=True, plat_profile=False)
        self.p._apply_tdp(15)
        self.assertEqual(self.calls["set_tdp"], [(15, True)])
        self.assertEqual(self.calls["soft"], [])

    def test_soft_only_amd_calls_apply_tdp_soft(self):
        # Scenario B: Secure Boot, no ACPI, no native -> must NOT call the
        # failing set_tdp; must call _apply_tdp_soft instead.
        self.p.capabilities = _caps(active_method="none", native=False, plat_profile=False, vendor="amd")
        self.p._apply_tdp(15)
        self.assertEqual(self.calls["soft"], [15])
        self.assertEqual(self.calls["set_tdp"], [], "soft-only AMD must not call set_tdp")

    def test_intel_device_calls_set_tdp_prefers_sysfs(self):
        self.p.capabilities = _caps(active_method="none", native=False, plat_profile=False, vendor="intel")
        self.p._apply_tdp(20)
        self.assertEqual(self.calls["set_tdp"], [(20, False)])
        self.assertEqual(self.calls["soft"], [])

    def test_platform_profile_without_native_calls_soft(self):
        # ACPI platform_profile owns watts but native is also off -> soft map.
        self.p.capabilities = _caps(active_method="platform_profile", native=False, plat_profile=True)
        self.p._apply_tdp(15)
        self.assertEqual(self.calls["soft"], [15])
        self.assertEqual(self.calls["set_tdp"], [])


class PStateCapsTests(unittest.TestCase):
    """P-State visibility gating that drove issues #1 and #2.

    Issue #1: the P-State mode selector was hidden by
    `!activePowerControl` in Content.tsx, which is True whenever a
    native_tdp / platform_profile method is active -- i.e. on the
    majority of AMD handhelds where mode switching is most useful
    (switch to active to enable EPP, switch to passive to hand
    control to the platform).

    Issue #2: in passive mode the cpufreq governor is the primary
    control surface, so the governor slider must remain visible.

    The frontend now reads `mode_switch_supported` (not the old
    `!activePowerControl` check) and the backend's _pstate_caps() sets
    it True for any amd-pstate device. These tests lock in that
    contract.
    """

    def setUp(self):
        self.p = plugin_module.Plugin()
        self.p.__dict__.pop("capabilities", None)
        self.p.capabilities = capabilities.Capabilities()

    def test_pstate_caps_returns_mode_switch_supported(self):
        with mock.patch.object(pstate_mod, "is_available", return_value=True), \
             mock.patch.object(pstate_mod, "get_mode", return_value="active"):
            caps = self.p._pstate_caps()
        self.assertIsNotNone(caps)
        self.assertTrue(caps["mode_switch_supported"],
                        "frontend gates <PstateSection> on this flag")

    def test_pstate_caps_none_when_not_available(self):
        with mock.patch.object(pstate_mod, "is_available", return_value=False):
            self.assertIsNone(self.p._pstate_caps())

    def test_epp_available_only_in_active_mode(self):
        for mode in ("active", "passive", "guided"):
            with mock.patch.object(pstate_mod, "is_available", return_value=True), \
                 mock.patch.object(pstate_mod, "get_mode", return_value=mode):
                caps = self.p._pstate_caps()
            self.assertEqual(caps["epp_available"], mode == "active",
                             f"epp_available must be True only in active mode (got {caps['epp_available']} for {mode})")

    def test_epp_preferences_empty_in_passive_mode(self):
        with mock.patch.object(pstate_mod, "is_available", return_value=True), \
             mock.patch.object(pstate_mod, "get_mode", return_value="passive"):
            caps = self.p._pstate_caps()
        self.assertEqual(caps["epp_preferences"], [],
                         "passive mode must clear epp_preferences (frontend hides EPP slider)")

    def test_epp_preferences_populated_in_active_mode(self):
        with mock.patch.object(pstate_mod, "is_available", return_value=True), \
             mock.patch.object(pstate_mod, "get_mode", return_value="active"), \
             mock.patch.object(cpu_mod, "available_epp", return_value=["power", "performance"]):
            caps = self.p._pstate_caps()
        self.assertEqual(caps["epp_preferences"], ["power", "performance"])
        self.assertTrue(caps["epp_available"])


class ApplySettingsTests(unittest.TestCase):
    """D1: apply_settings must (a) return False when a write fails, and
    (b) NOT persist the rejected value to disk."""

    def setUp(self):
        self.p = plugin_module.Plugin()
        self.p.__dict__.pop("capabilities", None)
        self.p.capabilities = capabilities.Capabilities()
        self.p.capabilities = _caps(active_method="native_tdp", native=True, plat_profile=False)
        self.p.current_profile = PowerProfile()
        self.p.current_profile.tdp = 15
        self.p.profile_store.save(self.p.current_profile_id, self.p.current_profile)
        # Make the tdp writer fail; nothing else should be touched.
        self.p._apply_tdp = lambda w: False

    def test_failed_write_returns_false(self):
        ok = _run(self.p.apply_settings({"tdp": 99}))
        self.assertFalse(ok, "apply_settings must return False when the hardware write failed")

    def test_failed_write_not_persisted(self):
        _run(self.p.apply_settings({"tdp": 99}))
        persisted = self.p.profile_store.load(self.p.current_profile_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.tdp, 15, "rejected value must not be persisted")

    def test_failed_write_not_in_memory(self):
        _run(self.p.apply_settings({"tdp": 99}))
        self.assertEqual(self.p.current_profile.tdp, 15,
                         "rejected value must not be applied to the in-memory profile")

    def test_successful_write_returns_true(self):
        self.p._apply_tdp = lambda w: True
        ok = _run(self.p.apply_settings({"tdp": 25}))
        self.assertTrue(ok)
        persisted = self.p.profile_store.load(self.p.current_profile_id)
        self.assertEqual(persisted.tdp, 25)

    def test_mixed_success_and_failure_returns_false(self):
        # tdp fails, cpuBoost succeeds. Whole call must report failure.
        self.p._apply_tdp = lambda w: False
        cpu_mod.set_boost = lambda enabled: True
        ok = _run(self.p.apply_settings({"tdp": 99, "cpuBoost": False}))
        self.assertFalse(ok)
        persisted = self.p.profile_store.load(self.p.current_profile_id)
        self.assertEqual(persisted.tdp, 15)
        self.assertEqual(persisted.cpuBoost, False)

    def test_unknown_field_ignored(self):
        # A field that isn't a profile attribute must not be persisted.
        # The tdp write itself succeeds (we only care about the unknown
        # field being dropped, not persisted).
        self.p._apply_tdp = lambda w: True
        ok = _run(self.p.apply_settings({"tdp": 16, "bogus_field": 1}))
        self.assertTrue(ok)
        persisted = self.p.profile_store.load(self.p.current_profile_id)
        self.assertEqual(persisted.tdp, 16)
        self.assertNotIn("bogus_field", persisted.to_dict())


class ProfileStoreTests(unittest.TestCase):
    """Sanity for the persistence layer the audit relies on."""

    def test_load_missing_returns_none(self):
        p = plugin_module.Plugin()
        self.assertIsNone(p.profile_store.load("does_not_exist_ac"))

    def test_save_then_load_roundtrip(self):
        p = plugin_module.Plugin()
        prof = default_profile(True, 15, 400, 1600)
        pid = "testprofile_ac"
        self.assertTrue(p.profile_store.save(pid, prof))
        loaded = p.profile_store.load(pid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.tdp, prof.tdp)
        self.assertEqual(loaded.governor, prof.governor)


if __name__ == "__main__":
    unittest.main()
