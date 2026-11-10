import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from fixtures import snapshot, changed
from webos_locale import cli
from webos_locale.locale import LocaleError
from webos_locale.storage import load_backup, make_backup, write_json


class FakeSession:
    def __init__(self, owner, **kwargs):
        self.owner, self.kwargs = owner, kwargs
        self.events, self.commands, self.launched = [], [], []
        self.run_dir = Path(tempfile.mkdtemp(prefix="fake-session-", dir=kwargs["state_dir"]))
        owner.sessions.append(self)

    def add(self, name, data):
        event = {"seq": len(self.events) + 1, "name": name, "data": data}
        self.events.append(event)
        return event

    def __enter__(self):
        if self.kwargs["operation"] == "audit": self.add("audit", {"snapshot": copy.deepcopy(self.owner.before)})
        else: self.add("ready", {"snapshot": copy.deepcopy(self.owner.before), "uid": 0, "watchdogPid": 400, "watchdogParentPid": self.owner.parent})
        return self

    def __exit__(self, kind, *_):
        if kind and "apply" in self.commands and "accept" not in self.commands:
            self.commands.append("rollback")

    def wait(self, names, *args, **kwargs):
        for event in self.events:
            if event["name"] in names: return event
        raise LocaleError("SYNTHETIC_EVENT_NOT_FOUND")

    def command(self, action):
        self.commands.append(action)
        if action == "probe":
            self.add("probe-started", {"uid": 0, "watchdogPid": 400, "watchdogParentPid": 1, "probePid": 401})
            self.add("probe-exited", {"signal": "SIGKILL"})
            self.add("probe-passed", {"snapshot": copy.deepcopy(self.owner.before)})
        elif action == "apply":
            after = changed(self.owner.before)
            if self.kwargs["operation"] == "restore":
                after["locale"] = copy.deepcopy(self.kwargs["restore_locale"])
                after["mirror"]["localeInfo"] = copy.deepcopy(after["locale"])
            if self.owner.mismatch: after["locale"]["locales"]["TV"] = "zh-Hans-CN"
            self.after = after
            self.add("rolled-back" if self.owner.rejected else "verified", {"snapshot": after})
        elif action == "accept": self.add("accepted", {"snapshot": self.after})

    def launch(self, app): self.launched.append(app)


class Factory:
    def __init__(self, before=None, *, parent=1, rejected=False, mismatch=False):
        self.before = before or snapshot(); self.sessions = []
        self.parent, self.rejected, self.mismatch = parent, rejected, mismatch

    def __call__(self, **kwargs): return FakeSession(self, **kwargs)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.key = self.root / "synthetic.key"; self.key.write_text("SYNTHETIC_TEST_KEY")
        self.base = ["--host", "10.23.45.67", "--key-file", str(self.key), "--state-dir", str(self.root)]
        self.output = io.StringIO()

    def tearDown(self): self.temp.cleanup()

    def run_cli(self, argv, factory, answers=()):
        iterator = iter(answers)
        def ask(_):
            try: return next(iterator)
            except StopIteration: raise EOFError()
        return cli.run(cli.parser().parse_args(self.base + argv), factory=factory, input_fn=ask, output=self.output)

    def test_audit_and_backup_never_send_mutation(self):
        for command in ("audit", "backup"):
            f = Factory()
            self.assertEqual(self.run_cli([command], f), 0)
            self.assertFalse(any(s.commands for s in f.sessions))
        saved = next(self.root.glob("*.backup.json"))
        self.assertEqual(load_backup(saved, "SYNTHETIC_TEST_KEY")["snapshot"]["locale"]["locales"]["UI"], "en-JP")

    def test_declined_apply_stops_before_writer(self):
        f = Factory()
        with self.assertRaisesRegex(LocaleError, "CONFIRMATION_DECLINED"):
            self.run_cli(["apply", "--ui", "zh-Hans-CN", "--allow-stt-sync"], f, ["NO"])
        self.assertEqual(len(f.sessions), 1)
        self.assertTrue(list(self.root.glob("*.backup.json")))

    def test_success_needs_visual_confirmation_even_yes(self):
        f = Factory()
        self.assertEqual(self.run_cli(["apply", "--ui", "zh-Hans-CN", "--allow-stt-sync", "--yes"], f, ["yes"] * 4), 0)
        self.assertEqual(f.sessions[-1].commands, ["probe", "apply", "accept"])
        report = json.loads((f.sessions[-1].run_dir / "public-report.json").read_text())
        self.assertTrue(report["visualConfirmed"])
        self.assertEqual(report["verification"]["changedFields"], ["/locales/STT", "/locales/UI"])

    def test_known_label_only_may_be_explicitly_accepted(self):
        f = Factory()
        self.run_cli(["apply", "--ui", "zh-Hans-CN", "--allow-stt-sync", "--yes"], f,
                     ["yes", "yes", "loading", "ACCEPT_LOADING", "yes"])
        report = json.loads((f.sessions[-1].run_dir / "public-report.json").read_text())
        self.assertTrue(report["knownLabelLimitationAccepted"])

    def test_eof_or_unknown_change_restores_without_accept(self):
        for mismatch in (False, True):
            f = Factory(mismatch=mismatch)
            with self.assertRaises(LocaleError):
                self.run_cli(["apply", "--ui", "zh-Hans-CN", "--allow-stt-sync", "--yes"], f)
            self.assertIn("rollback", f.sessions[-1].commands)
            self.assertNotIn("accept", f.sessions[-1].commands)

    def test_rejected_native_write_not_claimed_success(self):
        f = Factory(rejected=True)
        with self.assertRaisesRegex(LocaleError, "WRITE_MISMATCH_RESTORED"):
            self.run_cli(["apply", "--ui", "zh-Hans-CN", "--allow-stt-sync", "--yes"], f)
        self.assertNotIn("accept", f.sessions[-1].commands)

    def test_nonindependent_guard_stops_before_probe(self):
        f = Factory(parent=42)
        with self.assertRaisesRegex(LocaleError, "INDEPENDENT_WATCHDOG_NOT_CONFIRMED"):
            self.run_cli(["apply", "--ui", "zh-Hans-CN", "--allow-stt-sync", "--yes"], f)
        self.assertEqual(f.sessions[-1].commands, [])

    def test_idempotent_target_does_not_run_writer(self):
        f = Factory(changed(snapshot()))
        self.assertEqual(self.run_cli(["apply", "--ui", "zh-Hans-CN", "--allow-stt-sync", "--yes"], f), 0)
        self.assertEqual(len(f.sessions), 1)

    def test_incompatible_firmware_stops_after_read_only_audit(self):
        f = Factory(); f.before["device"]["firmwareVersion"] = "99.00.00"
        with self.assertRaisesRegex(LocaleError, "UNTESTED_WRITE_PROFILE"):
            self.run_cli(["apply", "--ui", "zh-Hans-CN", "--allow-stt-sync", "--yes"], f)
        self.assertEqual(len(f.sessions), 1)
        self.assertEqual(f.sessions[0].commands, [])

    def test_restore_uses_non_japanese_original_object(self):
        original = snapshot("fr-FR")
        path = self.root / "original.backup.json"
        write_json(path, make_backup(original, "SYNTHETIC_TEST_KEY"))
        f = Factory(changed(original))
        self.run_cli(["restore", "--backup", str(path), "--yes"], f)
        self.assertEqual(f.sessions[-1].kwargs["restore_locale"], original["locale"])
        self.assertEqual(f.sessions[-1].commands, ["probe", "apply", "accept"])

    def test_verify_is_read_only_and_offline_report_is_allowlisted(self):
        original = snapshot(); path = self.root / "original.backup.json"
        write_json(path, make_backup(original, "SYNTHETIC_TEST_KEY", {"target": "zh-Hans-CN", "allowSTT": True}))
        f = Factory(changed(original))
        self.assertEqual(self.run_cli(["verify", "--backup", str(path)], f), 0)
        self.assertEqual(f.sessions[-1].commands, [])
        session = self.root / "synthetic-session"; session.mkdir()
        write_json(session / "event-0001.private.json", {"name": "accepted", "data": {"snapshot": changed(original), "secret": "SYNTHETIC_PRIVATE_SENTINEL"}})
        stream = io.StringIO()
        cli.run(cli.parser().parse_args(["report", "--session", str(session)]), output=stream)
        self.assertNotIn("SYNTHETIC_PRIVATE_SENTINEL", stream.getvalue())
        self.assertFalse(json.loads(stream.getvalue())["visualConfirmed"])


if __name__ == "__main__": unittest.main()
