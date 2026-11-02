"""Pure path resolution shared by managed and standalone entry points."""

import os
from pathlib import Path
import re
import sys


def instance_name(name=None, environ=None):
    env = os.environ if environ is None else environ
    value = name or env.get("ROUNDTABLE_INSTANCE_NAME") or "default"
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value):
        raise ValueError("invalid_instance_name")
    return value


def state_dir(explicit=None, name=None, *, environ=None, platform=None, home=None):
    env = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else Path(home)
    name = instance_name(name, env)
    selected = explicit or env.get("ROUNDTABLE_STATE_DIR")
    if selected:
        return Path(selected).expanduser().absolute()
    if platform == "darwin":
        root = home / "Library" / "Application Support"
    elif platform == "win32":
        if not env.get("LOCALAPPDATA"):
            raise ValueError("localappdata_required")
        root = Path(env["LOCALAPPDATA"])
    else:
        root = Path(env.get("XDG_STATE_HOME") or home / ".local" / "state")
        if not root.is_absolute():
            raise ValueError("xdg_state_home_must_be_absolute")
    return root / "bot-roundtable" / name


def log_dir(state, name=None, *, custom_state=False, platform=None, home=None):
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else Path(home)
    if platform == "darwin" and not custom_state:
        return home / "Library" / "Logs" / "bot-roundtable" / instance_name(name)
    return Path(state) / "logs"


def path_warnings(state, checkout, *, platform=None, home=None):
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else Path(home)
    state, checkout = Path(state).absolute(), Path(checkout).absolute()
    warnings = []
    if state == checkout or checkout in state.parents:
        warnings.append("state_inside_checkout_migrate_recommended")
    if platform == "darwin":
        protected = [home / n for n in ("Documents", "Desktop", "Downloads")]
        protected += [home / "Library" / "Mobile Documents", home / "Library" / "CloudStorage"]
        if any(state == p or p in state.parents for p in protected):
            warnings.append("state_in_macos_protected_directory")
        if any(checkout == p or p in checkout.parents for p in protected):
            warnings.append("code_in_macos_protected_directory")
    # Existence only: never inspect the legacy installation or its credentials.
    legacy = checkout / "data" / "local"
    if legacy != state and legacy.exists():
        warnings.append("legacy_state_detected_use_migrate_state")
    return warnings
