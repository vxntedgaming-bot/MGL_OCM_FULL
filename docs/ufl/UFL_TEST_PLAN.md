# UFL Test Plan

Framework for testing the **existing** product. This is not a claim that every case already has an automated test.

Existing automated coverage lives under `mgl/test_*.py` and other app tests. Last noted full suite: **467 tests OK** (re-run locally with production env vars unset):

```bash
env -u DATABASE_URL -u PGHOST -u PGPORT -u PGUSER -u PGPASSWORD -u PGDATABASE -u RAILWAY_ENVIRONMENT python3 manage.py test
```

Do not run destructive management commands against production as a “test”.

---

## How to use this plan

For each feature: visitor path, signed-in path, forbidden path, and a database assertion where money, ownership, or official stats move.

Mark results: PASS / FAIL / BLOCKED / N/A.

---

## Public visitor

- [ ] `/` is Public Home (compact header). No MY TEAM, MARKET, notify dropdown.
- [ ] Nav: HOME, LEAGUES, CLUBS, FIXTURES, TABLES, STATISTICS, JOBS, JOIN UFL / LOGIN.
- [ ] Leagues, clubs, club pages, rules, jobs, live activity, pressroom, stats, history, public transfers load.
- [ ] `/mgl/hub/` and `/market/` redirect to Job Centre.
- [ ] Released fixture detail is visible; unreleased fixture 404s.
- [ ] `/stats/compare/` is 404.
- [ ] Cup slugs show Coming soon, not invented scores.
- [ ] Register and login work; CSRF on POSTs.

---

## Member (signed in, not appointed)

- [ ] `User.role` is MANAGER but `ufl_access_role` is MEMBER if application pending or no `managed_team`.
- [ ] `/` is Public Home if application not approved; approved-but-unassigned goes to hub (`home()` uses `approved_manager` only).
- [ ] Career URLs → Job Centre while application PENDING.
- [ ] Cannot complete `apply_for_club` until application APPROVED.
- [ ] Cannot sell, buy, scout, or submit.
- [ ] Can log out and read public pages.

---

## Manager (approved + assigned)

- [ ] `/` redirects to `/mgl/hub/`.
- [ ] Hub shows personal balance, outstanding fixtures, pending actions, resign, notify bell.
- [ ] Team page: only own squad; list, release request, auction own players.
- [ ] Cannot mutate another club’s players (direct POST).
- [ ] Submit result only for own released fixtures.
- [ ] Opponent Accept/Reject does not officialise.
- [ ] Transfer: list LIVE; offer; accept → PENDING; player still at club until Control approve.
- [ ] Listing caps 5 and 3/24h enforced.
- [ ] Buy own player rejected.
- [ ] Sign free agent 0 TKN; cannot sign unassigned as FA.
- [ ] Scout: one active; recruit respects 28 cap.
- [ ] Youth Academy shows COMING SOON.
- [ ] Control URLs redirect to hub.
- [ ] Site Management → 403.

---

## Admin

- [ ] Control Centre loads.
- [ ] Can approve/reject results, transfers, press, jobs, manager apps, releases, awards.
- [ ] Cannot approve starting squads (`approve_proposal` Owner-only).
- [ ] Cannot override opponent-accept without Owner + `override=1`.
- [ ] Token adjust writes `RewardTransaction`.
- [ ] Site Management display edits do not change IDs, squads, tokens, or `badge_code`.
- [ ] Django `/admin/` only if `is_staff`.

---

## Owner

- [ ] All Admin Control actions.
- [ ] Starting-squad generate is preview-only; approve with confirm assigns and locks season.
- [ ] Second approve same season rejected.
- [ ] Match approve with `override=1` works when opponent has not accepted.
- [ ] Reject starting-squad draft does not assign players.
- [ ] FC26 id/overall unchanged after approve.

---

## Authentication

- [ ] Unknown user cannot POST career actions (redirect login).
- [ ] Logout clears session.
- [ ] Duplicate username/email rejected on register.
- [ ] Tokens granted once at register (`starting_tokens()`).
- [ ] No password-reset route (confirm still absent).

---

## Authorisation

- [ ] Swap session cookies between Manager A and Manager B: A cannot release B’s player.
- [ ] Member cannot hit Control POST URLs.
- [ ] Manager cannot hit Site Management POST URLs (403).
- [ ] Face URL is public; does not leak other PII beyond the public player card.

---

## Career Mode

- [ ] Resign: squad remains; tokens remain; spell row written.
- [ ] Re-appoint: scout level persists.
- [ ] Hub forbidden extra cards absent (Academy / H2H / Propose Transfer **cards**).
- [ ] Youth Academy may appear in header only.

---

## Clubs and players

- [ ] Club page slug works; badge_code stable after display rename.
- [ ] Player profile career-gated; public club page still shows squad.
- [ ] FC26 name/id not rewritten by Site Management.

---

## Transfers and tokens

- [ ] Double-submit offer does not double-reserve incorrectly.
- [ ] Approve sale: buyer debit, seller credit, one SOLD listing, ownership history.
- [ ] Reject sale: no token move, player stays.
- [ ] Auction outbid refunds previous bidder.
- [ ] Window hook: while it returns True, list/buy allowed.

---

## Fixtures, results, statistics

- [ ] Pending result: table unchanged; public stats unchanged.
- [ ] Approve: table, player stats, career W/D/L, 1 TKN per side, news, press questions.
- [ ] Double approve: second is no-op.
- [ ] Locked season: approve refused.
- [ ] Rollback reverses official apply.

---

## Notifications, news, Live Activity, Pressroom

- [ ] Action cards only for the recipient.
- [ ] Mark read / read-all scoped to user.
- [ ] Live Activity shows published football posts; empty state works.
- [ ] Unapproved press not shown as official.
- [ ] Approve press pays within 24h cap.

---

## Mobile and desktop

- [ ] Public Home 390 / 768 / 1024 / 1280 / 1440 / 1920: header not cropped; gold CTA visible.
- [ ] Inner logged-in header matches Public Home compact scale (52 / 44 / 11 / 34). No page-body shrink.
- [ ] Burger menu opens/closes; backdrop works.
- [ ] Hub outstanding fixtures scroll after 8.
- [ ] Tables horizontally sane on small screens (no whole-site zoom).

---

## Security

- [ ] CSRF rejected without token.
- [ ] Control and Site Management gates as above.
- [ ] DEBUG false in production; secret not `django-insecure-`.
- [ ] Unassigned → auction forbidden for managers (403).
- [ ] Face proxy: invalid id 404; missing file silhouette.

See `UFL_SECURITY_RULES.md` for issues **not** to “fix” during a test pass unless asked.

---

## Database integrity

- [ ] No test run against production.
- [ ] Local tests use SQLite (unset `DATABASE_URL`).
- [ ] Migrations apply clean on empty DB; do not `makemigrations` unless a model change was requested.
- [ ] After fixture tests: `RewardTransaction` balances match `ManagerApplication.tokens`.
- [ ] Unique pending release per player.
- [ ] StartingSquadLock unique per season.

---

## Automated tests to keep green

When changing nav/header/hub/home, run at least:

- `mgl.test_ufl_structure`
- `mgl.test_nav`
- `mgl.test_hub_dashboard`
- `mgl.test_ia`
- relevant `mgl.test_scouting` / market tests if those modules change

Do not “fix” tests by removing required copy needles (`PENDING ACTIONS`, `COMING SOON`, `'<nav class="mgl-nav"'`, etc.) unless the Owner changes the product.
