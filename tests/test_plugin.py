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
import subprocess
import unittest
from unittest import mock

# conftest runs on import via the package; ensure it's loaded.
import tests.conftest  # noqa: F401

from powerdeck import capabilities
from powerdeck import plugin as plugin_module
from powerdeck.hardware import (
    cpu as cpu_mod,
    platform_profile as platform_profile_mod,
    pstate as pstate_mod,
    tdp as tdp_mod,
)
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

        def fake_set_tdp(w, *, prefer_native=True, **kwargs):
            self.calls["set_tdp"].append((w, prefer_native))
            return False, "soft_fallback"
        self.p._apply_tdp_soft = lambda w: (self.calls["soft"].append(w), True)[1]
        original = tdp_mod.set_tdp
        self.addCleanup(setattr, tdp_mod, "set_tdp", original)
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

    def test_platform_profile_without_native_is_noop(self):
        # ACPI platform_profile owns the watt level. On devices where the
        # platform profile only drives EC power limits + fan (Emdoor N161L,
        # Strix Halo), CPU scaling stays under amd-pstate-epp and belongs to
        # the profile's governor/epp fields. Soft-mapping watts here rewrote
        # CPU state on every switch and fought those fields.
        self.p.capabilities = _caps(active_method="platform_profile", native=False, plat_profile=True)
        self.assertTrue(self.p._apply_tdp(15))
        self.assertEqual(self.calls["soft"], [])
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


class PStateModeMigrationTests(unittest.TestCase):
    """P-State mode handling for power-saving profiles.

    On amd-pstate, 'guided' mode makes the kernel ignore userspace
    governor/EPP writes, so a battery profile with pstateMode='guided'
    (powersave + epp='power') has zero effect — CPU idles at ~12W
    instead of ~4W.

    These tests verify the contract:
    1. New battery default profiles use pstateMode="active" so EPP and
       governor are honored (EPP files only exist in active mode on
       classic amd-pstate).
    2. New AC default profiles leave pstateMode=None (don't override
       kernel default — performance profiles don't need active mode).
    3. _apply_profile_full NEVER overrides a user-set pstateMode
       (respects active/passive/guided/explicit choices).
    4. _apply_profile_full does NOT write to amd_pstate/status when
       pstateMode is None (leaves kernel default untouched).
    """

    def test_default_battery_profile_sets_active_mode(self):
        from powerdeck.state import default_profile
        profile = default_profile(is_ac=False, default_tdp=15,
                                  gpu_min=400, gpu_max=1600)
        self.assertEqual(profile.pstateMode, "active",
                         "battery default must use active mode for EPP/governor to work")

    def test_default_ac_profile_does_not_force_active(self):
        from powerdeck.state import default_profile
        profile = default_profile(is_ac=True, default_tdp=15,
                                  gpu_min=400, gpu_max=1600)
        self.assertIsNone(profile.pstateMode,
                          "AC default should not override kernel pstate mode")

    def test_apply_profile_full_respects_explicit_passive_mode(self):
        """When a profile explicitly sets pstateMode='passive', that
        choice must be respected (not overwritten with 'active')."""
        self.p = plugin_module.Plugin()
        self.p.__dict__.pop("capabilities", None)
        self.p.capabilities = _caps(active_method="none", native=False, plat_profile=False, vendor="amd")
        self.p.capabilities.pstate.available = True
        self.p.capabilities.pstate.mode_switch_supported = True
        written = {}
        def fake_set_mode(mode):
            written["mode"] = mode
            return True
        self.p._applier = lambda key: {"pstateMode": fake_set_mode}.get(key, lambda _v: True)
        profile = PowerProfile()
        profile.pstateMode = "passive"
        with mock.patch.object(pstate_mod, "is_available", return_value=True):
            self.p._apply_profile_full(profile)
        self.assertEqual(written.get("mode"), "passive",
                         "explicit pstateMode must be respected, not overwritten")

    def test_apply_profile_full_does_not_override_none_mode(self):
        """When a profile has pstateMode=None (not set), _apply_profile_full
        must NOT write anything to amd_pstate/status — the kernel's current
        mode should be left untouched. Never override state the user hasn't
        explicitly chosen."""
        self.p = plugin_module.Plugin()
        self.p.__dict__.pop("capabilities", None)
        self.p.capabilities = _caps(active_method="none", native=False, plat_profile=False, vendor="amd")
        self.p.capabilities.pstate.available = True
        self.p.capabilities.pstate.mode_switch_supported = True
        written = {}
        def fake_set_mode(mode):
            written["mode"] = mode
            return True
        self.p._applier = lambda key: {"pstateMode": fake_set_mode}.get(key, lambda _v: True)
        profile = PowerProfile()
        profile.pstateMode = None  # not set in profile
        with mock.patch.object(pstate_mod, "is_available", return_value=True):
            self.p._apply_profile_full(profile)
        self.assertIsNone(written.get("mode"),
                         "must NOT write pstateMode when profile has pstateMode=None")


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


class LiveStateTests(unittest.TestCase):
    """get_state must report live CPU state, not the saved profile."""

    def test_state_reports_live_governor_epp_platform_profile(self):
        p = plugin_module.Plugin()
        p.capabilities = _caps(active_method="platform_profile", native=False, plat_profile=True)
        with mock.patch.object(cpu_mod, "available_governors", return_value=["performance", "powersave"]), \
                mock.patch.object(cpu_mod, "get_governor", return_value="powersave"), \
                mock.patch.object(cpu_mod, "get_epp", return_value="performance"), \
                mock.patch.object(platform_profile_mod, "get_profile", return_value="performance"):
            state = _run(p.get_state())
        caps = state["capabilities"]
        self.assertEqual(caps["governor"], "powersave")
        self.assertEqual(caps["epp"], "performance")
        self.assertEqual(caps["platform_profile"], "performance")

    def test_epp_available_does_not_depend_on_platform_profile(self):
        # Regression: a device with ACPI platform_profile AND amd-pstate-epp
        # in active mode must report EPP as available. The UI used to hide
        # the EPP slider whenever active_method == "platform_profile".
        p = plugin_module.Plugin()
        p.capabilities = _caps(active_method="platform_profile", native=False, plat_profile=True)
        with mock.patch.object(pstate_mod, "is_available", return_value=True), \
                mock.patch.object(pstate_mod, "get_mode", return_value="active"), \
                mock.patch.object(cpu_mod, "available_epp",
                                  return_value=["power", "balance_performance", "performance"]), \
                mock.patch.object(cpu_mod, "available_governors",
                                  return_value=["performance", "powersave"]):
            caps = p._pstate_caps()
        self.assertTrue(caps["epp_available"])
        self.assertIn("performance", caps["epp_preferences"])


class GovernorSnapTests(unittest.TestCase):
    """Profiles must not keep a governor the driver cannot apply."""

    def test_unavailable_governor_snaps_to_available(self):
        p = plugin_module.Plugin()
        profile = PowerProfile(governor="schedutil")
        with mock.patch.object(cpu_mod, "available_governors",
                               return_value=["performance", "powersave"]), \
                mock.patch.object(cpu_mod, "_best_epp_governor", return_value="powersave"):
            changed = p._snap_profile_to_hardware(profile)
        self.assertTrue(changed)
        self.assertEqual(profile.governor, "powersave")

    def test_available_governor_left_alone(self):
        p = plugin_module.Plugin()
        profile = PowerProfile(governor="powersave")
        with mock.patch.object(cpu_mod, "available_governors",
                               return_value=["performance", "powersave"]):
            self.assertFalse(p._snap_profile_to_hardware(profile))
        self.assertEqual(profile.governor, "powersave")

    def test_default_profile_accepts_driver_governor(self):
        prof = default_profile(True, 15, 400, 1600, governor="powersave")
        self.assertEqual(prof.governor, "powersave")


class TdpOwnershipTests(unittest.TestCase):
    """A profile only manages watts once the user sets one."""

    def setUp(self):
        self.p = plugin_module.Plugin()
        self.p.__dict__.pop("capabilities", None)
        self.p.capabilities = capabilities.Capabilities()
        self.calls = []
        original = tdp_mod.set_tdp
        self.addCleanup(setattr, tdp_mod, "set_tdp", original)
        tdp_mod.set_tdp = lambda w, prefer_native=True, **kwargs: (
            self.calls.append((w, prefer_native)), (True, "ok")
        )[1]
        self.p._apply_tdp_soft = lambda w: (self.calls.append(("soft", w)), True)[1]

    def test_default_profile_leaves_tdp_unset(self):
        for is_ac in (True, False):
            prof = default_profile(is_ac, 15, 400, 1600)
            self.assertIsNone(prof.tdp, "fresh profiles must not cap the chip")

    def test_unset_tdp_writes_nothing(self):
        self.p.capabilities = _caps(active_method="native_tdp", native=True, plat_profile=False)
        self.assertTrue(self.p._apply_tdp(None))
        self.assertEqual(self.calls, [], "no hardware write when tdp is unset")

    def test_platform_profile_device_with_native_uses_ryzenadj(self):
        # Emdoor N161L / Strix Halo: platform_profile exists AND ryzenadj
        # works. The watt limit must go through ryzenadj; platform_profile
        # never writes the SMU package limit.
        self.p.capabilities = _caps(active_method="native_tdp", native=True, plat_profile=True)
        self.assertTrue(self.p._apply_tdp(55))
        self.assertEqual(self.calls, [(55, True)])

    def test_native_wins_over_platform_profile_in_detection(self):
        with mock.patch.object(capabilities, "_detect_acpi_platform_profile",
                               return_value=(True, ["low-power", "balanced", "performance"])), \
                mock.patch.object(capabilities, "_detect_secure_boot", return_value=False), \
                mock.patch.object(capabilities, "_detect_dev_mem", return_value=True):
            pc = capabilities._detect_power_control_method()
        self.assertEqual(pc.active_method, "native_tdp")
        self.assertTrue(pc.native_tdp_available)
        self.assertTrue(pc.platform_profile_available)

    def test_platform_profile_owns_watts_when_no_native(self):
        with mock.patch.object(capabilities, "_detect_acpi_platform_profile",
                               return_value=(True, ["low-power", "balanced", "performance"])), \
                mock.patch.object(capabilities, "_detect_secure_boot", return_value=True), \
                mock.patch.object(capabilities, "_detect_dev_mem", return_value=True):
            pc = capabilities._detect_power_control_method()
        self.assertEqual(pc.active_method, "platform_profile")
        self.assertFalse(pc.native_tdp_available)


class TdpRangeTests(unittest.TestCase):
    """The slider ceiling comes from the spec table, not the live SMU."""

    def setUp(self):
        capabilities._TDP_RANGE_CACHE = None
        capabilities._SMU_INFO_CACHE = None

    def tearDown(self):
        capabilities._TDP_RANGE_CACHE = None
        capabilities._SMU_INFO_CACHE = None

    def test_spec_ceiling_wins_over_live_smu(self):
        # PPT LIMIT APU reports what the firmware is currently set to, not
        # what the part is rated for. The 70W reading on the Emdoor N161L
        # must not become the slider ceiling when AMD rates the part at 120W.
        with mock.patch.object(capabilities, "_ryzenadj_smu_info",
                               return_value={"PPT LIMIT APU": 70.0, "STAPM LIMIT": 55.0}), \
                mock.patch("powerdeck.hardware.processor_db.tdp_bounds",
                           return_value={"min": 45, "max": 120, "default": 55}):
            tdp_min, tdp_max, default = capabilities._tdp_limits_from_processor_db()
        self.assertEqual(tdp_max, 120, "cTDP ceiling must come from the spec table")
        self.assertEqual(tdp_min, 4, "floor stays low so battery profiles can save power")
        self.assertEqual(default, 55, "live STAPM is what an unset profile displays")

    def test_falls_back_when_smu_unreadable(self):
        with mock.patch.object(capabilities, "_ryzenadj_smu_info", return_value={}), \
                mock.patch("powerdeck.hardware.processor_db.tdp_bounds", return_value=None):
            tdp_min, tdp_max, default = capabilities._tdp_limits_from_processor_db()
        self.assertEqual((tdp_min, tdp_max, default), (4, 25, 15))


class TieredBurstTests(unittest.TestCase):
    """STAPM is sustained; fast/slow burst above it up to measured ceilings."""

    def test_120w_matches_measured_config(self):
        # Verified on Strix Halo: stapm 120, fast 120, slow 100.
        self.assertEqual(
            tdp_mod.tiered_limits(120, fast_max=120, slow_max=100, burst_delta=25),
            (120, 120, 100),
        )

    def test_slow_stays_capped_below_stapm(self):
        # A part rated to 120W but measuring a 100W slow ceiling sustains
        # 100W. Flooring slow to stapm would lie about sustained watts.
        stapm, _, slow = tdp_mod.tiered_limits(120, fast_max=120, slow_max=100,
                                               burst_delta=25)
        self.assertEqual(slow, 100)
        self.assertLess(slow, stapm)

    def test_burst_above_sustained_at_moderate_wattage(self):
        self.assertEqual(
            tdp_mod.tiered_limits(55, fast_max=120, slow_max=100, burst_delta=25),
            (55, 80, 68),
        )

    def test_no_ceilings_collapses_to_sustained(self):
        self.assertEqual(tdp_mod.tiered_limits(55), (55, 55, 55))

    def test_fast_never_below_stapm(self):
        stapm, fast, _ = tdp_mod.tiered_limits(100, fast_max=120, burst_delta=5)
        self.assertGreaterEqual(fast, stapm)

    def test_set_tdp_passes_tiered_values_and_apu_limit(self):
        captured = {}

        def fake_native(watts, **kwargs):
            captured["watts"] = watts
            captured.update(kwargs)
            return True

        with mock.patch.object(tdp_mod, "set_tdp_native", side_effect=fake_native):
            ok, method = tdp_mod.set_tdp(120, fast_max=120, slow_max=100, burst_delta=25)
        self.assertTrue(ok)
        self.assertEqual(method, "ryzenadj")
        self.assertEqual(captured["stapm_limit"], 120_000)
        self.assertEqual(captured["fast_limit"], 120_000)
        self.assertEqual(captured["sustained_limit"], 100_000)
        self.assertEqual(captured["apu_slow_limit"], 120_000)


class SkinTempFlagTests(unittest.TestCase):
    """--apu-skin-temp aborts the whole ryzenadj run on parts without one."""

    def test_ai_max_detected_as_strix_halo(self):
        # /proc/cpuinfo reports the marketing name, never "Strix Halo".
        cpuinfo = "model name\t: AMD RYZEN AI MAX+ 395 w/ Radeon 8060S\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=cpuinfo)):
            self.assertTrue(tdp_mod.is_strix_halo())

    def test_non_halo_not_flagged(self):
        cpuinfo = "model name\t: AMD Ryzen 7 7840U w/ Radeon 780M\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=cpuinfo)):
            self.assertFalse(tdp_mod.is_strix_halo())

    def test_retries_without_skin_temp_when_family_rejects_it(self):
        calls = []
        reject = subprocess.CompletedProcess(
            args=[], returncode=255, stdout="",
            stderr="set_apu_skin_temp_limit is not supported on this family",
        )
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return reject if any(a.startswith("--apu-skin-temp") for a in args) else ok

        with mock.patch.object(tdp_mod.subprocess, "run", side_effect=fake_run):
            result = tdp_mod.set_tdp_native(55, omit_skin_temp=False)
        self.assertTrue(result, "must succeed after dropping the unsupported flag")
        self.assertTrue(any("--apu-skin-temp" in " ".join(a) for a in calls))
        self.assertFalse("--apu-skin-temp" in " ".join(calls[-1]))


if __name__ == "__main__":
    unittest.main()
