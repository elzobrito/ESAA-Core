# QA — Bilingual guides (PT + EN)

**Task:** T-I18N-QA · **Depends on:** T-I18N-README

Verification of the bilingual documentation roadmap (i18n): six source guides
gained an English `.en.md` sibling alongside the canonical Portuguese file, each
with a language switcher, and the README now points to the English versions.

## Scope verified

| Portuguese (canonical) | English (new) |
|---|---|
| `docs/guides/esaa-getting-started.md` | `docs/guides/esaa-getting-started.en.md` |
| `docs/guides/esaa-cenarios.md` | `docs/guides/esaa-cenarios.en.md` |
| `docs/guides/esaa-cli-reference.md` | `docs/guides/esaa-cli-reference.en.md` |
| `docs/guides/esaa-runners-codex-claude-code.md` | `docs/guides/esaa-runners-codex-claude-code.en.md` |
| `docs/guides/esaa-why.md` | `docs/guides/esaa-why.en.md` |
| `docs/security/threat-model.md` | `docs/security/threat-model.en.md` |

## Checks and results

1. **EN files exist** — all 6 `.en.md` siblings present. ✅
2. **Link targets resolve** — every relative markdown link in the EN files
   resolves to an existing file; intra-guide links point to `.en.md` siblings,
   `../plugins/*.md` kept (already English). ✅
3. **Cookbook in-page anchors** — 22 in-page anchors used across the EN cookbook
   (index, cross-references, summary) all match a regenerated English heading
   slug (38 heading slugs). Zero broken anchors. ✅
4. **Code-block integrity** — commands, JSON, and YAML payloads are identical
   between each PT/EN pair. The only intentional in-block localizations are:
   inline `#` comments, and example placeholders (`meu-endpoint`→`my-endpoint`,
   `ARQUIVO.json`→`FILE.json`, `<subcomando>`→`<subcommand>`). No command, flag,
   action, reject code, env var, or JSON key/value was changed. ✅
5. **Language switchers** — all 6 PT files and all 6 EN files carry the
   `🌐` switcher line linking to the other language. ✅
6. **README** — the 5 Usage Guides links point to `.en.md`; the section note
   reads "Guides are available in English and Portuguese". ✅

## Notes

- Portuguese remains the canonical source. Maintenance rule: any content change
  must update the `.en.md` sibling in the same PR to avoid drift (to be recorded
  in `CONTRIBUTING.md`).
- Out of scope (unchanged): `docs/spec/*`, `docs/qa/*` (except this report),
  `docs/operations/*`, and `docs/plugins/*` (already English).

## Verdict

**PASS.** The bilingual structure is consistent, links and anchors are intact,
and code is preserved except for intended comment/placeholder localization.
