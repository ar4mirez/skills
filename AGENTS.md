# AGENTS.md: authoring guide for this repository

This repo is a collection of portable **Agent Skills** that follow the open
specification at https://agentskills.io. Any agent (Claude Code, Codex, Cursor,
Copilot, etc.) working here must follow these rules. Humans should too.

## Layout

```
skills/<skill-name>/          one directory per skill (the unit that gets installed)
  SKILL.md                    required: frontmatter + core instructions (< 500 lines, < 5k tokens)
  references/                 on-demand docs, one level deep, each focused on one topic
  assets/                     templates and static resources the skill produces or fills in
  scripts/                    self-contained, non-interactive executables with --help
  evals/evals.json            output-quality test cases (+ evals/files/ fixtures)
  evals/trigger_queries.json  ~20 should/shouldn't-trigger queries for the description
template/                     skeleton (SKILL.md.tmpl, so installers never list it) copied by scripts/new-skill.sh
scripts/                      repo tooling (validator, scaffolder, local linking)
tests/                        unit tests for bundled skill scripts
.claude-plugin/marketplace.json  Claude Code marketplace: one plugin entry per skill
```

## Rules for every skill

**Frontmatter (spec requirements):**
- `name` is 1–64 characters of lowercase `a-z`, `0-9`, and single hyphens. It
  must not start or end with a hyphen, and it must **equal the directory
  name**.
- `description` is 1–1024 characters. It says **what** the skill does *and*
  **when** to use it, in imperative form ("Use when..."). Include user-intent
  phrasings for when the user doesn't name the domain, plus a "Not for..."
  boundary for near-miss tasks.
- Always include `license` and `metadata.author` / `metadata.version`, quoted
  as strings. Add `compatibility` only if the skill has real environment
  requirements. Don't add fields outside the spec.

**Portability:**
- A skill must work when copied **alone** into any agent's skills directory.
  Never reference files outside its own directory, and never use absolute
  paths.
- Scripts use only the standard library, or declare their dependencies inline
  (PEP 723 with `uv run`). They are non-interactive and print helpful errors.
  Exit codes are documented.
- No vendor-specific tool names in the core instructions. If a skill needs one,
  put it in `compatibility` or in a clearly marked section.

**Content:**
- Add what the agent *lacks*: domain procedures, gotchas, and defaults. Cut
  anything the agent already knows.
- Keep `SKILL.md` lean. Move detail to `references/`, and tell the agent
  **when** to load each file.
- Give a default instead of a menu of options.
- Put a **Gotchas** section in `SKILL.md`. Every correction you give an agent
  during use belongs there.
- Explain the *why* behind each rule, so the agent can make judgment calls.
- Put templates for any artifact the skill produces in `assets/`.
- Source material must be paraphrased and attributed. Don't copy copyrighted
  text wholesale.

## Workflow for adding or changing a skill

1. **Scaffold.** Run `make new name=<skill-name> desc="<one line>"`, which copies
   `template/` and registers the skill in `.claude-plugin/marketplace.json`.
2. **Ground it in real expertise.** Use primary sources, real artifacts, and
   real tasks, not generic best practices.
3. **Write** `SKILL.md`, then the references, assets, and scripts.
4. **Validate.** Run `make check` (the spec, repo conventions, and script
   tests). Also run `make validate-ref` if you have `skills-ref` installed.
5. **Evaluate.** For each case in `evals/evals.json`, run the prompt in a fresh
   context twice: once *with* the skill and once *without* it. Grade the
   assertions with evidence. Keep eval workspaces outside the skill directory
   (`<skill>-workspace/`, which is gitignored). Tune the description against
   `evals/trigger_queries.json`, using a train/validation split to avoid
   overfitting.
6. **Bump** `metadata.version` in `SKILL.md` using semver:
   - major: a behavior change that breaks existing usage;
   - minor: new capability;
   - patch: fixes and wording.
7. **Commit** with a conventional message (`feat(shape-up): ...`,
   `fix(shape-up): ...`, `docs: ...`).

## Local development

Run `make link` to symlink every skill into `~/.claude/skills`, so edits are
live. Pass `TARGET=<dir>` for other agents. Run `make unlink` to undo it.
