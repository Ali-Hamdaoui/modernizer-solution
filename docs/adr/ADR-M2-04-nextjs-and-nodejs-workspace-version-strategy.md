# ADR-M2-04 Next.js and Node.js workspace/version strategy

Status: Ready for reviewer approval

Date: 2026-06-10

## Context

The repository now has a minimal M2 Next.js vertical-slice workspace at:

```text
web/control-tower/
```

Found:

- `package.json`.
- `package-lock.json`.
- Next.js app files.
- React dependency.

Local Node.js diagnostic:

- `node --version`: `v24.15.0`.

The workspace declares Next.js `16.2.7`, React `19.2.7`, and React DOM `19.2.7`.

## Decision

Use the existing frontend workspace:

```text
web/control-tower/
```

Use npm with committed `package-lock.json`. Do not introduce another frontend package manager for M2 without a reviewed M2-00 update.

## Lockfile strategy

`package-lock.json` is the reproducibility lockfile.

## Required frontend commands

```powershell
cd web/control-tower
npm ci
npm run type-check
npm test
npm run build
npm audit --audit-level=moderate
```

## Consequences

The workspace is a minimal M2 vertical slice, not the final Control Tower frontend.

Frontend code must keep business rules, proof rules, filesystem access, executable details, and actor authority in the backend.

Native browser `EventSource` should handle reconnect. The client bootstraps from the last applied persisted public sequence, ignores already-applied sequences, updates its last-applied sequence, and refetches the current job projection after state-changing events.

## Approval

| Reviewer | Decision | Date | Comments |
|---|---|---|---|
| HAMDAOUI Ali | Pending | Pending | Pending |
| ilyas abarbach | Pending | Pending | Pending |
