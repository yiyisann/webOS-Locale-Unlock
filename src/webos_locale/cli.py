"""CLI orchestration. Initial consent and visual confirmation are separate gates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys

from . import __version__
from .client import AgentSession, private_ipv4, read_key, read_manifest
from .locale import (LocaleError, apply_request, check_profile, compare, differences,
                     protected_snapshot, validate_snapshot, validate_tag)
from .storage import (load_backup, make_backup, operation_lock, private_directory,
                      public_report, write_json)


def parser():
    p = argparse.ArgumentParser(prog="webos-locale", description="Unlock the language, not the region.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--host", help="Private IPv4 of the already-rooted TV")
    p.add_argument("--key-file", type=Path, help="Existing SSAP pairing token file; never printed")
    p.add_argument("--manifest-file", type=Path, help="Optional existing pairing identity manifest")
    p.add_argument("--state-dir", type=Path, help="Private directory OUTSIDE every Git checkout")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("audit", "backup"):
        command = sub.add_parser(name)
        command.add_argument("--ui", default="zh-Hans-CN", type=validate_tag)
    command = sub.add_parser("apply")
    command.add_argument("--ui", required=True, type=validate_tag)
    command.add_argument("--allow-stt-sync", action="store_true", help="Explicitly allow STT to follow the requested UI tag")
    command.add_argument("--yes", action="store_true", help="Confirm initial write only; DOES NOT replace visual checks")
    command.add_argument("--visual-timeout", type=int, default=600, help="30–900 seconds before autonomous rollback")
    command = sub.add_parser("verify")
    command.add_argument("--backup", required=True, type=Path)
    command.add_argument("--ui", type=validate_tag)
    command.add_argument("--allow-stt-sync", action="store_true")
    command = sub.add_parser("restore")
    command.add_argument("--backup", required=True, type=Path)
    command.add_argument("--yes", action="store_true")
    command = sub.add_parser("report", help="Offline allowlisted report from a private session")
    command.add_argument("--session", required=True, type=Path)
    command.add_argument("--output", type=Path)
    return p


def confirm(text, word, input_fn):
    try:
        answer = input_fn(text).strip()
    except (EOFError, KeyboardInterrupt):
        raise LocaleError("CONFIRMATION_NOT_RECEIVED") from None
    if answer != word:
        raise LocaleError("CONFIRMATION_DECLINED")


def fresh(factory, connection, target):
    with factory(**connection, operation="audit", target=target) as session:
        event = session.wait({"audit"})
        return validate_snapshot(event["data"]["snapshot"])


def same_environment(before, current):
    if protected_snapshot(before) != protected_snapshot(current):
        raise LocaleError("DEVICE_FIRMWARE_OR_PROTECTED_ENVIRONMENT_CHANGED")


def backup_file(directory, snapshot, key, intent=None, prefix="locale"):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / (prefix + "-" + stamp + "-" + secrets.token_hex(3) + ".backup.json")
    write_json(path, make_backup(snapshot, key, intent))
    return path


def show_report(report, output):
    print(json.dumps(report, ensure_ascii=False, indent=2), file=output)


def visual_checks(session, input_fn, output):
    result = {}
    for stage, app in (("Home", "com.webos.app.home"), ("Quick Settings", "com.webos.app.quicksettings"),
                       ("Full Settings", "com.palm.app.settings")):
        session.launch(app)
        try:
            reply = input_fn(stage + " shows the target language and is usable? Type yes, no, or loading: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise LocaleError("VISUAL_CONFIRMATION_NOT_RECEIVED") from None
        if reply == "loading" and stage == "Full Settings":
            print("Known profile limitation: the Menu Language label can remain Loading. Do not accept black screens, stuck menus or other faults.", file=output)
            confirm("If ONLY that known label is affected and the menus work, type ACCEPT_LOADING: ", "ACCEPT_LOADING", input_fn)
            result["knownLabelLimitationAccepted"] = True
        elif reply != "yes":
            raise LocaleError("VISUAL_CHECK_FAILED")
        result[stage] = True
    confirm("Check original HDMI, picture, sound, network and broadcasts you use; return Home. Type yes only if normal: ", "yes", input_fn)
    result["originalFunctionsConfirmed"] = True
    session.launch("com.webos.app.home")
    return result


def transaction(factory, connection, snapshot, *, target, allow_stt, restore_locale=None,
                input_fn=input, output=sys.stdout, seconds=600):
    operation = "restore" if restore_locale is not None else "apply"
    with factory(**connection, operation=operation, target=target, baseline=snapshot,
                 restore_locale=restore_locale, allow_stt=allow_stt, visual_seconds=seconds) as session:
        ready = session.wait({"ready"})["data"]
        if (type(ready.get("uid")) is not int or ready["uid"] != 0 or ready.get("watchdogParentPid") != 1 or
                type(ready.get("watchdogPid")) is not int or ready["watchdogPid"] <= 1):
            raise LocaleError("INDEPENDENT_WATCHDOG_NOT_CONFIRMED")
        session.launch("com.webos.app.home")
        session.command("probe")
        probe = session.wait({"probe-passed"}, 25)["data"]
        started = session.wait({"probe-started"})["data"]
        exited = session.wait({"probe-exited"})["data"]
        if (started.get("watchdogPid") != ready["watchdogPid"] or started.get("watchdogParentPid") != 1 or
                started.get("uid") != 0 or type(started.get("probePid")) is not int or started["probePid"] <= 1 or
                started["probePid"] == ready["watchdogPid"] or exited.get("signal") != "SIGKILL"):
            raise LocaleError("INDEPENDENT_RECOVERY_PROBE_FAILED")
        restored_probe = validate_snapshot(probe["snapshot"])
        same_environment(snapshot, restored_probe)
        if restored_probe["locale"] != snapshot["locale"]:
            raise LocaleError("RECOVERY_PROBE_LOCALE_MISMATCH")
        session.command("apply")
        result = session.wait({"verified", "rolled-back"}, 35)
        if result["name"] == "rolled-back":
            raise LocaleError("WRITE_MISMATCH_RESTORED")
        observed = validate_snapshot(result["data"]["snapshot"])
        same_environment(snapshot, observed)
        if operation == "apply":
            verification = compare(snapshot["locale"], observed["locale"], target, allow_stt)
            if not verification["ok"]:
                raise LocaleError("UNEXPECTED_LANGUAGE_FIELDS")
            visual = visual_checks(session, input_fn, output)
        else:
            if observed["locale"] != restore_locale:
                raise LocaleError("RESTORE_READBACK_MISMATCH")
            verification = {"ok": True, "changes": differences(snapshot["locale"], restore_locale), "unexpected": []}
            visual = None
        write_json(session.run_dir / "owner-confirmation.private.json", {"visual": visual, "operation": operation})
        session.command("accept")
        accepted = validate_snapshot(session.wait({"accepted"}, 20)["data"]["snapshot"])
        same_environment(snapshot, accepted)
        if operation == "apply" and not compare(snapshot["locale"], accepted["locale"], target, allow_stt)["ok"]:
            # The native guard validates the same rule before accepting.
            raise LocaleError("FINAL_SCOPE_VERIFICATION_FAILED")
        if operation == "restore" and accepted["locale"] != restore_locale:
            raise LocaleError("FINAL_RESTORE_VERIFICATION_FAILED")
        report = public_report(accepted, outcome="RESTORED" if operation == "restore" else "APPLIED_VISUALLY_CONFIRMED",
                               verification=verification, visual=visual, audit_info=snapshot.get("audit", {}))
        report["knownLabelLimitationAccepted"] = bool(visual and visual.get("knownLabelLimitationAccepted"))
        write_json(session.run_dir / "public-report.json", report)
        return report


def offline_report(args, output):
    try:
        events = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.session.glob("event-*.private.json"))]
        candidates = [e for e in events if e.get("name") in {"audit", "accepted", "rolled-back", "verified"} and
                      isinstance(e.get("data", {}).get("snapshot"), dict)]
        if not candidates:
            raise LocaleError("NO_REPORTABLE_SNAPSHOT")
        event = candidates[-1]
        owner_path = args.session / "owner-confirmation.private.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8")) if owner_path.exists() else {}
        audit = next((e.get("data", {}).get("snapshot", {}).get("audit") for e in events
                      if e.get("data", {}).get("snapshot", {}).get("audit")), {})
        report = public_report(event["data"]["snapshot"], outcome={"audit": "AUDIT", "accepted": "ACCEPTED", "rolled-back": "RESTORED", "verified": "NOT_ACCEPTED"}[event["name"]],
                               visual=owner.get("visual") if event["name"] == "accepted" else None, audit_info=audit)
        if args.output:
            write_json(args.output, report)
        show_report(report, output)
    except (OSError, ValueError, KeyError, TypeError):
        raise LocaleError("PRIVATE_SESSION_UNREADABLE") from None


def run(args, *, factory=AgentSession, input_fn=input, output=sys.stdout):
    if args.command == "report":
        offline_report(args, output)
        return 0
    if not args.host or not args.key_file or not args.state_dir:
        raise LocaleError("HOST_KEY_FILE_AND_PRIVATE_STATE_DIR_REQUIRED")
    host, key = private_ipv4(args.host), read_key(args.key_file)
    directory = private_directory(args.state_dir)
    manifest = read_manifest(args.manifest_file)
    connection = dict(host=host, key=key, manifest=manifest, state_dir=directory)
    with operation_lock(directory):
        target = getattr(args, "ui", None) or "zh-Hans-CN"
        snapshot = fresh(factory, connection, target)
        if args.command == "audit":
            show_report(public_report(snapshot), output)
            return 0
        if args.command == "backup":
            path = backup_file(directory, snapshot, key)
            print("Private signed backup saved: " + str(path), file=output)
            return 0
        if args.command == "verify":
            backup = load_backup(args.backup, key)
            same_environment(backup["snapshot"], snapshot)
            intent = backup.get("intent") or {}
            target = args.ui or intent.get("target") or backup["snapshot"]["locale"]["locales"]["UI"]
            verification = compare(backup["snapshot"]["locale"], snapshot["locale"], target,
                                   args.allow_stt_sync or bool(intent.get("allowSTT")))
            show_report(public_report(snapshot, outcome="VERIFIED" if verification["ok"] else "MISMATCH",
                                      verification=verification), output)
            return 0 if verification["ok"] else 1
        check_profile(snapshot, target)
        if args.command == "restore":
            stored = load_backup(args.backup, key)
            same_environment(stored["snapshot"], snapshot)
            desired = stored["snapshot"]["locale"]
            if desired == snapshot["locale"]:
                show_report(public_report(snapshot, outcome="NO_CHANGE"), output)
                return 0
            print("Restore the complete original localeInfo from the authenticated backup. Region is never written.", file=output)
            if not args.yes:
                confirm("Type RESTORE to continue: ", "RESTORE", input_fn)
            path = backup_file(directory, snapshot, key, prefix="before-restore")
            print("Pre-restore recovery backup: " + str(path), file=output)
            report = transaction(factory, connection, snapshot, target=target, allow_stt=False,
                                 restore_locale=desired, input_fn=input_fn, output=output)
        else:
            if not 30 <= args.visual_timeout <= 900:
                raise LocaleError("VISUAL_TIMEOUT_MUST_BE_30_TO_900_SECONDS")
            if apply_request(snapshot["locale"], args.ui) is None:
                show_report(public_report(snapshot, outcome="NO_CHANGE"), output)
                return 0
            if not args.allow_stt_sync:
                raise LocaleError("THIS_PROFILE_REQUIRES_EXPLICIT_ALLOW_STT_SYNC")
            print("Current UI: " + snapshot["locale"]["locales"]["UI"] + "\nTarget UI: " + args.ui +
                  "\nAllowed linkage: STT may follow UI. NLP, TV OSD, keyboards, region and all other fields stay unchanged."
                  "\nVoice recognition language can change. Menu Language may show Loading; translation may be incomplete."
                  "\nAn independent TV watchdog must pass a real original-value recovery rehearsal before the one UI write.", file=output)
            path = backup_file(directory, snapshot, key, {"target": args.ui, "allowSTT": True})
            print("Restore with the restore command and this private backup: " + str(path), file=output)
            if not args.yes:
                confirm("Type APPLY to authorize one UI request and the disclosed STT linkage: ", "APPLY", input_fn)
            report = transaction(factory, connection, snapshot, target=args.ui, allow_stt=True,
                                 input_fn=input_fn, output=output, seconds=args.visual_timeout)
        show_report(report, output)
        return 0


def main(argv=None):
    try:
        return run(parser().parse_args(argv))
    except LocaleError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("INTERRUPTED; inspect the private session for recovery confirmation.", file=sys.stderr)
        return 2
    except Exception:
        # Do not echo library exception text containing addresses, paths or credentials.
        print("OPERATION_FAILED; retain private state and follow docs/recovery.md.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
