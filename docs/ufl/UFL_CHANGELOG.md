# UFL Changelog

All notable **project** changes should be recorded here after they ship.

This file started with the documentation/audit pass. It does **not** claim that application features were changed in that pass.

---

## 2026-09-01 — Documentation and audit (no application changes)

- Inspected the live Django UFL / Career Mode codebase (apps, models, views, settings, routes, CSS).
- Created `/docs/ufl/` as the project source of truth:
  - `UFL_MASTER_SPEC.md`
  - `UFL_ROLES_PERMISSIONS.md`
  - `UFL_GAME_RULES.md`
  - `UFL_CAREER_MODE.md`
  - `UFL_TRANSFER_RULES.md`
  - `UFL_DATABASE_RULES.md`
  - `UFL_DESIGN_SYSTEM.md`
  - `UFL_ROUTES.md`
  - `UFL_APPROVAL_SYSTEM.md`
  - `UFL_SECURITY_RULES.md`
  - `UFL_DECISIONS.md`
  - `UFL_PROGRESS.md`
  - `UFL_CHANGELOG.md`
  - `UFL_TEST_PLAN.md`
- Pointed the root `README.md` at `/docs/ufl/` for product truth. Operational run commands were not rewritten as a new stack.
- **No** UI redesign, route changes, database migrations, data resets, auth changes, Career Mode logic changes, FC26 changes, token changes, or approval-flow changes were made in this pass.

---

## How to log future work

After a real change:

1. Add a dated section: what changed, what did not change, and which specs you updated.
2. Do not list “fixed” items that were only documented.
3. Update `UFL_PROGRESS.md` in the same commit when status changes.
