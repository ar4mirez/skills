---
status: draft
version: 0.1.0
owner: {{owner}}
requirements: [SEC-01]
---

# {{project}}: security

This file wins on security. Report vulnerabilities to {{private contact}},
never in a public issue.

## When to raise security

You don't need to build everything at once. When work touches an area below,
raise the concern at intake, design, review and before merging. Then decide
whether to do it now or later. Record each "later" as an issue or a risk
acceptance, so it isn't lost.

1. **Core security and systems.** Network protocols (TCP, UDP, HTTP, TLS,
   DNS), OS permissions, processes and privilege boundaries, crypto basics,
   trust boundaries, least privilege, defence in depth. Models: CIA, STRIDE,
   kill chain.
2. **Web and API.** OWASP risks (XSS, SQLi, CSRF, SSRF, IDOR), input validation
   and output encoding, sessions and cookie flags, API auth (keys, OAuth2,
   JWT), object-level authorization, rate limits and abuse, uploads and
   deserialization.
3. **Identity, access and secrets.** MFA, password storage and credential
   stuffing, SSO, RBAC and ABAC, service accounts and workload identity, least
   privilege and time-bound access, vaults and key rotation, impersonation and
   session hijacking.
4. **Cloud and infrastructure.** Segmentation and private connectivity,
   firewalls and WAF, bucket and blob security, containers and Kubernetes
   RBAC, IaC and policy as code, patching by risk, endpoint hardening, secure
   baselines.
5. **Detection, response and secure delivery.** Log sources and useful
   detections, incident response through to lessons learned, alert triage and
   ownership, evidence preservation, security-focused code review, SAST, DAST
   and dependency scanning in CI.

## Requirements

| ID | Requirement | Area |
| --- | --- | --- |
| SEC-01 | Secrets never appear in code, logs, fixtures or docs. | 3 |

## Threat model (STRIDE)

One row per trust boundary and threat that applies. Link the mitigation to a
requirement ID or a test.

| ID | Boundary | STRIDE | Threat | Mitigation |
| --- | --- | --- | --- | --- |
| TM-01 | {{user to API}} | S | {{a forged session}} | {{SEC-NN or a test}} |

STRIDE: Spoofing, Tampering, Repudiation, Information disclosure, Denial of
service, Elevation of privilege.

## Risk acceptances

A risk we knowingly carry. Each one has an owner and lasts at most 90 days
from Accepted to Expires. On expiry, fix the risk or accept it again with a new
row. `kit.sh audit` fails on an expired or over-long acceptance.

| ID | Risk | Owner | Accepted | Expires | Mitigation or plan |
| --- | --- | --- | --- | --- | --- |
