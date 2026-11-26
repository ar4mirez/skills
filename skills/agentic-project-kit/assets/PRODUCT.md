---
status: draft
version: 0.1.0
owner: {{owner}}
requirements: [CORE-01]
---

# {{project}}: product

What to build and why. `TECH.md` says how.

## Problem

{{Who has the problem, what it costs them today, and how we will know it is solved.}}

## Users

| User | Needs |
| --- | --- |
| {{role}} | {{what they come to do}} |

## Goals and non-goals

- Goal: {{an outcome we can test}}
- Non-goal: {{what we deliberately won't do}}

## Areas

Each area owns an ID prefix. When this file passes its size cap, move an area
to `docs/prd/<area>.md` and keep only its row here.

| Area | Prefix | File | Owner | Status |
| --- | --- | --- | --- | --- |
| Core | CORE | this file | {{owner}} | draft |

## Requirements

IDs are stable: never renumber or reuse one. To drop a requirement, set its
Priority to `withdrawn` (or `deferred`). Tests name the ID they prove.

| ID | Requirement | Priority | Acceptance |
| --- | --- | --- | --- |
| CORE-01 | {{the first thing a user must be able to do}} | must | {{observable result}} |

## Open questions

- {{a question that changes what we build}}
