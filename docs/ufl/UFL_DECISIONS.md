# UFL Decisions

Decisions come from **code that still matches the product**, **existing documentation that still matches the code**, and **Owner Phase 1 locks (2026-09-01)**.

Phase 1 items are **STATUS: LOCKED**. Do not reinterpret them.

Where Phase 1 and current code disagree, both are recorded. The locked rule wins as product intent. The code is not changed in a documentation pass.

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

**CONFIRMED (code) + PHASE 1 AMENDMENT**

Official results, **transfer requests**, press rewards, job appointments, and awards require Owner/Admin. Starting squads require Owner. Opponent/seller accept is not official.

**Phase 1 LOCKED:** **player listings** and **release listings** do **not** require Admin/Owner approval. **IMPLEMENTED (Phase 4):** manager release is immediate and does not wait for Control. Leftover PENDING `PlayerReleaseRequest` rows can still be reviewed.

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

**CONFIRMED (mechanism) + PHASE 1 AMENDMENT**

Preview-only until Owner confirm. `StartingSquadLock` prevents a second apply in the same season. Legacy 14×26 command is a different path. **Do not clear StartingSquadLock.**

**Phase 1 LOCKED structure is 30 players.** CURRENT CODE generator is the locked 30-player shape. Production allocation has not been applied. Season 1 bootstrap apply is blocked.

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

### DEC-015 — Listing/auction frequency caps (code defaults)

**CONFIRMED in code; not restated in Phase 1**

`LeagueSettings` defaults: 5 active listings, 3 listings / 24h, 3 manager auctions / 24h.

Roster: **Phase 1 LOCKED 30**. Code `max_squad_size` / `effective_roster_limit` now resolve to at least 30.

Whether the 5 / 3 / 3 caps stay is **UNDECIDED** (not in Phase 1).

### DEC-016 — Free agents sign for 0 TKN; unassigned ≠ free agent

`sign_free_agent` and `Player.is_free_agent` help_text. **Superseded in detail by DEC-042** (unsigned ≠ FA; do not trust the stored flag as product status).

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

**STATUS: NEEDS OWNER VISUAL CONFIRMATION** — a CSS pass shipped; Owner has not confirmed the current appearance. Not a new functional rule.

### DEC-022 — Cups and Youth Academy are Coming Soon until a live system exists

`coming_soon.html` / `competition_page` flags. Do not invent scores.

### DEC-023 — Compare and Waiting Room are removed

`/stats/compare/` raises 404. Not in navigation.

---

## Phase 1 Owner locks (2026-09-01)

All items below: **STATUS: LOCKED**.

### DEC-024 — Transfer window never closes

No automatic closing period. Window remains open continuously. Code hook already returns True.

### DEC-025 — Listings and release listings do not require approval

Player listings and release listings go live without Admin/Owner approval.

**Code match:** listings already LIVE immediately.  
**Code GAP:** releases still use `PlayerReleaseRequest` + Control.

### DEC-026 — Transfer requests require approval before official/live

Seller/manager negotiation is not enough. Admin/Owner must approve the request before the transfer is official. Matches current PENDING → `approve_listing` path.

### DEC-027 — Admin/Owner control pack availability

Packs may be added, removed, released, replaced, changed, made temporarily available, or made unavailable (regular / high / lower rating, random position, drops, future types).

### DEC-028 — Pack opening limits are configurable per pack

Each pack has its own maximum openings (examples: 1, 2, or another configured limit). The system must eventually enforce that limit. **Not confirmed as a Pack model field today.**

### DEC-029 — Pack and token costs use 0.5 increments only

Valid: 0, 0.5, 1, 1.5, 2, … Invalid: 0.25, 0.75, 1.25, 1.75. Applies to UFL tokens generally, including pack/recruitment costs. **Code does not currently validate this.**

### DEC-030 — Official starting squad is 30 players with locked positions

Every new season/reset:

2 GK, 4 CB, 2 RB, 2 LB, 2 RWB, 2 LWB, 2 CDM, 2 CM, 2 CAM, 2 LM, 2 RM, 2 LW, 2 RW, 2 ST.

Roster limit 30. Current production squads are **not** this structure.

### DEC-031 — Starter league is 16 Premier / 14 Championship / 8 League One

38 clubs total. Clubs initially randomly generated as the starter setup.

### DEC-032 — Admin can change club names/logos/branding

At any point, including when a new manager takes over. Site Management already supports display name/logo edits; `badge_code` remains the frozen crest key in code.

### DEC-033 — Current 14 Premier League clubs are test data

Not the final UFL league structure. Mixed player counts/positions. Nothing currently locked. Production is live; only the Owner currently has visibility/access. Do not reset as part of docs or ordinary work.

### DEC-034 — Matches are played on the virtual game; UFL manages official league data

Website is squad, transfers, scores, statistics, fixtures, and Career Mode record-keeping. The virtual game is where the match is played.

### DEC-035 — Website, database, and Discord/outbox stay synchronised

Database is the central source of truth. Approved website updates should be reflected by the Discord bot/outbox.

### DEC-036 — Weekly rewards run Sunday 10:00 AM to Sunday 10:00 AM

Time zone **NEEDS OWNER DECISION** (not specified in Phase 1).

### DEC-037 — Locked weekly and cup token amounts

- Approved league game: **+1 TKN**
- TOTW: **+0.5 TKN per selected player** from that manager’s team
- Press conference answer: **+0.5 TKN**
- Manager of the Week: **+1 TKN**
- Weekly top goalscorer (manager of #1): **+0.5 TKN**
- Weekly top assists (manager of #1): **+0.5 TKN**
- Cup winner: **+10 TKN**
- Cup runner-up: **+5 TKN**

No other cup placing is locked. Match-approve already pays +1 in code. Other amounts **not confirmed as implemented**.

### DEC-038 — Job applications require Admin acceptance before appointment

**STATUS: LOCKED** (superseded in detail by DEC-041)

MEMBER → submits job application → Admin reviews → Admin accepts → member gets the job.

Required fields: EA ID / gamertag, Discord username, games per week **1–3 / 3–5 / 6+**, referred by, new-gen confirmation (“I confirm I am playing on a new-generation console.”).

### DEC-039 — Django `/admin/` remains

Keep it if it is the appropriate administrative control tool. Do not remove it.

### DEC-040 — Scout/recruitment setting must enforce

`LeagueSettings.scout_can_recruit` (and related configured restrictions) must actually apply. CURRENT CODE: `scout_can_recruit()` hard-codes True.

### DEC-041 — Job Application is the single application process

**STATUS: LOCKED** (Owner, 2026-09-01)

The UFL Job Application is the **only** application Admin reviews for a club/manager job.

Official workflow:

1. MEMBER
2. Submits **Job Application**
3. Admin reviews that Job Application
4. Admin accepts
5. Member gets the job
6. Member becomes the appropriate manager / job holder under existing Career Mode structure (`Team.manager`, etc.)

There is **no** additional manager-application approval stage between submit and Admin accept.

Official fields (user-facing):

| Field | Locked value |
|---|---|
| EA ID / Gamertag | Required |
| Discord | **Username** (not a numeric Discord ID) |
| Games per week | Dropdown **1–3** / **3–5** / **6+** only |
| Referred by | Present |
| New-gen console | Checkbox confirming new-generation console |

Do **not** use 1 / 2 / 3 / 4 / 5+ as the official options.

**IMPLEMENTED (Phase 4):** registration still creates a `ManagerApplication` identity/token row (not a second job-review gate). A Member with a PENDING identity can submit the Job Application. Admin accept of that Job Application atomically approves the identity if needed and assigns the club. Form fields are Discord username and games-per-week **1–3 / 3–5 / 6+**. Optional numeric Discord ID may be stored on `User.discord_id` without replacing the username.

### DEC-042 — Unsigned ≠ Free Agent; Season 1 uses the unsigned pool

**STATUS: LOCKED** (Owner, 2026-09-01)

An FC26 player with no current UFL club is **UNSIGNED**, not automatically a UFL Free Agent.

Do **not** treat `Player.is_free_agent=True` as the product status. The current database flags many unused FC26 rows as Free Agents. Do **not** mass-edit those ~18,000 flags to make generators or pages work.

UFL statuses the application must distinguish:

| Product status | Meaning |
|---|---|
| FC26 master / unsigned | In the FC26 database, no UFL club. Recruitment pool. |
| UFL Free Agent | Entered FA through an explicit UFL process only |
| Club-owned | `mgl_team` set |
| Temporarily in a manager auction | Leaves available squad selection; unsold **returns to the original club** |

Unsigned players become available through Recruitment Packs, Scouting, and Admin-released auctions. Managers can win them there.

The public Free Agents page must **not** list every unassigned FC26 player. FA examples: rejected/released from a pack, rejected/released after scouting, admin-released auction with no bids, other explicit FA processes.

Admin/Owner may auction an unsigned player. No bid → that player **may** become a UFL Free Agent.

Manager club auction: if sold, original club → new club. If no sale, player **returns to the original club**. Do not make an unsold manager-auction player a Free Agent. **CURRENT CODE** already restores `listing_kind=CLUB` auctions to `origin_team` (`_restore_unsold_player`). Keep that path; do not invent a second auction system.

**Season 1 starting-squad eligibility (bootstrap only):**

- UNSIGNED FC26 players are eligible **regardless of** the stored `is_free_agent` flag.
- That does **not** publish them as public UFL Free Agents.
- `RB` may fill **RB or RWB**. `LB` may fill **LB or LWB**.
- OVR band remains 64–69.
- After Season 1 squads are established, the normal status system applies.

Scout upgrades (tokens reducing hours by a percentage) and pack catalogue remain Owner/Admin-controlled. `scout_can_recruit` must still enforce (DEC-040). Pack/scouting catalogue work is **not** implemented in this pass.

**CURRENT CODE (2026-09-01):** Season 1 generator uses UNSIGNED eligibility and the RB/LB wing-back mapping. Genuine UFL Free Agents are players with `released_at` set by an explicit UFL process. The public Free Agents page no longer lists unused FC26 rows. Production Season 1 apply/approve remains fenced.

---

## Not decisions (still open)

- Promotion / relegation
- Stored MEMBER role
- Whether `Team.tokens` remains a live economy
- Listing/auction frequency caps (5 / 3 / 3) — code defaults only
- Time zone for Sunday 10:00 AM
- Monthly awards (code exists; not in Phase 1 weekly table)
- Logged-in header appearance — **NEEDS OWNER VISUAL CONFIRMATION** (not a rule lock)
