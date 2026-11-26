---
status: draft
version: 0.1.0
owner: {{owner}}
requirements: []
---

# {{project}}: technical design

How to build what `PRODUCT.md` asks for. Each stack choice links to the
decision record that made it.

## Rules for agents

1. {{the architectural rule that must never be broken}}
2. Tests name the requirement ID they prove.
3. Contracts (schemas, interfaces, migrations) change before the code that uses them.

## Architecture

{{The parts, what each one owns, and how they talk. A small diagram is welcome.}}

| Part | Owns | Talks to |
| --- | --- | --- |
| {{part}} | {{data or behaviour}} | {{other parts}} |

## Stack

| Concern | Choice | Decision |
| --- | --- | --- |
| {{language, storage, hosting}} | {{choice}} | `docs/decisions/0001-{{slug}}.md` |

## Testing

- Where tests live: {{path}}
- How to run them: `{{check command}}`
- Requirement IDs appear in test names or comments, in any language.

## Sizing work

Milestones are sized in tokens and context, never in time. A plan that
won't fit one working session is split.

## Areas

When this file passes its size cap, move an area to `docs/tech/<area>.md` and
keep a row here.

| Area | File | Owner |
| --- | --- | --- |
| Core | this file | {{owner}} |
