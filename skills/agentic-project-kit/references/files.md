# What goes in each kit file

Load this when you are deciding where content belongs, or when you map a
repo's own documents onto the kit.

| File | Profile | Holds | Doesn't hold |
| --- | --- | --- | --- |
| `AGENTS.md` | lite | Read order, how work is planned and done, definition of done, agent safety, never-rules, commands | Specs, history, long explanations |
| `CLAUDE.md` | lite | Exactly `@AGENTS.md` | Anything else |
| `PRODUCT.md` | lite | Problem, users, goals and non-goals, the areas index, requirements with IDs, open questions | How to build it |
| `TECH.md` | lite | Agent rules, architecture, stack (linked to decisions), testing, sizing work, areas index | Requirements, history |
| `SECURITY.md` | lite | Reporting contact, the 5-area checklist, `SEC-NN` requirements, the STRIDE table, risk acceptances | Secrets, scan dumps (those go in `docs/security/`) |
| `docs/decisions/` | lite | One record per decision, a README index, a TEMPLATE | Meeting notes |
| `AGENTIC.md` | full | Autonomy table (what agents may do alone), agent tools, untrusted-content rule, evals, skills | Day-to-day rules (those go in `AGENTS.md`) |
| `CHANGES.md` | full | Unreleased bullets and the Released index | Released history (that's in `docs/changes/`) |
| `GLOSSARY.md` | full | Domain terms, meanings and near-misses | General tech jargon |
| `EXTENSIONS.md` | opt-in | The extension ladder, extension points and their contracts, versioning | Internal APIs |
| `docs/prd/` | full | Product area files split from `PRODUCT.md`, source PRDs | |
| `docs/tech/` | as needed | Technical area files split from `TECH.md` | |
| `docs/milestones/` | full | Briefs `MNN-slug.md`, an index, a TEMPLATE | Dates or hours |
| `docs/runbooks/` | full | One operational situation per file | Design docs |
| `docs/security/` | full | Security area splits, threat model detail, scans, reviews | Secrets |
| `docs/changes/` | full | One file per released version, written by `rotate` | |
| `docs/incidents/` | full | Blameless postmortems, each ending in a guardrail | Blame |
| `docs/evals/` | full | Agent-behaviour conformance cases (`EV-NN`) and their results | Unit tests |
| `docs/kit-map.md` | map | Kit role, then the existing file, or `n/a` plus a reason | |

## Mapping a repo that has its own docs

1. Inventory what exists: README, requirement or spec docs, ADR folders,
   security policy, changelog, runbooks, contributor guide.
2. For each kit role the repo already covers, add a row to
   `docs/kit-map.md`: `| PRODUCT.md | spec/requirements.md | existing spec |`.
   A folder role ends in `/` (`| docs/decisions/ | adr/ | existing ADRs |`).
3. For a role that genuinely doesn't apply, write `n/a` with a reason.
4. Scaffold the rest. `scaffold` skips existing files, and the audit counts a
   mapped role as present.
5. Leave mapped files in the client's format. The audit checks only that they
   exist. It doesn't impose front matter or caps on them. If a mapped file is
   huge, tell the user and suggest splitting it, but don't do it unasked.
6. `AGENTS.md` is always the kit's. If the repo already has one, merge the
   kit's read order and Agent safety section into it. Don't replace their
   rules. Then make `CLAUDE.md` the one-line import.

Typical mappings: `CHANGELOG.md` → `CHANGES.md` (rotation then works only on
`CHANGES.md`, so say so), `.github/SECURITY.md` → `SECURITY.md`, `docs/adr/`
→ `docs/decisions/`, `CONTRIBUTING.md` stays as it is and `AGENTS.md` links
to it.
