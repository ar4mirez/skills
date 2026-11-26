---
status: draft
version: 0.1.0
owner: {{owner}}
requirements: []
---

# {{project}}: extensions

How others change {{project}} without changing its code. Only keep this file
if the project has a configuration, plugin or integration surface.

## The ladder

Reach for the lowest rung that works:

1. Configuration (a setting or a record).
2. Content or data types.
3. Automations and hooks.
4. Plugins that run in-process. These need a decision record.
5. Separate apps that talk over a published contract.

## Extension points

| Point | Contract | Version | Owner |
| --- | --- | --- | --- |
| {{hook, setting or API}} | {{schema or interface}} | 1 | {{owner}} |

## Versioning

An extension contract is a public API. Adding to it is fine. Removing or
changing something is breaking: it needs a new version, a migration note in
`CHANGES.md`, and a deprecation period.
