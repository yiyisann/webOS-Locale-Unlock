# Security and privacy review — v0.1.0

## Scope and trust boundary

Reviewed: the CLI, full-object request/diff logic, authenticated backup format, minimal SSAP launcher, temporary Windows callback receiver, in-memory HBC worker/watchdog, synthetic tests, documentation and Git content. No dependency was installed, no TV was probed or changed, and no third-party penetration audit was performed.

Assets are the existing pairing key, Root execution authority, private original locale/evidence and protected TV settings. The operator, Windows host, rooted TV, pre-existing HBC and LAN must be trusted. Local administrators, a compromised TV/HBC, malicious native responses and an active LAN attacker are not contained by this tool. Backups and private sessions are not public diagnostics.

## Findings, controls and residual risk

| Severity | Finding / precondition | Control and validation | Remaining limit |
| --- | --- | --- | --- |
| **High, residual** | An active LAN attacker could modify the HTTP bootstrap or intercept the SSAP connection accepted with the TV's self-signed TLS certificate. Bootstrap modification can run code through already-authorized Root HBC. | Bind Windows only to the routed private IPv4; exact TV peer check, random per-session URL token, one-use page, no redirects, no public targets. Handler restrictions and SSAP options tested offline. | These are scope controls, not cryptographic peer authentication. Use a trusted isolated LAN; this release is unsuitable for hostile/shared networks. No firewall, proxy or router settings are changed automatically. |
| **Medium, residual** | A local user/process with access to the state directory can read private evidence/key or forge a backup if it also has that key. | State outside all Git checkouts; exclusive files, fsync, pairing-key HMAC, no credential in backups. Tests reject tampering and another key. | No encryption, hardware attestation or automatic Windows ACL hardening. Restrict filesystem access yourself. |
| **Medium, residual** | Power loss, dead native service, lost Root or independently changed region can prevent verified recovery. | Independent guard rehearsed before the single target request; separate writer; bounded restoration attempts; full readback and protected-field checks. VM tests exercise failure, disconnect, missing evidence ACK and timeout. | No guarantee for an unbootable TV, cold boot, changed firmware, HBC compromise or failure of the watchdog itself. This refactored client has not had device acceptance. |
| **Medium, addressed** | A field-only comparison could silently accept locale side effects or omit unknown original fields. | Deep-copy complete original; exact differences including unknown keys and type/list changes; UI-only request, explicit same-target STT opt-in; all other changes reject. Python and VM regressions cover these cases. | Native proprietary normalization can still make exact restoration fail; never report success without matching readback. |
| **Medium, addressed** | Recovery tied to the writer or controller would disappear with that process. | Detached parent, separate IPC writer, killed-child recovery rehearsal, actual uid/parent checks, independent timeout. Tests run the actual source with mocked process/RPC boundaries. | Simulated process separation is not proof of the new client's real-device lifecycle. |
| **Low, addressed** | Raw diagnostic exports can disclose identity, credentials, addresses, paths or unexpected service data. | Public report constructed from fixed fields, validated locale tags, booleans and known difference paths; no arbitrary error echo. Synthetic sentinel tests. Runtime filenames/keys/backups are ignored by Git. | Private event files contain raw scoped responses and must never be attached publicly. Review even allowlisted output before sharing. |

No unresolved issue is presented as a production security guarantee. High/medium residuals above are material assumptions for an experimental Root tool. Publishing source for review does not establish that it is safe for unattended or general consumer use.

## Enforced limits

- No Root exploit/installer, TV file writes, resource replacement, NVRAM setter, region setter, reboot, engineering-menu command, update-policy change or remote shell server.
- Native writes are limited to the original full `localeInfo` or a copy with only UI changed. The worker is single-use; known STT synchronization must be opted in.
- Only existing pairing is accepted. Changed returned keys and unexpected pairing requests fail; manifests cannot add arbitrary fields/signed permission bundles or expand the permitted app-launch subset.
- The temporary Windows server serves only one fixed bootstrap, fixed commands and scoped event acknowledgments. It accepts the specified TV IP and token, bounds request size, requires ordered events, rejects changed duplicates and disables request logging. It is closed on normal exit. It is still reachable from the LAN interface while active; do not expose it publicly.
- No telemetry, public upload, credential collection, whole-DB dump or broad system-log export. Private state is not stored in the source tree.
- Dependency: websocket-client, Apache-2.0, installed separately by the operator. Original AGPL experiment transport was not copied; no third-party or LG resources are bundled. Dependency installation, build and supply-chain auditing remain outside this local review.

Report security concerns without keys, serials, ESNs, account data, IPs, backup files or raw private events. Do not post a live proof of Root access or secrets in public issues. Provide a small synthetic reproducer or allowlisted report instead.
