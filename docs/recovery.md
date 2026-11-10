# Backup and recovery

Read this before Apply. Recovery protects language preferences on a running, reachable TV with working Root and native Settings Service. It is not a firmware backup or a recovery system for an unbootable TV.

## Before writing

1. Keep the existing pairing key, optional minimal identity manifest, private state and backups outside **every Git checkout**. Use a local directory accessible only to your Windows account; inherited Windows ACLs are not hardened automatically. Files are not encrypted.
2. Use the README's `$tv` argument array and run `webos-locale @tv audit`, then `webos-locale @tv backup`. Preserve the printed `.backup.json` path. Make a backup before the first change, not after it. Keep the original key separately secured: it authenticates the backup.
3. Keep TV power and LAN stable, stay available with the remote and close other controllers. Use the same private state directory for this TV. Local locks do not coordinate different computers/directories.
4. Apply makes another complete backup before initial consent. It stops if native locale and preference mirror disagree or if the known write profile does not match. No `--force` exists.

## Automatic recovery

A detached Root Node watchdog is launched through the existing HBC service. The CLI requires uid=0 and parent PID=1, a separate killed dummy child, and successful original-value restoration before requesting the target UI write. If that rehearsal fails, no target request is issued.

The watchdog owns the separate writer. A rejected response, unexpected locale/region/Root drift, writer exit, about 20 seconds without a controller response, a 25-second write-stage limit or the visual deadline triggers restoration. The limits are approximate: native RPC and process scheduling can add time. The default visual deadline is 600 seconds, adjustable to 30–900. An EOF or failed visual check also makes the CLI request restoration.

Restoration always requests the saved complete original `localeInfo`, then verifies native readback, mirror, actual uid and protected environment. It retries at most three times. A native service may refuse or normalize the original object; only a matching full readback is reported as recovered. It cannot restore an unrelated changed country/region/Root configuration; it reports that mismatch instead of writing those settings.

Evidence already delivered to Windows stays in `session-*`: exact target request, raw reply, immediate/delayed readbacks, differences and recovery events. No broad system-log collection is performed. An offline report can be produced even after failure, but a `verified` event without `accepted` is not proof of a retained configuration. A local session without a later recovery event does not prove recovery failed or succeeded while Windows was offline.

## Explicit restoration

With the same connection arguments and the actual original backup:

```powershell
webos-locale @tv restore --backup $backup
```

Type `RESTORE` after checking the prompt. The tool verifies backup authentication, model/firmware and protected baseline, creates a pre-restore backup, passes an independent recovery rehearsal and writes the complete saved original object. If restoration fails, its watchdog attempts to recover the **pre-restore** state. It never substitutes `ja-JP` or another guessed default. A successful native readback is not a visual check: inspect the restored menus with the remote.

The current release intentionally rejects changed firmware, unsupported region or a different pairing key. Do not edit the signed backup, remove validation or reuse a backup from another TV. No serial-number-based hardware attestation is claimed; pairing-key binding and the protected snapshot are the identity checks.

## If the CLI crashes or Windows disappears

- Do not restart or unplug the TV during an active trial. The detached watchdog can restore without its writer or Windows; allow time for timeout and native verification.
- When Windows is available, run a read-only Audit and compare the locale with the authenticated original backup. Inspect the private session for `rolled-back` and its complete snapshot. If the TV cannot be reached or recovery is unverified, stop and retain evidence rather than assume success.
- An abrupt Windows process exit can leave `operation.lock`. There is deliberately no automatic stale-lock deletion. Confirm the recorded local PID is no longer running **and** the TV trial/recovery has ended before manually removing only that state directory's lock. Then use read-only Audit and, if needed, the explicit Restore command. Do not launch concurrent trials through another directory to bypass the lock.
- A `recovery-error` is a stop condition. Preserve private evidence locally. If a protected field changed, this tool will not repair it. No new Root, region, engineering-menu, factory-reset or firmware action is authorized or supplied as a workaround.

After acceptance, the watchdog is disarmed, the CLI closes its temporary HTTP receiver, returns Home and requests helper exit. If completion acknowledgment is lost, the inactive helper times out after controller loss. Recovery exhaustion stops further automatic writes; a remaining helper cannot be used as an arbitrary command server and creates no TV listener or startup persistence.

Removing this Python package does not reverse a language change. Restore the desired backup first, verify the TV, and retain recovery evidence before removing local tools. Full Root/HBC uninstall, cold-boot recovery, lost-key recovery and unbootable-device recovery have **not** been verified by this project. No reboot is performed automatically.
