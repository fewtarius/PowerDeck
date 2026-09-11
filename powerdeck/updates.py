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
import tempfile
import time
import traceback
import urllib.request
import zipfile
from typing import Optional

import decky_plugin


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


def _overlay_dir(src: str, dst: str, errors: list) -> None:
    """Recursively copy all items from src into dst, overwriting files.

    Uses dirs_exist_ok=True so existing directories are merged rather
    than replaced, preserving any files in dst that aren't in src.
    """
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
    except OSError as e:
        errors.append(f"{os.path.basename(src)}: {e}")


def install_staged_update() -> dict:
    """Extract the staged zip into the plugin dir and restart plugin_loader.

    The release zip has a top-level 'PowerDeck/' directory. We extract to a
    temporary location, locate that directory, and overlay its contents onto
    the actual plugin directory (which is already named 'PowerDeck/'). This
    avoids creating a nested 'PowerDeck/PowerDeck/' structure.

    After extraction, plugin_loader is restarted so the new code is loaded.
    The restart uses a clean environment (LD_LIBRARY_PATH, PYTHONPATH, etc.
    stripped) to avoid OpenSSL library conflicts caused by the Decky/Python
    runtime's bundled libcrypto.so.3.
    """
    try:
        files = sorted(glob.glob(os.path.join(STAGING_DIR, "PowerDeck-*.zip")), key=os.path.getmtime)
        if not files:
            return {"success": False, "error": "No staged zip found"}
        staged = files[-1]

        # Determine the actual plugin directory (where main.py lives)
        plugin_dir = os.environ.get("DECKY_PLUGIN_DIR")
        if not plugin_dir:
            # __file__ = .../powerdeck/updates.py -> plugin_dir = ../
            plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Extract to a temporary directory using Python's zipfile (no external deps)
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(staged, "r") as zf:
                zf.extractall(tmpdir)

            # The release zip has top-level entries like 'PowerDeck/' and
            # 'RyzenAdj/'. We need to copy 'PowerDeck/' contents directly to
            # plugin_dir (flatten, since plugin_dir is already named 'PowerDeck'),
            # and copy other top-level dirs (like 'RyzenAdj/') as-is.
            plugin_name = os.path.basename(plugin_dir)

            copy_errors = []
            for item in os.listdir(tmpdir):
                src = os.path.join(tmpdir, item)
                if not os.path.exists(src):
                    continue
                # Determine destination: if the top-level dir matches the plugin
                # name, flatten it (copy contents into plugin_dir directly).
                # Otherwise, preserve the directory name under plugin_dir.
                if item == plugin_name:
                    if os.path.isdir(src):
                        _overlay_dir(src, plugin_dir, copy_errors)
                    else:
                        try:
                            shutil.copy2(src, plugin_dir)
                        except OSError as e:
                            copy_errors.append(f"{item}: {e}")
                else:
                    dst = os.path.join(plugin_dir, item)
                    try:
                        if os.path.isdir(src):
                            # Remove existing dir first to handle --delete semantics
                            if os.path.exists(dst):
                                shutil.rmtree(dst, ignore_errors=True)
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)
                    except OSError as e:
                        copy_errors.append(f"{item}: {e}")

            if copy_errors:
                # Continue anyway - critical files like VERSION/plugin.json
                # should have been copied. Report non-fatal copy errors.
                decky_plugin.logger.warning(f"Non-fatal copy errors during update: {copy_errors}")

        # Restart plugin_loader with a clean environment to avoid OpenSSL conflicts
        # The Decky/Python runtime may set LD_LIBRARY_PATH to a PyInstaller temp
        # dir containing an incompatible libcrypto.so.3, which breaks systemctl.
        clean_env = os.environ.copy()
        for var in ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD"):
            clean_env.pop(var, None)

        restart_result = subprocess.run(
            ["systemctl", "restart", "plugin_loader"],
            env=clean_env,
            check=False,
            timeout=15,
            capture_output=True,
        )

        if restart_result.returncode != 0:
            stderr = restart_result.stderr.decode(errors="replace").strip() if restart_result.stderr else ""
            stdout = restart_result.stdout.decode(errors="replace").strip() if restart_result.stdout else ""
            combined = stderr or stdout or "unknown error"
            return {"success": False, "error": f"systemctl restart plugin_loader failed (rc={restart_result.returncode}): {combined}"}

        shutil.rmtree(STAGING_DIR, ignore_errors=True)
        return {"success": True}
    except Exception as e:
        traceback.print_exc()
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
