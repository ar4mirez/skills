# ar4mirez/skills

This repo holds portable [Agent Skills](https://agentskills.io): folders of
instructions, references, templates, and scripts that give AI agents real
domain expertise. Every skill follows the open
[Agent Skills specification](https://agentskills.io/specification), so it
works in any compatible client (Claude Code, Claude.ai, Codex, Cursor, GitHub
Copilot, VS Code, and others).

## Skills

| Skill | What it does |
|---|---|
| [`shape-up`](skills/shape-up/SKILL.md) | Acts as an expert practitioner of Basecamp's [Shape Up](https://basecamp.com/shapeup) method. It shapes raw ideas into pitches (appetite, breadboards, rabbit holes, no-gos), runs betting tables, hands projects to teams, maps scopes, reads hill charts, and hammers scope to ship on time. It bundles a pitch checker and a hill-chart renderer. |
| [`ruby-on-rails`](skills/ruby-on-rails/SKILL.md) | An opinionated senior Ruby and Rails 8 engineer. It favors a modular monolith, rich models, REST-only controllers, Hotwire, the Solid Queue/Cache/Cable stack, Minitest, and Kamal. It ships iOS and Android apps from the same codebase with Hotwire Native, and bundles an app health audit and a path-configuration validator. |

## Install

**Any agent, via the [`skills`](https://github.com/vercel-labs/skills) CLI:**

```bash
npx skills add ar4mirez/skills --list              # see what's available
npx skills add ar4mirez/skills --skill shape-up    # install one skill into this project
npx skills add ar4mirez/skills --skill shape-up -g # install globally, for all projects
```

**Claude Code, as a plugin marketplace:**

```
/plugin marketplace add ar4mirez/skills
/plugin install shape-up@ar4mirez-skills
```

**Manually:** copy or symlink `skills/<name>/` into your agent's skills
directory, for example `~/.claude/skills/<name>` or `.agents/skills/<name>`.
Each skill directory is self-contained.

## Development

Requirements: Python 3.9+ and `make`. Optionally, install
[`skills-ref`](https://github.com/agentskills/agentskills/tree/main/skills-ref)
for the reference validator.

```bash
make help                              # list targets
make new name=my-skill desc="One line" # scaffold from template/ and register it in the marketplace
make check                             # validate every skill and run script tests (what CI runs)
make validate-ref                      # run the official skills-ref validator too
make link                              # symlink skills into ~/.claude/skills for live local testing
```

See [AGENTS.md](AGENTS.md) for the authoring rules and the evaluation workflow.
CI runs the same checks on every push and pull request.

## Repository layout

```
skills/<name>/            installable skill: SKILL.md + references/ assets/ scripts/ evals/
template/                 skeleton for new skills
scripts/                  repo tooling (validate_skills.py, new-skill.sh, link-local.sh)
tests/                    tests for scripts bundled inside skills
.claude-plugin/           Claude Code marketplace manifest (one plugin per skill)
.github/workflows/        CI: spec validation, skills-ref, tests
```

## Acknowledgements

The `shape-up` skill paraphrases and cites *Shape Up: Stop Running in Circles
and Ship Work that Matters* by Ryan Singer, © Basecamp, which is freely
available at https://basecamp.com/shapeup. This repository isn't affiliated
with or endorsed by Basecamp or 37signals. Read the book, because it's
excellent.

## License

[MIT](LICENSE)
