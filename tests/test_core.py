import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from fixtures import snapshot, changed
from webos_locale.locale import (LocaleError, apply_request, check_profile, compare,
                                differences, validate_locale, validate_snapshot, validate_tag)
from webos_locale.storage import (load_backup, make_backup, operation_lock,
                                 private_directory, public_report, write_json)


class LocaleTests(unittest.TestCase):
    def test_parse_device_and_locale(self):
        s = snapshot()
        self.assertIs(validate_snapshot(s), s)
        for field in ("modelName", "firmwareVersion", "sdkVersion"):
            bad = copy.deepcopy(s)
            del bad["device"][field]
            with self.assertRaises(LocaleError):
                validate_snapshot(bad)
        for uid in (1, False, "0"):
            bad = copy.deepcopy(s); bad["uid"] = uid
            with self.assertRaises(LocaleError): validate_snapshot(bad)
        bad = copy.deepcopy(s); bad["mirror"]["localeInfo"]["clock"] = "other"
        with self.assertRaises(LocaleError): validate_snapshot(bad)
        with self.assertRaises(LocaleError): validate_locale({"locales": {"UI": "en-JP"}})

    def test_ui_request_changes_one_field_and_keeps_extensions(self):
        before = snapshot("fr-FR")["locale"]
        saved = copy.deepcopy(before)
        body = apply_request(before, "zh-Hans-CN")
        self.assertEqual(before, saved)
        self.assertEqual([d["path"] for d in differences(before, body["settings"]["localeInfo"])], ["/locales/UI"])
        self.assertEqual(body["settings"]["localeInfo"]["locales"]["STT"], "fr-FR")
        self.assertIsNone(apply_request(before, "fr-FR"))

    def test_stt_requires_opt_in(self):
        before = snapshot(); after = changed(before)
        self.assertFalse(compare(before["locale"], after["locale"], "zh-Hans-CN")["ok"])
        self.assertTrue(compare(before["locale"], after["locale"], "zh-Hans-CN", True)["ok"])
        after["locale"]["locales"]["STT"] = "zh-TW"
        self.assertFalse(compare(before["locale"], after["locale"], "zh-Hans-CN", True)["ok"])

    def test_unknown_fields_and_type_changes_are_rejected(self):
        before = snapshot()
        for mutate in (lambda x: x["locales"].update(TV="zh-Hans-CN"),
                       lambda x: x["locales"].update(FMT="zh-Hans-CN"),
                       lambda x: x.update(keyboards=["zh"]), lambda x: x.update(new=True),
                       lambda x: x.pop("clock"), lambda x: x["syntheticExtension"].update(retain=[1, 1, "fixture"])):
            actual = changed(before)["locale"]; mutate(actual)
            self.assertFalse(compare(before["locale"], actual, "zh-Hans-CN", True)["ok"])
        self.assertEqual(differences({"a/b": 1}, {"a/b": 2})[0]["path"], "/a~1b")

    def test_only_verified_write_profile(self):
        self.assertTrue(check_profile(snapshot(), "zh-Hans-CN"))
        for key, value in (("modelName", "SYNTHETIC-OTHER"), ("firmwareVersion", "99.00.00")):
            s = snapshot(); s["device"][key] = value
            with self.assertRaises(LocaleError): check_profile(s, "zh-Hans-CN")
        for mutate in (lambda s: s.update(nvram="1"), lambda s: s["region"].update(country="USA"),
                       lambda s: s["audit"]["target"].update(catalogs={}),
                       lambda s: s["audit"]["target"]["catalogs"].update(home=False)):
            s = snapshot(); mutate(s)
            with self.assertRaises(LocaleError): check_profile(s, "zh-Hans-CN")
        with self.assertRaises(LocaleError): check_profile(snapshot(), "zh-TW")

    def test_tag_injection_rejected(self):
        for tag in (None, "x\nEOF", "zh_CN", "zh-CN';exit", "a" * 100):
            with self.assertRaises(LocaleError): validate_tag(tag)


class StorageTests(unittest.TestCase):
    def test_full_backup_authenticated_and_not_assumed_japanese(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "test.backup.json"
            s = snapshot("fr-FR")
            write_json(p, make_backup(s, "SYNTHETIC_TEST_KEY"))
            self.assertEqual(load_backup(p, "SYNTHETIC_TEST_KEY")["snapshot"], s)
            with self.assertRaises(LocaleError): load_backup(p, "SYNTHETIC_WRONG_KEY")
            data = json.loads(p.read_text()); data["data"]["snapshot"]["locale"]["clock"] = "tampered"
            p.write_text(json.dumps(data))
            with self.assertRaises(LocaleError): load_backup(p, "SYNTHETIC_TEST_KEY")

    def test_private_output_exclusive_and_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp); write_json(p / "one.json", {})
            with self.assertRaises(LocaleError): write_json(p / "one.json", {})
            with operation_lock(p):
                with self.assertRaises(LocaleError):
                    with operation_lock(p): pass
            self.assertFalse((p / "operation.lock").exists())
            (p / ".git").write_text("synthetic worktree marker")
            with self.assertRaises(LocaleError): private_directory(p / "state")

    def test_public_report_drops_private_values_paths_and_unknown_fields(self):
        s = snapshot()
        sentinel = "SYNTHETIC_PRIVATE_SENTINEL"
        s.update(serial=sentinel, pairingKey=sentinel, host="10.23.45.67", windowsPath=sentinel)
        s["device"].update(serial=sentinel)
        s["audit"]["selectable"] += [None, {"private": sentinel}, sentinel + "/secret"]
        s["locale"]["locales"]["AUD"] = sentinel + "/secret"
        verification = {"ok": False, "changes": [{"path": "/secret/" + sentinel, "before": sentinel}], "unexpected": [{}]}
        report = public_report(s, verification=verification)
        text = json.dumps(report)
        self.assertNotIn(sentinel, text)
        self.assertNotIn("10.23.45.67", text)
        self.assertEqual(report["verification"]["changedFields"], ["<other-field>"])
        self.assertFalse(report["rebootTested"])


if __name__ == "__main__": unittest.main()
