# ADR-M2-04 Next.js and Node.js workspace/version strategy

Status: Proposed for review

Date: 2026-06-10

## Context

No frontend workspace exists in the repository today.

Not found:

- `package.json`.
- `package-lock.json`.
- `pnpm-lock.yaml`.
- `yarn.lock`.
- Next.js app files.
- React dependency.

Local Node.js diagnostic:

- `node --version`: `v24.15.0`.

The M2 plan lists Next.js `16.2.7`, React `19.2.7`, and Node 24 LTS as candidates for a new frontend. These are not installed by the repository today.

## Decision

M2-00 does not create a frontend workspace or force a frontend migration.

If reviewers do not choose another convention, M2-12 should create the new frontend under:

```text
web/control-tower/
```

A new frontend should target Node 24 LTS, Next.js 16.x, and React 19.x after dependency resolution is verified.

## Lockfile strategy

M2-12 must commit the selected package-manager lockfile with the new workspace.

The package manager is not currently selected by repository convention. M2-12 must choose one explicitly and document the install/audit/build commands.

## Required frontend commands once workspace exists

Commands are unverified until a package manager is selected:

```text
install consistency check
audit
type-check
unit tests
production build
```

## Consequences

Frontend checks are not applicable in M2-00.

M2-12 owns frontend dependency introduction, lockfile creation, accessibility checks, and wording tests that prevent diagnostic success from being described as migration proof.
