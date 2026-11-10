"""Private, signed backups; deliberately small allowlisted public reports."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path

from .locale import LocaleError, TAG, check_profile, validate_snapshot


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def private_directory(path):
    path = Path(path).expanduser().resolve()
    if any((p / ".git").exists() for p in (path, *path.parents)):
        raise LocaleError("STATE_DIRECTORY_MUST_BE_OUTSIDE_GIT")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def write_json(path, value, exclusive=True):
    path = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise LocaleError("OUTPUT_ALREADY_EXISTS") from None


def _mac(key, data):
    return hmac.new(key.encode(), b"webos-locale-backup/v1\0" + canonical(data), hashlib.sha256).hexdigest()


def make_backup(snapshot, key, intent=None):
    validate_snapshot(snapshot)
    data = {"schema": 1, "createdUTC": datetime.now(timezone.utc).isoformat(),
            "snapshot": snapshot, "intent": intent,
            "binding": hmac.new(key.encode(), b"webos-locale-device/v1", hashlib.sha256).hexdigest()}
    return {"data": data, "signature": _mac(key, data)}


def load_backup(path, key):
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        data, signature = document["data"], document["signature"]
        if data["schema"] != 1 or not hmac.compare_digest(signature, _mac(key, data)):
            raise LocaleError("BACKUP_AUTHENTICATION_FAILED")
        validate_snapshot(data["snapshot"])
        return data
    except (ValueError, KeyError, TypeError, OSError):
        raise LocaleError("INVALID_OR_UNREADABLE_BACKUP") from None


def safe_tag(value):
    return value if isinstance(value, str) and TAG.fullmatch(value) else "unavailable"


def public_report(snapshot, *, outcome="AUDIT", verification=None, visual=None, audit_info=None):
    """Never copy arbitrary device strings, exception text, paths, IDs or raw responses."""
    locales = snapshot.get("locale", {}).get("locales", {})
    audit = snapshot.get("audit", {}) if audit_info is None else audit_info
    target = audit.get("target", {})
    requested = safe_tag(audit.get("requestedTag"))
    try:
        check_profile(dict(snapshot, audit=audit), requested)
        profile_known = True
    except (LocaleError, KeyError, TypeError, AttributeError):
        profile_known = False
    report = {"schema": 1, "toolVersion": "0.1.0", "outcome": outcome,
              "locales": {k: safe_tag(locales.get(k)) for k in ("UI", "TV", "STT", "FMT", "NLP", "AUD", "AUD2")},
              "uid0": snapshot.get("uid") == 0, "hbcRoot": snapshot.get("hbc", {}).get("root") is True,
              "selectableLanguages": [safe_tag(t) for t in audit.get("selectable", []) if isinstance(t, str) and TAG.fullmatch(t)],
              "requestedUI": requested, "knownWriteProfile": profile_known,
              "targetSelectable": requested != "unavailable" and requested in audit.get("selectable", []),
              "resourceChecksAt": "INITIAL_AUDIT",
              "resourceChecks": {"defined": target.get("defined") is True, "settingsEntry": target.get("settingsEntry") is True,
                  "catalogs": {k: target.get("catalogs", {}).get(k) is True for k in ("home", "quicksettings", "settings")},
                  "simplifiedFont": target.get("simplifiedFont") is True},
              "visualConfirmed": bool(visual), "rebootTested": False}
    if verification is not None:
        known = {"/locales/" + k for k in ("UI", "TV", "STT", "FMT", "NLP", "AUD", "AUD2")}
        report["verification"] = {"ok": bool(verification["ok"]),
            "changedFields": sorted({d["path"] if d["path"] in known else "<other-field>" for d in verification["changes"]}),
            "unexpectedFieldCount": len(verification["unexpected"])}
    return report


@contextmanager
def operation_lock(directory):
    path = Path(directory) / "operation.lock"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise LocaleError("ANOTHER_OPERATION_OR_STALE_LOCK") from None
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)
