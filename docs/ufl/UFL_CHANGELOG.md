# UFL Changelog

All notable **project** changes should be recorded here after they ship.

This file started with the documentation/audit pass. It does **not** claim that application features were changed in that pass.

---

## 2026-09-01 — Phase 5.1 harden Discord outbox

Hardened the existing `DiscordEvent` pipeline. Website/database remains the source of truth.

- Unique `idempotency_key` plus action keys on existing news/DM writers. Same UFL action does not create a second Discord row on retry/refresh/double POST.
- Retry backoff on PENDING (`next_attempt_at`); 20 attempts then FAILED. Control can retry FAILED or waiting PENDING. Bot restart re-reads due rows.
- Owner/Admin Control Centre Discord Outbox. Managers and Members cannot administer the queue. Bot token is never shown.
- TOTW admin approve now uses `create_news` so the announcement enters the outbox. TOTW selection and 0.20 tokens unchanged.
- Job Centre invite uses `resolved_discord_invite()` (CMS / `DISCORD_INVITE_URL`). Hardcoded invite removed.
- Channel keys centralised in `mgl/discord_channels.py`. IDs stay in env. Extra channels are optional.
- Migration `mgl.0030_phase51_discord_outbox` — local only, not applied to production.
- Automated tests: **559 OK** (local SQLite).
- **No Season 1, no 38 clubs, no starting squads, no Discord messages sent, no slash/commands, no Phase 5.2 event catalogue.**

---

## 2026-09-01 — Phase 5 Discord / YourBot inspection (documentation only)

Read-only audit of the existing Discord outbox and bot. Recorded in `UFL_DISCORD_AUDIT.md`.

- Website/database remains the source of truth. `DiscordEvent` + `run_mgl_bot.py` already exist as an outbox publisher.
- No slash commands, buttons, embeds, webhooks, or YourBot codebase.
- Discord is not connected in the documented production shape. The bot is a separate process and was not started.
- **No application, migration, production, Season 1, or Discord-send changes.**

---

## 2026-09-01 — Phase 4 Job Application + player release lifecycle

Implemented DEC-041 and immediate manager release (DEC-025 / Phase 1 lock).

- Job Application (`ClubApplication`) is the only official process that makes a Member a Manager. Accept is atomic: approve identity if still PENDING, assign the club, open the club spell, mark the Job Application APPROVED.
- Official fields: EA ID / gamertag, Discord username, games per week **1–3 / 3–5 / 6+**, referred by, required new-gen checkbox. Optional numeric Discord ID may be stored on `User.discord_id` without replacing the username.
- One PENDING Job Application per manager (`unique_pending_club_application`). Reject leaves the user a Member; they may apply again.
- `ManagerApplication` remains the token/identity row created at registration. It is not a second approval gate on the official path. The leftover Control identity queue is labelled as legacy.
- Manager release is immediate: CLUB-OWNED → genuine UFL Free Agent (`released_at`). No Control approval, no token charge. `PlayerReleaseRequest` is written APPROVED as an audit row. Leftover PENDING rows can still be approved/rejected.
- Free Agents page signs with **SIGN FOR 0 TKN**. Recruitment/scout rejects stay UNSIGNED. Manager auction no-bid still returns home. Admin unsigned no-bid may become genuine FA.
- Central helper: `ufl_player_status()` → UNSIGNED / CLUB-OWNED / TEMPORARILY LISTED / UFL FREE AGENT. Legacy `is_free_agent` never wins.
- Migration `mgl.0029_phase4_job_release`. No Season 1 bootstrap, no FC26 mass edit, no Discord/YourBot, no production data writes.

---

## 2026-09-01 — Phase 3 recruitment, scouting, Free Agents and auction economy

Implemented the UFL player recruitment economy on top of locked DEC-042 status.

- Recruitment packs are Owner/Admin configurable (`RecruitmentPack`). Default result is **3 UNSIGNED / choose 1**. Unselected stay UNSIGNED.
- Per-pack opening limits, 0.5 token costs, OVR/position filters, and reserved results are enforced in the database.
- Scouting returns **4 UNSIGNED / choose 1**. Levels 1–4 and extra time-reduction % are Owner/Admin configurable. `scout_can_recruit` is enforced.
- Genuine UFL Free Agent signing remains **0 TKN**. Unsigned and legacy `is_free_agent=True` do not appear on the FA page.
- Manager auction listing fee is **0.1 TKN**, charged once, not refunded. Manager no-bid returns to the original club. Admin unsigned no-bid may become a genuine FA.
- Migration `mgl.0028_recruitment_economy`. No Season 1 bootstrap, no FC26 mass edit, no Discord/YourBot connection, no production data writes.

## 2026-09-01 — DEC-042 generator and genuine Free Agent status

Implemented the locked Season 1 player-pool rules and stopped the public Free Agents page from listing the unused FC26 set.

- Starting-squad generator treats unassigned players as UNSIGNED regardless of `is_free_agent`.
- RB may fill RB/RWB and LB may fill LB/LWB without rewriting FC26 positions.
- Genuine UFL Free Agent status is `Player.released_at`, set only by explicit UFL processes (club release, no-bid admin/unsigned auction). The legacy flag is not mass-edited.
- Public Free Agents page and player-database FA filters use that status.
- Manager no-bid club auctions still return the player to the original club.
- Read-only 38-club simulation only. Production apply/approve was not run.

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
