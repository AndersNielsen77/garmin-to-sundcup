"""Config, paths and credential storage (system keyring)."""

from __future__ import annotations

import getpass
import json
import os
import sys
import tomllib
from pathlib import Path

import keyring

APP = "garmin_to_sundcup"
PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / APP
CONFIG_FILE = CONFIG_DIR / "config.toml"
GARMIN_TOKENS = CONFIG_DIR / "garth"
STATE_FILE = STATE_DIR / "synced.json"

DEFAULTS = {
    "garmin_email": "",
    "sundcup_username": "",
    "sundcup_base_url": "https://sundcup.nc3.politi.dk",
    "ca_bundle": str(PROJECT_DIR / "certs" / "sundcup-ca-bundle.pem"),
    "visibility": "TeamOnly",
    "note_template": "{name} (Garmin)",
    # Warn when Garmin's cloud has no step data newer than this many minutes.
    "stale_after_minutes": 120,
    # Ask which activities to upload when running interactively.
    "pick": True,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as fh:
            cfg.update(tomllib.load(fh))
    for key in ("garmin_email", "sundcup_username"):
        if not cfg[key]:
            sys.exit(f"Missing {key!r} in {CONFIG_FILE}")
    return cfg


# --- credentials -----------------------------------------------------------
# Passwords live in the system keyring (SecretService/gnome-keyring on Fedora).
# They are never written to disk by this tool.


def get_password(kind: str, account: str, *, prompt: bool = True) -> str:
    pw = keyring.get_password(f"{APP}:{kind}", account)
    if pw:
        return pw
    if not prompt or not sys.stdin.isatty():
        sys.exit(
            f"No {kind} password stored for {account}. "
            f"Run: garmin-to-sundcup set-password {kind}"
        )
    pw = getpass.getpass(f"{kind} password for {account}: ")
    keyring.set_password(f"{APP}:{kind}", account, pw)
    return pw


def set_password(kind: str, account: str) -> None:
    pw = getpass.getpass(f"New {kind} password for {account}: ")
    keyring.set_password(f"{APP}:{kind}", account, pw)


def clear_password(kind: str, account: str) -> None:
    try:
        keyring.delete_password(f"{APP}:{kind}", account)
    except keyring.errors.PasswordDeleteError:
        pass


# --- sync state ------------------------------------------------------------


def load_state() -> dict:
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    for key in ("activities", "steps", "skipped"):
        state.setdefault(key, {})
    return state


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))
