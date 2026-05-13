# ADR 0001 â€” Stack baseline anchored in `docs/ARCHITECTURE.md`

**Status:** Accepted
**Date:** 2026-04-28
**Authors:** @msoliman1975

## Context

`docs/ARCHITECTURE.md` is binding. It records every committed stack and infrastructure decision for AgriPulse's MVP. Engineers should never invent or "improve" a stack choice during implementation; they should re-read the architecture doc instead.

This ADR exists to anchor that arrangement: it does not introduce new decisions. It records, in the form we'll use for every future change, that the stack already enumerated in `docs/ARCHITECTURE.md` and the schemas already enumerated in `docs/data_model.md` are the source of truth from this point forward.

## Decision

1. `docs/ARCHITECTURE.md` is the canonical record of stack, deployment, observability, RBAC, API, imagery, alerting, i18n, units, CI/CD, and observability decisions for the platform.
2. `docs/data_model.md` is the canonical record of every table, column, index, hypertable, and view across the `public` schema and per-tenant schemas.
3. Any new architectural decision (a new library, a new pattern, a new module, a different deployment topology) **must** start with a new ADR under `docs/decisions/NNNN-short-title.md` using `0000-template.md`. The decision is accepted only after a human approves the ADR.
4. After acceptance, the corresponding section of `docs/ARCHITECTURE.md` or `docs/data_model.md` is updated **in the same PR** as the ADR, so the two documents and the ADR move together.
5. Code and configuration changes that depend on the new decision land in a follow-up PR after the docs PR is merged.

## Consequences

- **Positive.** Stack drift is impossible without an explicit, reviewed paper trail. Future Claude Code sessions can rely on the architecture doc as ground truth.
- **Negative.** A small overhead per architectural change: one extra PR (the ADR) before code lands.
- **Neutral.** ADRs are short. The discipline pays off the second time we'd otherwise have re-litigated a decision.

## Alternatives considered

- **No ADRs, only the architecture doc.** Rejected â€” without an audit trail, "the architecture doc says X" loses its history. ADRs explain the *why* that the architecture doc only summarizes as the *what*.
- **ADRs in a separate repo.** Rejected â€” separation breaks the link between a decision and the code or schema that implements it.

## Follow-ups

- [x] Add `docs/decisions/0000-template.md` so new ADRs have a standard shape.
- [ ] Whenever a future ADR changes a binding constraint in `docs/ARCHITECTURE.md` or `docs/data_model.md`, that PR also updates the affected section of those docs.
