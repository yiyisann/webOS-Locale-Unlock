"""Pure preference construction, compatibility checks and field comparisons."""
from __future__ import annotations

import copy
import re


class LocaleError(Exception):
    """A fixed, non-sensitive error code suitable for console output."""


TAG = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,5}\Z")
PROFILE = "oled42c5pja-43.21.96-zh-Hans-CN"
CONFIG_NAMES = [
    "tv.model.languageCountrySel", "tv.model.hwSettingGroup", "tv.model.continentIndx",
    "tv.model.sysType", "tv.nyx.tvBroadcastSystem", "tv.hw.countryType",
    "tv.hw.hwoptCountryLevel", "tv.rmm.grpCodeName", "tv.rmm.codeName",
    "tv.rmm.satellite", "tv.rmm.cableDigital",
]


def validate_tag(tag):
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise LocaleError("INVALID_LOCALE_TAG")
    return tag


def validate_locale(value):
    if not isinstance(value, dict) or not isinstance(value.get("locales"), dict):
        raise LocaleError("INVALID_LOCALE_OBJECT")
    for key in ("UI", "TV", "STT"):
        validate_tag(value["locales"].get(key))
    return value


def differences(before, after, path=""):
    """JSON Pointer differences. Unknown fields are retained, never ignored."""
    if not isinstance(before, (dict, list)) and type(before) is type(after) and before == after:
        return []
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        if not any(differences(a, b) for a, b in zip(before, after)):
            return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before:
                result.append({"path": pointer, "added": True, "after": after[key]})
            elif key not in after:
                result.append({"path": pointer, "removed": True, "before": before[key]})
            else:
                result.extend(differences(before[key], after[key], pointer))
        return result
    return [{"path": path, "before": before, "after": after}]


def apply_request(original, target):
    validate_locale(original)
    validate_tag(target)
    if original["locales"]["UI"] == target:
        return None
    modified = copy.deepcopy(original)
    modified["locales"]["UI"] = target
    return {"settings": {"localeInfo": modified}}


def compare(original, actual, target, allow_stt=False):
    changes = differences(original, actual)
    allowed = {"/locales/UI"}
    if allow_stt:
        allowed.add("/locales/STT")
    unexpected = [d for d in changes if d["path"] not in allowed or
                  d.get("added") or d.get("removed") or d.get("after") != target]
    matched = isinstance(actual, dict) and actual.get("locales", {}).get("UI") == target
    return {"ok": bool(matched and not unexpected), "changes": changes, "unexpected": unexpected}


def protected_snapshot(snapshot):
    """All read-only environment data which a language transaction must preserve."""
    return {key: copy.deepcopy(snapshot[key]) for key in
            ("device", "nvram", "factory", "config", "region", "hbc", "hbcVersion", "startupHash", "initHooks")}


def validate_snapshot(snapshot):
    try:
        if type(snapshot["uid"]) is not int or snapshot["uid"] != 0 or snapshot["hbc"]["root"] is not True or snapshot["hbc"].get("failsafe"):
            raise LocaleError("HBC_ROOT_REQUIRED")
        device = snapshot["device"]
        if not all(isinstance(device.get(k), str) and device[k] for k in ("modelName", "firmwareVersion", "sdkVersion")):
            raise LocaleError("DEVICE_INFORMATION_UNAVAILABLE")
        validate_locale(snapshot["locale"])
        if snapshot["mirror"].get("localeInfo") != snapshot["locale"]:
            raise LocaleError("PREFERENCE_MIRROR_MISMATCH")
        protected_snapshot(snapshot)
    except (KeyError, TypeError, AttributeError):
        raise LocaleError("INCOMPLETE_DEVICE_SNAPSHOT") from None
    return snapshot


def check_profile(snapshot, target):
    """v0.1 allows writes only for the method's actual device/firmware/region/target."""
    validate_snapshot(snapshot)
    validate_tag(target)
    d, c, r = snapshot["device"], snapshot["config"], snapshot["region"]
    expected_config = {"tv.model.languageCountrySel": "JP", "tv.model.hwSettingGroup": "JP",
                       "tv.model.continentIndx": 6, "tv.model.sysType": "ARIB",
                       "tv.nyx.tvBroadcastSystem": "ARIB", "tv.hw.countryType": "JP",
                       "tv.rmm.grpCodeName": "JP", "tv.rmm.codeName": "JPN", "tv.hw.hwoptCountryLevel": 7,
                       "tv.rmm.satellite": True, "tv.rmm.cableDigital": False}
    if (d["modelName"] != "OLED42C5PJA.AJLQLJD" or d["firmwareVersion"] != "43.21.96" or
            d["sdkVersion"] != "11.2.0" or snapshot["hbcVersion"] != "0.7.3" or target != "zh-Hans-CN"):
        raise LocaleError("UNTESTED_WRITE_PROFILE")
    if (str(snapshot["nvram"]) != "31622" or str(snapshot["factory"]) != "31622" or
            any(type(c.get(k)) is not type(v) or c.get(k) != v for k, v in expected_config.items()) or
            any(r.get(k) != v for k, v in {"country": "JPN", "smartServiceCountryCode2": "JP",
                "smartServiceCountryCode3": "JPN", "localeCountryGroup": "langSelJP"}.items())):
        raise LocaleError("REGION_BASELINE_NOT_SUPPORTED")
    resources = snapshot.get("audit", {}).get("target", {})
    if (resources.get("defined") is not True or resources.get("settingsEntry") is not True or
            any(resources.get("catalogs", {}).get(k) is not True for k in ("settings", "home", "quicksettings"))):
        raise LocaleError("TARGET_RESOURCES_NOT_CONFIRMED")
    return PROFILE
