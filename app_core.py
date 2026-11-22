"""Logic of PC-MQTT-Notifier that does not need a window: paths, config
(load, migrate, safe save, password in the Windows Credential Manager),
log file, MQTT payloads, versions and update checks, settings validation.

No tkinter / customtkinter here, so it can be tested anywhere.
"""
import hashlib
import json
import logging
import logging.handlers
import os
import re
import shutil
import sys
import time

import notification_styles as nstyles

APP_NAME = "PC-MQTT-Notifier"
INSTALLER_NAME = "PC-MQTT-Notifier-Setup.exe"
SHA256SUMS_NAME = "SHA256SUMS.txt"
KEYRING_SERVICE = APP_NAME
KEYRING_USER = "mqtt_password"

DEFAULT_CONFIG = {
    "mqtt_broker": "",
    "mqtt_port": 1883,
    "mqtt_username": "",
    "mqtt_password": "",
    "mqtt_topic": "pc-notifier/notify",
    "mqtt_tls": False,
    "duration": 5,
    "position": "top-center",
    "theme": "dark",
    "alpha": 0.94,
    "fps": 50,
    "corner_radius": 30,
    "scale": 1.0,
    "language": "en",
    "notification_style": nstyles.DEFAULT_STYLE,
    "glass_glow": nstyles.DEFAULT_GLOW,
    "aurora_palette": nstyles.DEFAULT_PALETTE,
}
POSITIONS = ("top-center", "top-right", "bottom-right", "bottom-center")

log = logging.getLogger("notifier")


# --- Paths ---------------------------------------------------------------

def app_dir():
    """Folder for config and log: %APPDATA%\\PC-MQTT-Notifier on Windows."""
    override = os.environ.get("PC_MQTT_NOTIFIER_HOME")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".config", APP_NAME)


def config_path():
    return os.path.join(app_dir(), "config.json")


def program_dirs():
    """Where the program's own files can be: inside the exe, next to it, next to this file."""
    dirs = []
    if getattr(sys, "frozen", False):
        if getattr(sys, "_MEIPASS", None):
            dirs.append(sys._MEIPASS)
        dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    out = []
    for d in dirs:
        if d not in out:
            out.append(d)
    return out


def resource_path(name):
    for d in program_dirs():
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return os.path.join(program_dirs()[0], name)


def legacy_config_paths():
    """Where older versions saved config.json (the current working folder)."""
    cands = [os.path.join(os.getcwd(), "config.json")]
    cands += [os.path.join(d, "config.json") for d in program_dirs()]
    new = os.path.normcase(os.path.abspath(config_path()))
    out = []
    for p in cands:
        ap = os.path.normcase(os.path.abspath(p))
        if ap != new and ap not in [os.path.normcase(os.path.abspath(x)) for x in out]:
            out.append(p)
    return out


# --- Log -----------------------------------------------------------------

def setup_logging():
    """Log file in the app folder (the exe has no console)."""
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        os.makedirs(app_dir(), exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            os.path.join(app_dir(), "notifier.log"), maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        pass
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    return log


# --- Password in the Windows Credential Manager (keyring) ------------------

def _keyring():
    try:
        import keyring
        return keyring
    except Exception as e:
        log.warning("keyring non disponibile: %s", e)
        return None


def keyring_get():
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception as e:
        log.warning("Lettura della password dal Gestore credenziali fallita: %s", e)
        return None


def keyring_set(password):
    """True if the password is now in the Credential Manager (or removed when empty)."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        if password:
            kr.set_password(KEYRING_SERVICE, KEYRING_USER, password)
            return kr.get_password(KEYRING_SERVICE, KEYRING_USER) == password
        try:
            kr.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            pass
        return True
    except Exception as e:
        log.warning("Scrittura della password nel Gestore credenziali fallita: %s", e)
        return False


# --- Config --------------------------------------------------------------

def sanitize_config(cfg):
    """Merge with the defaults and fix types, so a missing or wrong key never breaks the app."""
    out = dict(DEFAULT_CONFIG)
    if isinstance(cfg, dict):
        # style migration first, on what was really in the file (enable_fluid)
        out.update(nstyles.migrate_config(dict(cfg)))

    def num(key, kind, lo, hi):
        try:
            v = kind(out[key])
            if not (lo <= v <= hi):
                raise ValueError
            out[key] = v
        except Exception:
            out[key] = DEFAULT_CONFIG[key]

    num("mqtt_port", int, 1, 65535)
    num("duration", float, 0.5, 86400)
    num("alpha", float, 0.2, 1.0)
    num("fps", int, 1, 240)
    num("corner_radius", int, 0, 100)
    num("scale", float, 0.3, 3.0)
    for key in ("mqtt_broker", "mqtt_username", "mqtt_password", "mqtt_topic", "language"):
        if not isinstance(out.get(key), str):
            out[key] = DEFAULT_CONFIG[key] if out.get(key) is None else str(out[key])
    out["mqtt_tls"] = bool(out.get("mqtt_tls", False))
    if out.get("position") not in POSITIONS:
        out["position"] = DEFAULT_CONFIG["position"]
    return nstyles.migrate_config(out)


def migrate_legacy_config(log_fn=None):
    """Move config.json from the old place (working folder) to the app folder,
    only if there is none there yet. Returns the path moved, or None."""
    new = config_path()
    if os.path.exists(new):
        return None
    for old in legacy_config_paths():
        if os.path.isfile(old):
            try:
                os.makedirs(os.path.dirname(new), exist_ok=True)
                shutil.copy2(old, new)
                try:
                    os.remove(old)
                except Exception as e:
                    log.warning("Config copiato ma il vecchio %s non si cancella: %s", old, e)
                log.info("Config spostato da %s a %s", old, new)
                return old
            except Exception as e:
                log.error("Spostamento del config da %s fallito: %s", old, e)
                return None
    return None


def write_json_atomic(path, data):
    """Write to a temporary file, then rename: a crash never leaves half a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_config(cfg, path=None):
    """Save the config; the MQTT password goes to the Credential Manager when possible."""
    path = path or config_path()
    data = dict(cfg)
    password = data.get("mqtt_password", "")
    if keyring_set(password):
        data.pop("mqtt_password", None)
        data["mqtt_password_keyring"] = True
    else:
        data["mqtt_password_keyring"] = False
        if password:
            log.warning("Password MQTT salvata in chiaro in config.json (Gestore credenziali non disponibile)")
    write_json_atomic(path, data)


def load_config(path=None):
    """Config ready to use: migrated, merged with the defaults, password filled in."""
    if path is None:
        migrate_legacy_config()
        path = config_path()
    raw = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("il config non è un oggetto JSON")
        except Exception as e:
            broken = f"{path}.broken-{time.strftime('%Y%m%d-%H%M%S')}"
            try:
                os.replace(path, broken)
            except Exception:
                broken = "(non rinominato)"
            log.error("config.json illeggibile (%s): copia in %s, riparto dai valori di partenza", e, broken)
            raw = None
    cfg = sanitize_config(raw or {})
    if raw is None:
        return cfg

    plain = raw.get("mqtt_password") or ""
    if plain:
        # A clear-text password in the file (first start after the update):
        # save again, which moves it to the Credential Manager if it works
        # (if not, it stays as it was and the log says so)
        try:
            save_config(cfg, path)
        except Exception as e:
            log.error("Salvataggio del config dopo la migrazione della password fallito: %s", e)
    elif raw.get("mqtt_password_keyring"):
        cfg["mqtt_password"] = keyring_get() or ""
    cfg.pop("mqtt_password_keyring", None)
    return cfg


# --- MQTT payload ----------------------------------------------------------

def parse_payload(raw):
    """MQTT payload -> notification dict, or None to ignore it.

    - JSON object: used as it is (``title``, ``message``, optional ``icon``, ``app``);
    - JSON text or number, or plain text that is not JSON: shown as the message;
    - empty, a list or null: ignored.
    """
    if isinstance(raw, (bytes, bytearray)):
        text = bytes(raw).decode("utf-8", errors="replace")
    else:
        text = str(raw)
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception:
        return {"message": text}
    if isinstance(data, dict):
        out = {}
        for key in ("title", "message", "app"):
            if data.get(key) is not None:
                out[key] = str(data[key])
        if isinstance(data.get("icon"), str):
            out["icon"] = data["icon"]
        if not out.get("title") and not out.get("message"):
            return None
        return out
    if isinstance(data, bool) or data is None or isinstance(data, (list,)):
        return None
    if isinstance(data, (str, int, float)):
        return {"message": str(data)}
    return None


# --- Versions and updates --------------------------------------------------

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-+.]?([0-9A-Za-z.\-]+))?$")


def parse_version(text):
    """'v1.2.0' -> ((1, 2, 0), 1, ''); '1.1.0-beta' -> ((1, 1, 0), 0, 'beta'); None if not a version.
    A pre-release (with a suffix) comes before the same version without it."""
    m = _VERSION_RE.match(str(text or "").strip())
    if not m:
        return None
    nums = tuple(int(x) for x in m.group(1).split("."))
    while len(nums) > 1 and nums[-1] == 0:
        nums = nums[:-1]
    suffix = m.group(2) or ""
    return (nums, 0 if suffix else 1, suffix)


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    return a > b


def pick_installer(assets):
    """(installer url, SHA256SUMS url) from the release assets, by exact name."""
    exe = sums = None
    for asset in assets or []:
        name = asset.get("name", "")
        if name == INSTALLER_NAME:
            exe = asset.get("browser_download_url")
        elif name == SHA256SUMS_NAME:
            sums = asset.get("browser_download_url")
    return exe, sums


def parse_sha256sums(text):
    out = {}
    for line in str(text).splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            out[parts[-1].lstrip("*")] = parts[0].lower()
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Settings form ---------------------------------------------------------

def validate_settings(fields):
    """Check the text fields of the settings window.
    Returns (values, errors): errors maps a field to a translation key."""
    values, errors = {}, {}
    broker = str(fields.get("mqtt_broker", "")).strip()
    if not broker:
        errors["mqtt_broker"] = "error_required"
    values["mqtt_broker"] = broker
    try:
        port = int(str(fields.get("mqtt_port", "")).strip())
        if not 1 <= port <= 65535:
            raise ValueError
        values["mqtt_port"] = port
    except Exception:
        errors["mqtt_port"] = "error_port"
    topic = str(fields.get("mqtt_topic", "")).strip()
    if not topic:
        errors["mqtt_topic"] = "error_required"
    values["mqtt_topic"] = topic
    try:
        duration = float(str(fields.get("duration", "")).strip().replace(",", "."))
        if not 0.5 <= duration <= 86400:
            raise ValueError
        values["duration"] = int(duration) if duration == int(duration) else duration
    except Exception:
        errors["duration"] = "error_duration"
    values["mqtt_username"] = str(fields.get("mqtt_username", ""))
    values["mqtt_password"] = str(fields.get("mqtt_password", ""))
    return values, errors
