# docs/archive/ — superseded specs and sequences

Files here are **archived** — they represent prior authoritative baselines that have been superseded by a newer version. Per Kosmos discipline:

- **Never referenced** from live code, ADRs, sequence documents, or skill instructions.
- **Never deleted** — retained for provenance and to reconstruct historical decisions.
- **Not amended** — corrections to archived content are made in the current baseline, not here.

## Current archive

| File | Superseded by | Superseded on | ADR |
|---|---|---|---|
| `Kosmos-Build-Spec-v25.md` | `../Kosmos-Build-Spec-v26.md` | 2026-09-10 | ADR-078 |
| `Kosmos-Build-Sequence-v25.md` | `../Kosmos-Build-Sequence-v26.md` | 2026-09-10 | ADR-078 |

## Newer-wins rule

`kosmos-spec-diff` enforces the newer-wins rule: where prior specs conflict, the current baseline (`../Kosmos-Build-Spec-v26.md`) always wins. If an older position appears preferable, the correct action is to amend the current baseline — never to revive an archived spec.
