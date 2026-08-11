"""
PowerDeck - power management backend

Layout:
  - plugin.py            - main Plugin class held by main.py, exposes callables
  - state.py             - PowerProfile dataclass, settings persistence, profile storage
  - capabilities.py      - device/processor detection, power-control method selection
  - hardware/            - per-subsystem writers for sysfs/ryzenadj/dbus
  - device_controllers/  - device-specific quirks (ROG Ally, Steam Deck, Lenovo)
  - monitor.py           - AC + game polling loop
  - updates.py           - version check/stage/install
"""
