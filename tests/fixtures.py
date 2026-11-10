"""Hand-built data. Never a captured device backup or response."""
import copy


def snapshot(ui="en-JP"):
    locale = {"locales": {"UI": ui, "TV": "ja-JP", "STT": ui, "FMT": "ja-JP",
                          "NLP": "ja-JP", "AUD": "ja-JP", "AUD2": "en-US"},
              "keyboards": ["en", "ja"], "clock": "locale", "timezone": "",
              "syntheticExtension": {"retain": [1, True, "fixture"]}}
    return {"uid": 0,
            "device": {"modelName": "OLED42C5PJA.AJLQLJD", "firmwareVersion": "43.21.96", "sdkVersion": "11.2.0"},
            "locale": locale, "mirror": {"localeInfo": copy.deepcopy(locale)},
            "nvram": "31622", "factory": "31622",
            "config": {"tv.model.languageCountrySel": "JP", "tv.model.hwSettingGroup": "JP",
                       "tv.model.continentIndx": 6, "tv.model.sysType": "ARIB", "tv.nyx.tvBroadcastSystem": "ARIB",
                       "tv.hw.countryType": "JP", "tv.hw.hwoptCountryLevel": 7,
                       "tv.rmm.grpCodeName": "JP", "tv.rmm.codeName": "JPN",
                       "tv.rmm.satellite": True, "tv.rmm.cableDigital": False},
            "region": {"country": "JPN", "smartServiceCountryCode2": "JP", "smartServiceCountryCode3": "JPN", "localeCountryGroup": "langSelJP"},
            "hbc": {"returnValue": True, "root": True, "failsafe": False}, "hbcVersion": "0.7.3",
            "startupHash": "synthetic-startup-hash", "initHooks": [],
            "audit": {"requestedTag": "zh-Hans-CN", "selectable": ["ja-JP", "en-JP"], "target": {"defined": True, "settingsEntry": True,
                       "catalogs": {"home": True, "settings": True, "quicksettings": True}}}}


def changed(before):
    result = copy.deepcopy(before)
    result["locale"]["locales"].update(UI="zh-Hans-CN", STT="zh-Hans-CN")
    result["mirror"]["localeInfo"] = copy.deepcopy(result["locale"])
    return result
