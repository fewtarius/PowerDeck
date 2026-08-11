"""Plugin self-update.

Checks GitHub for a newer release matching the installed plugin name.
Stages a downloaded zip into /tmp and applies it on user confirmation.

Network errors, missing tags, or version mismatch cause the relevant
operation to return a structured {success, error} dict rather than
raising. The frontend reads success/error directly.

TLS: We ship a Mozilla CA bundle (ca-certificates.crt) next to the
plugin and pin it explicitly via ssl.create_default_context. Some
Decky sandboxes and minimal images don't expose the system CA bundle
in a place Python's ssl module can find, so we can't rely on the
default trust store. The bundled cert is the same one the install
script uses via curl --cacert.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import ssl
import subprocess
import time
import urllib.request
from typing import Optional


GITHUB_API = "https://api.github.com/repos/fewtarius/PowerDeck/releases/latest"
STAGING_DIR = "/tmp/powerdeck_staged_update"
LAST_CHECK_FILE = os.path.join(os.environ.get("DECKY_PLUGIN_RUNTIME_DIR", "/tmp"), "last_update_check")


def _runtime_dir() -> str:
    return os.environ.get("DECKY_PLUGIN_RUNTIME_DIR", "/tmp")


def _bundled_cert_path() -> Optional[str]:
    """Locate the bundled CA bundle relative to this module.

    When the plugin is installed, files are flattened to the plugin
    root, so ca-certificates.crt sits next to main.py and powerdeck/.
    When running from the repo, it sits one level up.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "ca-certificates.crt"),
        os.path.join(here, "ca-certificates.crt"),
    ]
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(path):
            return path
    return None


def _ssl_context() -> ssl.SSLContext:
    """Build a TLS context that uses the bundled CA bundle when
    available, falling back to the system trust store."""
    cert = _bundled_cert_path()
    if cert:
        try:
            return ssl.create_default_context(cafile=cert)
        except Exception:
            pass
    return ssl.create_default_context()


def _urlopen(url: str, timeout: int = 10):
    """urllib wrapper that uses the bundled CA bundle."""
    ctx = _ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": "PowerDeck"})
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def current_version() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "VERSION"),
        os.path.join(here, "..", "plugin.json"),
    ]
    for path in candidates:
        try:
            if path.endswith("plugin.json"):
                with open(path, "r") as f:
                    return json.load(f).get("version", "unknown")
            with open(path, "r") as f:
                v = f.read().strip()
                if v:
                    return v
        except OSError:
            continue
    return "unknown"


def _read_last_check() -> Optional[float]:
    if not os.path.exists(LAST_CHECK_FILE):
        return None
    try:
        with open(LAST_CHECK_FILE, "r") as f:
            return float(f.read().strip() or 0)
    except Exception:
        return None


def _write_last_check(ts: float) -> None:
    os.makedirs(os.path.dirname(LAST_CHECK_FILE), exist_ok=True)
    with open(LAST_CHECK_FILE, "w") as f:
        f.write(str(ts))


def get_update_status() -> dict:
    """Return cached status. The actual network check happens in check_for_updates."""
    last = _read_last_check()
    hours = (time.time() - last) / 3600 if last else None
    return {
        "update_available": False,
        "latest_version": None,
        "hours_since_last_check": hours,
    }


def check_for_updates() -> dict:
    """Hit GitHub and report whether a newer release exists."""
    try:
        with _urlopen(GITHUB_API, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {
            "update_available": False,
            "current_version": current_version(),
            "latest_version": current_version(),
            "download_url": None,
            "error": str(e),
        }

    latest = (data.get("tag_name") or "").lstrip("v")
    cur = current_version()
    update_available = bool(latest and latest != cur)
    _write_last_check(time.time())
    download_url = None
    if update_available:
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if name.endswith(".zip"):
                download_url = asset.get("browser_download_url")
                break
    return {
        "update_available": update_available,
        "current_version": cur,
        "latest_version": latest,
        "download_url": download_url,
    }


def stage_update(download_url: str, version: str) -> dict:
    """Download the zip into /tmp/powerdeck_staged_update."""
    try:
        os.makedirs(STAGING_DIR, exist_ok=True)
        out_path = os.path.join(STAGING_DIR, f"PowerDeck-{version}.zip")
        with _urlopen(download_url, timeout=30) as resp, open(out_path, "wb") as f:
            shutil.copyfileobj(resp, f)
        return {"success": True, "staged_path": out_path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def install_staged_update() -> dict:
    """Unzip the staged zip into the plugin dir and restart plugin_loader."""
    try:
        files = sorted(glob.glob(os.path.join(STAGING_DIR, "PowerDeck-*.zip")), key=os.path.getmtime)
        if not files:
            return {"success": False, "error": "No staged zip found"}
        staged = files[-1]
        plugin_dir = os.environ.get("DECKY_PLUGIN_DIR", os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        subprocess.run(["unzip", "-o", staged, "-d", plugin_dir], check=True, timeout=30)
        subprocess.run(["systemctl", "restart", "plugin_loader"], check=False, timeout=10)
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_plugin() -> bool:
    """One-shot check + stage + install."""
    status = check_for_updates()
    if not status["update_available"]:
        return True
    if not status["download_url"]:
        return False
    staged = stage_update(status["download_url"], status["latest_version"])
    if not staged["success"]:
        return False
    installed = install_staged_update()
    return installed["success"]
