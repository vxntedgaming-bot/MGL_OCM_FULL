# UFL Changelog

All notable **project** changes should be recorded here after they ship.

This file started with the documentation/audit pass. It does **not** claim that application features were changed in that pass.

---

## 2026-09-01 — DEC-042 player status + Season 1 pool re-check (docs + read-only)

Owner locked: unsigned ≠ Free Agent; do not mass-edit `is_free_agent`; FA page is explicit FA only; manager no-bid auctions return home; Season 1 eligibility uses unsigned players, ignores the stored FA flag, and maps RB→RB/RWB and LB→LB/LWB.

Read-only in-memory simulation with those Season 1 rules: **6,225** unsigned 64–69 players; every position has surplus; five seeds each allocated **1,140** unique players with average-OVR gap **0.000–0.033** (limit 1.500). No clubs, squads, tokens, or locks were written.

**Documentation updated. Generator code not changed in this pass.**

---

## 2026-09-01 — Phase 2.1 starting squads + Season 1 bootstrap

Implemented the locked 30-player starting-squad generator and a controlled 38-club Season 1 bootstrap.

- Active `UFL_SQUAD_SHAPE` is the locked 30-player table. Runtime roster helpers never cap below 30.
- Canonical path: Control generate → Owner review → Owner approve → lock. No stacking. Atomic rollback.
- Path B write (`apply_starting_squads --apply`) is fenced. Path C remains disabled.
- Season 1 preview creates a 16 / 14 / 8 plan with random fictional club identities. Production apply is blocked.
- Migrations: `mgl.0027_ufl_roster_30`, `teams.0007_team_is_ufl_starter`.
- Automated tests: **478 OK** (local SQLite, production env unset).
- **Production clubs were not deleted. Production squads were not generated. StartingSquadLock was not written on production.**

---

## 2026-09-01 — Job Application is the single process (documentation only)

Owner locked DEC-041: Member submits a Job Application → Admin reviews → Admin accepts → job/manager appointment. No extra manager-application approval stage. Official fields: EA ID / gamertag, Discord username, games per week 1–3 / 3–5 / 6+, referred by, new-gen checkbox.

Current code (separate `ManagerApplication` gate, numeric Discord ID, 1 / 2 / 3 / 4 / 5+) is recorded as **GAP TO IMPLEMENT**.

**Documentation updated only. No application, database, or production changes.**

---

## 2026-09-01 — Phase 1 UFL rules lock (documentation only)

Owner supplied and locked the Phase 1 UFL rules.

- Recorded in `/docs/ufl/` (master spec, game rules, career, transfers, approvals, decisions, progress, and related specs).
- Distinguishes **locked product rules**, **current code**, and **current 14-club test production**.
- **Documentation updated only.**
- **No application, template, CSS, JavaScript, Python/Django, model, migration, or database changes were made.**
- **No clubs, players, tokens, starting squads, StartingSquadLock, authentication, or production data were reset or modified.**

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
