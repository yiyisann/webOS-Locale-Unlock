# Compatibility

Status describes the stated scope, never an entire product family.

| Scope | Status | Evidence / limit |
| --- | --- | --- |
| Original method: Japanese OLED42C5PJA.AJLQLJD, 43.21.96, webOS 26 / internal 11.2.0, HBC 0.7.3; UI→zh-Hans-CN | **Verified** for this running session | Native UI-only request succeeded; STT followed UI; complete field comparison and owner visual checks passed |
| Same method as complete Chinese localization | **Partially verified** | Principal menus Chinese; Loading label, Japanese TV OSD/keyboards/NLP and possible translation fallback remain |
| Original method's Root/HBC and Japan-region preservation | **Verified** for the experiment | uid=0, HBC/startup and JP configuration retained; owner confirmed HDMI/picture/sound/network/Japanese broadcasts |
| Original method's independent recovery | **Verified** for the exercised paths | Detached uid=0 guard, killed dummy child, complete original-value write/readback; previous trial fully restored |
| This v0.1.0 CLI on a real TV, including SSAP identity/packaging | **Untested** | Local mocks and isolated runtime VMs only; requires independent end-to-end acceptance |
| Chinese UI across normal restart | **Untested** | No restart performed after localization |
| Chinese UI across full power loss/cold boot | **Untested** | No cold boot performed |
| Chinese/Japanese voice recognition accuracy | **Untested** | STT changed; NLP remained Japanese |
| Other C5 sizes/regions, G5, C4 or other firmware/HBC versions | **Untested**; writes **Unsupported** in v0.1 | Do not inherit compatibility from the model family |
| Other target languages | **Untested**; writes **Unsupported** in v0.1 | Audit can inspect a requested tag; catalog discovery is only implemented for the known Chinese layout |
| Unrooted TV, missing HBC exec or required native paths | **Unsupported** | No privilege escalation or installation fallback |
| Region changes, resource replacement, engineering-menu unlocking, firmware changes | **Unsupported** | Outside project scope |
| Unbootable TV, lost Root, changed firmware, factory reset, complete Root/HBC uninstall | **Unsupported / recovery unverified** | No out-of-band recovery or full uninstall rehearsal |

The write profile checks model, firmware, internal SDK, HBC version, both Area readers, JP hardware/language/broadcast baseline and Chinese catalog presence. During a transaction it additionally compares the complete captured config, region, HBC and startup state. It does not automatically expand its allowlist after an audit succeeds.

Read-only Audit/Backup use the same scoped native readers, so even those commands may fail on a different firmware's paths or ACLs. That failure is not evidence that the device cannot be localized. Do not disable guards or change region to make an unsupported profile pass.

The test fixtures are manually constructed. Some use the public known profile identifiers to exercise profile gates, and others deliberately use a fictional model and French original locale. They are not captured device data or additional compatibility claims.
