# UFL Decisions

Only decisions that can be established from **code, comments, configuration, or existing documentation that still matches the code**.

Assumptions are not listed as decisions.

Format: ID — title — status — evidence.

---

## DEC-001 — One Global UFL Header

**CONFIRMED**

Inner pages share `core/templates/core/base.html` (`.mgl-header.ufl-header`) and `mgl/nav.py`.

**Exception (also confirmed, not a violation):** Public Home uses a dedicated compact header (`public_home_header.html`, `.uh-header`). That page is isolated on purpose.

---

## DEC-002 — One Unified UFL Career Mode Product

**CONFIRMED**

Public website and Career Mode are one Django project and one database. Discord is an outbox only. Users see UFL; `/mgl/` URLs may remain.

---

## DEC-003 — Role hierarchy

**CONFIRMED**

Stored: OWNER > ADMIN > MANAGER.

Capability grid adds PUBLIC and MEMBER (`ufl_access_role`). MEMBER is not a database enum value.

---

## DEC-004 — Manager ownership restrictions

**CONFIRMED**

Managers may only sell, release, auction, and submit results for their own club. They cannot buy their own listed players. Services enforce this.

---

## DEC-005 — Approval workflow

**CONFIRMED**

Official results, completed transfers, releases, press rewards, job appointments, and awards require Owner/Admin. Starting squads require Owner. Opponent/seller accept is not official.

---

## DEC-006 — Existing Career Mode data must be preserved

**CONFIRMED** (product constraint, restated in this audit)

Do not reset applications, spells, fixtures, stats, notifications, or club links in ordinary development.

---

## DEC-007 — FC26 identities must be preserved

**CONFIRMED**

`Player.fc27_id` is the master identity. Import/sync commands are explicit about not rewriting club/token/stat fields unless named. Starting-squad apply checks id and overall.

---

## DEC-008 — Tokens must be preserved

**CONFIRMED**

Personal tokens live on `ManagerApplication.tokens`. Ledger is `RewardTransaction`. Resign does not confiscate tokens. Do not zero balances.

---

## DEC-009 — Owner starting-squad approval must be preserved

**CONFIRMED**

UFL 25-player proposals are preview-only until Owner confirm. `StartingSquadLock` prevents a second apply in the same season. Legacy 14×26 command is a different path.

---

## Additional confirmed decisions

### DEC-010 — Website is source of truth; Discord is outbox

README + `DiscordEvent` queue + separate bot process.

### DEC-011 — User-facing name is UFL; internal `mgl` identifiers may stay

Templates, tests, and `/mgl/` URLs.

### DEC-012 — Public Home is a completed isolated page

Do not redesign `/` or add career chrome to it.

### DEC-013 — Manager Dashboard is a completed page

Do not redesign `/mgl/hub/` or add forbidden hub cards (Academy / H2H / Propose Transfer on the hub body).

### DEC-014 — No loans

Market code and README: loans are not implemented and must not be invented in UI copy.

### DEC-015 — Squad cap 28; listings 5; 3 listings / 24h; 3 manager auctions / 24h

`LeagueSettings` defaults and `ufl_settings.py`.

### DEC-016 — Free agents sign for 0 TKN; unassigned ≠ free agent

`sign_free_agent` and `Player.is_free_agent` help_text.

### DEC-017 — Official stats only after Owner/Admin approve

`match_official.approve_match_submission`; stats pages filter approved.

### DEC-018 — Site Management is display-only for structure

README + `badge_code` help_text: display edits must not rewrite IDs, squads, fixtures, tokens, or player states.

### DEC-019 — `generate_balanced_squads` is disabled

README + management command state. Do not run it.

### DEC-020 — Transfer listings go LIVE without Control pre-approval

`list_player_for_sale` creates `LIVE`. Control approves the **sale** after seller accept.

### DEC-021 — Inner header scale matches Public Home compact chrome

CSS: `--header-h: 52px`, 44px logo, 11px nav, 34px livebar. No page-body transform scale.

### DEC-022 — Cups and Youth Academy are Coming Soon until a live system exists

`coming_soon.html` / `competition_page` flags. Do not invent scores.

### DEC-023 — Compare and Waiting Room are removed

`/stats/compare/` raises 404. Not in navigation.

---

## Not decisions (do not treat as locked)

- Transfer window close dates — hook always True
- Promotion / relegation
- Stored MEMBER role
- Using `LeagueSettings.scout_can_recruit` as a live gate (`scout_can_recruit()` returns True)
- Whether `Team.tokens` remains a live economy
- Remaining logged-in crop versus Owner screenshots
