# webOS Locale Unlock

Unlock hidden UI languages on rooted LG webOS TVs without changing the TV's region.

**Unlock the language, not the region.**

[简体中文](README.zh-CN.md) · [Method](docs/methodology.md) · [Compatibility](docs/compatibility.md) · [Recovery](docs/recovery.md) · [Security](SECURITY.md)

v0.1.0 is an experimental CLI for auditing languages, backing up complete language preferences, applying a narrowly scoped UI preference, verifying changes and restoring the original configuration. It requires an **already-rooted** TV and Homebrew Channel. It does not install Root, change region or unlock engineering menus.

**Evidence matters:** the underlying method worked on one Japanese OLED42C5PJA, firmware 43.21.96, webOS 26. This newly packaged client has offline tests, but has **not yet had its own end-to-end TV acceptance test**. No TV was changed while building this version. Other devices and languages are unverified; writes are deliberately restricted to that exact model, firmware, Japan baseline and `zh-Hans-CN` target.

## Why a language can be hidden

Installed translations and the selectable language list are separate things. On the observed TV, Chinese resources were installed, while `langSelJP` exposed only Japanese and English. A native UI preference selected those existing translations without changing the country or hardware configuration. Resource presence alone does not establish that another TV supports the same behavior.

The tool preserves the complete current `localeInfo`, changes only `locales.UI` in its request, and compares every field after writing. Explicit `--allow-stt-sync` permits only the observed STT synchronization to the same target. It never requests changes to TV OSD, keyboards, format, audio, NLP, country, service country, language group or NVRAM.

## Observed device and limitations

| Item | Original method's real-device result |
| --- | --- |
| Device | LG OLED42C5PJA.AJLQLJD, firmware 43.21.96, webOS 26 / internal 11.2.0 |
| Prerequisites | Root, Homebrew Channel 0.7.3 |
| UI | Japanese → Simplified Chinese in Home, Quick Settings and full Settings; owner confirmed |
| Linked field | STT followed UI to `zh-Hans-CN`; NLP stayed Japanese |
| Preserved | Area 31622; JP / JP / 6; JPN / JP / langSelJP; Root/HBC |
| Owner functional checks | HDMI, picture, sound, network and original Japanese broadcasts normal |
| Unchanged | TV OSD Japanese; keyboards Japanese/English |
| Known issue | Menu Language label remains **Loading / 正在加载**; some translations may fall back |
| Not tested | Chinese persistence after restart/cold boot, voice accuracy, other models; new CLI on a TV |

This is partial UI localization, not complete Chinese localization. Japanese voice behavior is not guaranteed when STT changes. The known Loading label may be accepted explicitly only if the menus remain usable; other faults require rollback.

## Requirements and installation

- Windows with Python 3.10+; source tests have been run with Python 3.14.
- An existing working SSAP pairing key with app-launch permission. This version neither creates nor saves new pairings.
- Existing Root/HBC exec access, Tiny Browser, `/usr/bin/node`, `/usr/bin/setsid` and `/usr/bin/luna-send` on the TV. No TV tools are installed.
- A trusted private IPv4 LAN. The TV must reach a temporary Windows HTTP listener. No port forwarding or public exposure.
- One runtime dependency: [websocket-client](https://github.com/websocket-client/websocket-client), Apache-2.0, for WebSocket framing. Everything else on Windows uses the Python standard library.

After reviewing the source, install from your checkout:

```powershell
py -m pip install .
webos-locale --help
```

This installs the declared dependency and build requirements. Installation and wheel building were not performed during this version's local review. No third-party SSAP or exploit code is bundled. See [security and trust assumptions](SECURITY.md).

## Use

The IP below is fictional. Replace it with your own TV's private address. Keep an existing pairing key in `ssap.key`, outside this repository. Keep the entire private state directory local and access-controlled; backups are not encrypted.

```powershell
$state = Join-Path $env:LOCALAPPDATA 'webos-locale-private'
$tv = @('--host', '10.23.45.67', '--key-file', "$state\ssap.key", '--state-dir', $state)

webos-locale @tv audit --ui zh-Hans-CN
webos-locale @tv backup
```

These commands do not write TV preferences. They temporarily open a bootstrap page through SSAP and the existing HBC exec service, then return Home. They save scoped private evidence, not system-wide logs or database dumps. A missing native path or denied API stops the operation; the tool does not change ACLs.

If the existing pairing needs its original identity, append `--manifest-file` and the path to its private, minimal JSON manifest to `$tv`. Only the documented app-launch permission subset and unsigned manifest fields are accepted. The new SSAP adapter's pairing interoperability still needs device acceptance; do not approve an unexpected pairing prompt to work around a failure.

On the supported profile, after reviewing audit results:

```powershell
webos-locale @tv apply --ui zh-Hans-CN --allow-stt-sync
```

The CLI displays the current/target UI, STT impact and recovery backup, then requires `APPLY`. Before the target request, it verifies a detached Root watchdog and rehearses recovery by killing a dummy child and writing the **saved original value** back. That rehearsal is a real same-value preference write. Recovery writes are separate from the single target-language request.

The watchdog owns a separate writer process. Request, raw response, immediate/delayed readbacks and exact differences must be saved to Windows before progressing. Unknown changes, rejected writes, worker failure, controller loss or timeout trigger full original-locale restoration. No confirmation within 600 seconds (configurable 30–900) restores the original configuration. `--yes` skips only initial consent, **never** visual checks.

Use the remote to confirm Home, Quick Settings, Settings and original TV functions. Only then does the CLI ask the watchdog to retain the change. It does not restart the TV. Reapplying the current target is a no-op.

## Verify, restore and report

Use the actual backup path printed by Apply; filenames below are placeholders. Pairing-key authentication and the protected environment must match. The backup preserves the real original object, whatever its original language was.

```powershell
$backup = "$state\locale-TIMESTAMP.backup.json"
webos-locale @tv verify --backup $backup --ui zh-Hans-CN --allow-stt-sync
webos-locale @tv restore --backup $backup

# Offline, with the actual private session directory:
webos-locale report --session "$state\session-SESSIONID" --output .\public-report.json
```

Restore requires `RESTORE`, makes a pre-restore backup and uses the same recovery rehearsal. It restores the authenticated complete original locale, not a hardcoded Japanese template. A backup made **after** a language change cannot reconstruct an earlier state. Keep the pairing key with, but separate from, the backups; losing it prevents backup authentication. Never attach backups or private event files to public issues. The offline report is an allowlisted, human-readable JSON summary. Check it before sharing.

See [recovery.md](docs/recovery.md) before changing a TV. Recovery depends on a running TV, working Root and Settings Service. There is no verified recovery for an unbootable TV, power loss or changed firmware. A stale lock is not automatically removed. Different state directories do not coordinate: use one operator and one state directory per TV.

## Development and upstreams

Offline tests require no installed runtime dependency and never contact a TV:

```powershell
$env:PYTHONPATH = 'src'
py -B -m unittest discover -s tests -v
py -B -m webos_locale --help
```

The native-runtime tests additionally need an existing local Node.js; they skip explicitly when it is missing. They run the actual watchdog and worker in isolated VMs with synthetic RPC, clocks, processes and files. Passing mocks is not device validation.

- [LG TV Settings Service](https://webostv.developer.lge.com/develop/references/settings-service): public locale getter documentation; not an official endorsement of the Root-only setter.
- [webOS OSE settingsservice](https://github.com/webosose/settingsservice): implementation context, not proof of proprietary TV behavior.
- [webOS Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel): existing Root execution prerequisite.
- [SlopBro](https://github.com/throwaway96/slopbro): external Root research context only; not a bundled dependency or a compatibility recommendation.

MIT License. The existing [LICENSE](LICENSE) is preserved. LG firmware, fonts, translations, captured private backups and third-party source are not distributed.
