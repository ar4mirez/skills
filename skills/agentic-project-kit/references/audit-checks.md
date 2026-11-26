# Audit checks

`kit.sh audit` prints one finding per line: `<error|warn> <check> <path>:
<message>`. Errors fail the audit (exit 1). Warnings fail only with
`--strict`. Fix errors first.

| Check | Severity | Meaning | Fix |
| --- | --- | --- | --- |
| K01 | error | A kit file for the profile is missing, or its mapped target doesn't exist | `scaffold` it, or add a row to `docs/kit-map.md` (a target, or `n/a` plus a reason) |
| K02 | error / warn | `CLAUDE.md` isn't exactly `@AGENTS.md` (a copy or extra content is an error, a symlink is a warning) | Move the content into `AGENTS.md` and make `CLAUDE.md` the one line |
| K03 | error | A file is over its token cap | Split it by area (`references/conventions.md`). For `CHANGES.md`, `rotate`. For `AGENTS.md`, move detail into the specs |
| K04 | error | No front matter, or front matter that isn't closed | Add the `---` block |
| K05 | error | Front matter is missing or has an invalid status, version, owner or requirements | Fill in each field. `requirements` is an inline list |
| K06 | warn | Unfilled `{{placeholders}}` | Replace them with real content, or delete the line |
| K07 | error | A requirement ID is malformed or defined twice | Use `AREA-NN`. Give the duplicate a new, unused ID. Never renumber the original |
| K08 | error | A doc's front matter references an ID that no requirement table defines | Fix the typo, or add the requirement first |
| K09 | warn | No test or code names a requirement | Write the test and name the ID in it. On a new repo this is expected |
| K10 | warn | A requirement isn't in any milestone brief (checked only when briefs exist) | Plan it in a brief, or set its Priority cell to `deferred` |
| K11 | warn | A requirements file's front matter list doesn't match its tables | Set `requirements:` to the IDs the message lists |
| K12 | error / warn | A risk acceptance has bad dates, has expired, or runs more than 90 days (warns within 14 days of expiry) | Fix the risk, or add a fresh acceptance row |
| K13 | warn | `CHANGES.md` still holds released version sections | Run `kit.sh rotate --version X <repo>` once per old version, or move them into `docs/changes/` by hand |
| K14 | error / warn | A milestone brief plans in calendar time (error), or has no `budget_tokens` or Exit tests section (warning) | Remove dates, hours and deadlines. Add a token budget and exit tests |
| K15 | warn | A decision record is missing Options, Recommendation or Decision, or is decided without the owner's quoted words | Add the sections and quote the owner in a `>` block |
| K16 | error | `AGENTS.md` has no Agent safety section | Add the template's section |
| K17 | warn | An incident has no Guardrail section | Add the rule, test, check or eval case it produced |
