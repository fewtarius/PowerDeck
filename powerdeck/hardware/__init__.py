"""Per-subsystem hardware writers. Each module exposes a small set of
synchronous + async functions: read_sysfs / write_sysfs for plain sysfs,
set_X / get_X for higher-level operations."""
