# UFL Master Specification

**Status:** Source of truth. Includes the live-code audit **and** Owner Phase 1 locked rules (1 September 2026).  
**Audited tree:** production Django application (`MGL_OCM_FULL`, branch `main`).  
**Scope:** documentation only unless a later task explicitly asks to implement a rule.

This document is the project source of truth. Before any future UFL change, follow the development rule at the end of this file.

**How to read this file**

| Layer | Meaning |
|---|---|
| **PHASE 1 LOCKED** | Official UFL product rules from the Owner. Do not reinterpret. |
| **CURRENT CODE** | What the Django application actually does today. |
| **CURRENT PRODUCTION / TEST STATE** | The live 14-club setup. Test/development data. Not the final league. |
| **GAP** | Locked rule and current code/data disagree. Do **not** implement the gap in a docs-only task. |

---

## PROTECTED SYSTEMS — DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION

A design or content task must not become a data or logic rewrite. Do not change, reset, delete, or “clean up” any of the following unless the Owner explicitly asks:

- Existing Career Mode data (applications, club spells, career stats, rewards, notifications)
- FC26 identities (`Player.fc27_id`, names, source ratings, faces, individual FC attributes)
- Tokens (`ManagerApplication.tokens` and the `RewardTransaction` ledger)
- Owner starting-squad approval state (`StartingSquadProposal`, `StartingSquadLock`)
- Authentication (`accounts.User`, login/register/logout, session cookies)
- Existing database records, including current test clubs, mixed squads, fixtures, results, and statistics
- Existing manager/club relationships (`Team.manager`, `ManagerApplication`, `ManagerClubSpell`)
- Existing player data
- Existing working functionality (routes, approval workflows, market, fixtures, Discord outbox)

Internal `/mgl/` URL prefixes and `mgl_*` identifiers may remain. Users must see **UFL**.

Do not reset the current 14-club test production as part of documentation or design work. The live system stays as-is until the Owner explicitly asks to rebuild toward the 38-club / 30-player structure.

---

## PHASE 1 — LOCKED UFL RULES (Owner, 2026-09-01)

These are official product rules. Status: **LOCKED**. Current code may not match yet; see GAP notes and `UFL_DECISIONS.md`.

### Virtual game and website

UFL matches are played on the external/virtual football game. The website is the league-management and record-keeping system around those matches. Managers play the match on the virtual game; they use the website for squad, transfers, scores, statistics, fixtures, and other Career Mode actions. The UFL database is the central source of truth. When an approved website update occurs, the Discord bot/outbox should reflect it. Club website data and related UFL systems should remain synchronised.

### Transfer window

The transfer window **does not close**. It remains open continuously. There is no automatic closing period. **Transfer requests** still require Admin/Owner approval before they become official/live.

### Listings vs transfer requests vs releases

| Action | Admin/Owner approval required to go live/official? |
|---|---|
| Player listings (list for sale) | **No** |
| Release listings | **No** |
| Transfer requests (buy/offer that completes a move) | **Yes** — must be approved before official/live |

Do not describe all market activity as requiring approval.

### Player status (DEC-042 LOCKED)

An FC26 player with no UFL club is **UNSIGNED**, not a UFL Free Agent. Do not mass-edit `is_free_agent` on the FC26 master set. The Free Agents page lists only players who entered FA through an explicit UFL process (pack/scout reject-release, no-bid **admin** auction, other approved FA paths). Unsigned players are the recruitment pool (packs, scouting, admin auctions). Manager club auctions: sold → new club; no sale → **return to the original club**.

**Season 1 starting squads only:** unsigned players are eligible regardless of the stored `is_free_agent` flag; `RB` may fill RB/RWB; `LB` may fill LB/LWB; OVR 64–69. That does not publish them as public Free Agents.

**CURRENT CODE:** the generator implements that eligibility and mapping. Genuine UFL Free Agent status is `Player.released_at` (set only by an explicit UFL process). The public Free Agents page uses that status, not the unused FC26 `is_free_agent` flags. Production Season 1 apply/approve remains fenced.

### Scouting / packs / recruitment

Admin/Owner control which packs are available. Packs may be added, removed, released, replaced, changed, made temporarily available, or made unavailable (regular rating, high rating, lower rating, random position, drops, future types). Each pack can have its **own** configurable maximum number of openings (example: Pack A = 1, Pack B = 2). The system must eventually enforce that limit. Pack/recruitment **token costs use 0.5 increments only** (0, 0.5, 1, 1.5, …). Invalid: 0.25, 0.75, 1.25, 1.75. The existing scout safety/recruitment setting (`LeagueSettings.scout_can_recruit`) **should actually enforce** configured restrictions. Managers may spend tokens to upgrade scouting (shorter hours). Catalogue remains Owner/Admin-controlled.

### Starting squad (official, every new season / reset)

**30 players** per club. Roster limit **30**.

```
2 GK, 4 CB, 2 RB, 2 LB, 2 RWB, 2 LWB,
2 CDM, 2 CM, 2 CAM, 2 LM, 2 RM, 2 LW, 2 RW, 2 ST
```

Current production squads are **not** this structure.

### Starter league structure (official)

| Division | Clubs |
|---|---|
| Premier League | 16 |
| Championship | 14 |
| League One | 8 |
| **Total** | **38** |

Clubs are initially randomly generated as the starter setup. Admin must be able to change club name, logo, and branding/identity where supported at any time (including when a new manager takes over).

### Current production / test state (not the final league)

- 14 clubs exist; all are Premier League.
- They are **test/development data**.
- They do **not** have the final 30-player starting structure; player counts/positions are mixed.
- Nothing is currently locked (`StartingSquadLock` / final structure not applied as the official 30s).
- The production system is live. Only the Owner currently has visibility/access to this live production setup.
- **Do not reset this data** unless the Owner explicitly asks.

### Tokens

Official UFL currency. Values use **0.5 increments only**.

### Weekly rewards (Sunday 10:00 AM → next Sunday 10:00 AM)

| Reward | Amount |
|---|---|
| Approved league game | +1 TKN |
| Team of the Week | +0.5 TKN per selected player from that manager’s team |
| Press conference answer | +0.5 TKN |
| Manager of the Week | +1 TKN |
| Weekly top goalscorer (manager of #1) | +0.5 TKN |
| Weekly top assists (manager of #1) | +0.5 TKN |
| Cup winner | +10 TKN |
| Cup runner-up | +5 TKN |

No other cup placing is locked unless decided later.

### Jobs

The Job Application is the **single** application process (DEC-041). MEMBER submits a Job Application → Admin reviews that application → Admin accepts → member gets the job and becomes the manager / job holder. **No** extra manager-application approval stage.

Fields: EA ID / gamertag, Discord **username** (not numeric ID), games per week (**1–3 / 3–5 / 6+** only), referred by, new-gen confirmation (“I confirm I am playing on a new-generation console.”). Do not invent extra mandatory fields.

**CURRENT CODE / GAP TO IMPLEMENT:** separate `ManagerApplication` still exists and must be APPROVED before `apply_for_club`; form still uses numeric Discord ID and 1 / 2 / 3 / 4 / 5+.

### Django `/admin/`

Retained. Do not remove it.

### Global design

One UFL identity. Structure: UFL Header → UFL Live Activity → Page Header → Page Content. Public Home may keep its dedicated compact header. Inner pages use the shared header. Do not create duplicate unrelated headers.

Logged-in header scale: CSS pass already shipped. Status: **NEEDS OWNER VISUAL CONFIRMATION**. Not a new functional rule.

---

## What UFL is

**PHASE 1 LOCKED**

Ultimate Fantasy League (UFL) is the league-management website for an EA FC 26 Career Mode football league. Matches are played on the external/virtual game. The website stores official UFL state (clubs, squads, transfers, scores, statistics, fixtures).

- Managers apply for clubs, receive a personal token balance, run a squad, list and buy players, scout, open recruitment packs, submit match results, and answer press questions.
- Owner and Admin approve **results**, **transfer requests**, **job applications**, **press answers**, and **awards**. Starting squads remain Owner-gated in code. **Player listings** and **release listings** do **not** require Admin/Owner approval (Phase 1 lock). **CURRENT CODE still requires Control approval for releases** — GAP, do not implement in this pass.
- The **website/database is the source of truth**. Discord is an outbox: official events are queued (`DiscordEvent`) and a separate bot process should reflect approved updates.
- User-facing brand is **UFL / Ultimate Fantasy League**. Internal app labels, Python packages, and many URLs still use `mgl` so existing Railway, Discord, and test links keep working.

**UNKNOWN / UNDECIDED**

- Whether the public product name will ever drop the internal `mgl` URL prefix.
- Public canonical hostname if not the Railway default.

---

## Overall architecture

**LOCKED / CONFIRMED**

| Layer | Implementation |
|---|---|
| Framework | Django `>=6.1,<6.2` (server-rendered templates, no React, no DRF) |
| Apps | `core`, `accounts`, `leagues`, `teams`, `managers`, `players`, `auctions`, `mgl` |
| Frontend | Django templates + CSS/JS (`core/static/core/css/`, `core/templates/`) |
| Backend | Django views and service modules under `mgl/`, `managers/`, `auctions/` |
| Database | Local SQLite `db.sqlite3`; production PostgreSQL via `DATABASE_URL` or `POSTGRES_*` |
| Auth | Django session auth; `AUTH_USER_MODEL = accounts.User` |
| Static | WhiteNoise in production; Django finders in DEBUG |
| Media | Filesystem `MEDIA_ROOT`; Django serves media when DEBUG or `DJANGO_SERVE_MEDIA=true` |
| Process | Gunicorn WSGI (`gunicorn.conf.py`, default 2 workers) |
| Discord | Separate process (`run_mgl_bot.py`); not started by Gunicorn |
| Deploy | Railway (`railway.toml` `releaseCommand = "true"`) |
| Live host (from prior ops notes) | `https://mglocmfull-production.up.railway.app/` — **NEEDS CONFIRMATION** if the public hostname has changed |

There is **no REST API framework**. Closest HTTP surfaces are HTML views, a notification panel fragment, and the player-face proxy `/mgl/players/<id>/face/`.

There is **no custom Django middleware**. Stack is Security → WhiteNoise → Session → Common → CSRF → Auth → Messages → XFrame.

---

## Current technology (detail)

**LOCKED / CONFIRMED**

- Python Django project (`manage.py`, `config/settings.py`, `config/urls.py`, `config/wsgi.py`)
- Dependencies: Django, Pillow, python-dotenv, WhiteNoise, Gunicorn, psycopg, optional discord.py (`requirements-mgl.txt`)
- Email: console backend in DEBUG; SMTP when `DJANGO_DEBUG=false` unless overridden
- Production HTTPS/HSTS/secure cookies when `DJANGO_DEBUG=false`
- `LOGIN_URL=/login/`; `LOGIN_REDIRECT_URL=/`; `LOGOUT_REDIRECT_URL=/`
- Context processor: `mgl.context_processors.mgl_nav`
- Tests: Django test suite (`mgl/test_*.py` and others). Last recorded local run in prior work: **467 tests OK**. Re-run before treating that number as current.

---

## Major systems

| System | Status | Where |
|---|---|---|
| Public Home | Complete (isolated compact page) | `core/templates/core/home.html`, `ufl-public-home.css` |
| Shared inner chrome | Complete | `core/templates/core/base.html`, `ufl-system.css`, `ufl-pages.css` |
| Auth register/login/logout | Complete | `managers/urls.py`, `accounts.User` |
| Job Centre / club applications | Complete | `/jobs/`, `ClubApplication` |
| Career hub / team / fixtures | Complete | `/mgl/hub/`, `/mgl/team/`, `/mgl/fixtures/` |
| Transfer market + requests | Complete | `mgl/market.py`, `/market/` |
| Free agents | Complete | `/mgl/free-agents/`, `sign_free_agent` |
| Auctions | Complete | `auctions` app, `/auctions/` |
| Recruitment Drive | Complete | `/market/recruitment/` |
| Scouting | Complete | `/market/scouting/`, `mgl/scouting.py` |
| Youth Academy | Placeholder only | `/market/youth-academy/` → `coming_soon.html` |
| Cups | Structure pages only | `competition_page` + `COMPETITIONS` slugs |
| Match submit + opponent inbox | Complete | `submit_match`, `ManagerNotification` |
| Official results / tables / stats | Complete | `mgl/match_official.py` |
| Pressroom | Complete | `/news/pressroom/` |
| Live Activity / Newsroom | Complete | `/news/activity/` |
| Notifications | Complete | `/mgl/notifications/` |
| Control Centre | Complete | `/mgl/control/` |
| Site Management | Complete | `/mgl/control/site/` |
| Starting squads | Code: 25-player UFL generator + Owner lock. **Phase 1 locked structure is 30.** | `mgl/ufl_starting.py` |
| Legacy 14×26 apply command | Exists; do not use for the locked 30s | `apply_starting_squads` |
| Discord outbox | Complete | `DiscordEvent` + bot |
| Loans | **Not implemented** | — |
| Transfer window | **Phase 1 locked: never closes.** Code hook always returns True | `transfer_window_is_open()` |
| Player compare / Waiting Room | Removed (404) | `/stats/compare/` |

---

## User hierarchy

**LOCKED / CONFIRMED**

Database role enum (`accounts.User.role`) has only three values:

- `OWNER`
- `ADMIN`
- `MANAGER` (default on registration)

There is **no `MEMBER` column value**. Capability “Member” is derived in `mgl.ufl_settings.ufl_access_role()`:

| Capability | Meaning in code |
|---|---|
| PUBLIC | Anonymous |
| MEMBER | Signed in, and not (approved manager **and** assigned `managed_team`) |
| MANAGER | Approved `ManagerApplication` **and** `user.managed_team` |
| ADMIN | `User.role == ADMIN` |
| OWNER | `User.role == OWNER` |

Registration creates `User(role=MANAGER, is_active=True)` plus `ManagerApplication(status=PENDING)` with `starting_tokens()` (default **20**).

Career pages use `career_required`: approved manager **or** Owner/Admin; everyone else is redirected to Job Centre.

Control pages use `owner_admin_required`: unauthenticated → login; other roles → hub.

Site Management uses `site_manage_required`: managers get HTTP 403 (`mgl/site_manage/forbidden.html`).

Assigned approved managers who open `/` are redirected to `/mgl/hub/`.

See `UFL_ROLES_PERMISSIONS.md`.

---

## Career Mode architecture

**LOCKED / CONFIRMED**

One product. Public website and Career Mode share the same Django site, database, and (except Public Home) the same header.

- Tokens live on `ManagerApplication.tokens`.
- Club `Team.tokens` (default 50) is a **club treasury / legacy** field. Help text says it remains with the club if the manager leaves. Personal economy uses manager tokens.
- Authoritative ledger: `credit_manager` / `debit_manager` → `RewardTransaction` (idempotent on category + reference).
- `auctions.TokenTransaction` still exists as a **legacy** table.
- Squads stay with the club on resign; tokens stay with the manager (`resign_manager_from_club` / `ManagerClubSpell`).
- Squad cap: **30.** `UFL_ROSTER_LIMIT`, `DEFAULT_MAX_SQUAD`, `LeagueSettings.max_squad_size` default, and `effective_roster_limit()` all resolve to at least 30. Legacy stored 28 cannot silently cap a squad.
- Token values: **Phase 1 locked 0.5 increments only.** CURRENT CODE stores `Decimal` with two places and does not reject 0.25 / 0.75. GAP.
- Player identity master is FC26 (`Player.fc27_id`). Do not change IDs, names, or source ratings in ordinary work.
- Starting squads: official **30-player** `UFL_SQUAD_SHAPE`. Control generate is preview-only. Owner approve assigns and creates `StartingSquadLock`. Stacking is rejected. Production 30-player allocation has **not** been applied. Season 1 38-club bootstrap is implemented with apply **blocked** until Owner authorisation.

See `UFL_CAREER_MODE.md`.

---

## Public website

**LOCKED / CONFIRMED**

Public Home (`/`) is an isolated compact page (`body.ufl-home`) with its own header/footer (`public_home_header.html`, `public_home_footer.html`, `ufl-public-home.css`). It must not show MY TEAM, MARKET, Youth Academy, fixture-list career chrome, or `data-notify-dropdown`.

Public Home nav (logged-out / pending): HOME · LEAGUES · CLUBS · FIXTURES · TABLES · STATISTICS · JOBS, plus gold **JOIN UFL / LOGIN**.

All other pages use `core/templates/core/base.html`:

**UFL → Home · My Team · Market · Leagues · Cups · Job Centre · Stats · History**

(plus Control Centre for Owner/Admin; notification bell and profile for signed-in career users.)

Public-readable pages include leagues, clubs, fixtures/tables (released data), stats, jobs, rules, live activity, pressroom, hall of fame, manager search, public transfers, and released fixture detail.

---

## Authentication

**LOCKED / CONFIRMED**

- Register: `/register/` (`manager_register`) — creates User + pending `ManagerApplication`. No email verification in code.
- Login: `/login/` (Django `LoginView`, `managers/login.html`)
- Logout: `/logout/` (Django `LogoutView`)
- Optional unique `User.discord_id`
- Standard Django password validators
- CSRF on all POST forms

**UNKNOWN / NEEDS CONFIRMATION**

- Whether production uses any extra auth (Discord OAuth, 2FA). **Not present in this repo.**
- Password-reset views: **not found** in `managers/urls.py`.

---

## Database

See `UFL_DATABASE_RULES.md`. Summary:

- Custom user, leagues, teams, players (FC26), manager applications, fixtures/submissions/stats, listings, auctions, rewards, notifications, news, press, scouting, starting-squad proposals/locks, league settings, Discord events.
- Legacy/unused: `core.Club` (separate from `teams.Team` — **do not assume it is live Career Mode**).

---

## Admin

**LOCKED / CONFIRMED**

Two admin surfaces:

1. **Django admin** `/admin/` — **Phase 1 LOCKED: retained.** Staff/superuser. Includes match-approval actions that call the same `approve_match_submission` path. Do not remove it.
2. **UFL Control Centre** `/mgl/control/` — Owner/Admin only (`owner_admin_required`). Queues for scores, transfers, press, managers, jobs, releases (code still queues releases; Phase 1 says release listings should not need this), awards, tokens, scouting exceptions, auctions, clubs, notifications, logs, season, league, starting squads.

---

## Owner

**LOCKED / CONFIRMED**

Owner has Admin capabilities plus:

- Approve official UFL starting-squad proposals (`approve_proposal` requires `is_owner` and explicit confirm)
- Override opponent-accept on match approval (`override=1` and `role == OWNER`)

Owner and Admin both use `User.role`. Superuser flags on Django admin are separate Django staff flags.

---

## Approval system

See `UFL_APPROVAL_SYSTEM.md`.

**Phase 1 locked:** listings and release listings do **not** need Admin/Owner approval. Transfer requests **do**. Job applications **do**. Match results **do**.

**CURRENT CODE:** listings go LIVE without Control. Transfer requests still need Control after seller accept. **Releases still need Control** (`PlayerReleaseRequest`) — GAP vs Phase 1.

Owner/Admin also approve press, awards, and (Owner only) starting-squad apply. Opponent Accept/Reject on a result does **not** make the result official.

---

## Security

See `UFL_SECURITY_RULES.md`. Do not “fix” issues from this audit unless asked.

---

## Global navigation

**LOCKED / CONFIRMED** (`mgl/nav.py`, `base.html`, Public Home header)

| Surface | Nav |
|---|---|
| Public Home | Custom compact: HOME, LEAGUES, CLUBS, FIXTURES, TABLES, STATISTICS, JOBS |
| Shared inner (public visitor) | HOME, LEAGUES, CUPS, JOB CENTRE, STATS, HISTORY |
| Shared inner (signed-in career) | HOME, MY TEAM, MARKET, LEAGUES, CUPS, JOB CENTRE, STATS, HISTORY, (+ CONTROL for Owner/Admin) |

Job Centre is a top-level link inserted after Cups, not a dropdown.

Youth Academy appears under MARKET as Coming Soon.

---

## Global UI

**LOCKED / CONFIRMED**

- One UFL visual identity: near-black + gold `#e4c77a`, Barlow Condensed + Manrope
- Global structure: UFL Header → UFL Live Activity → Page Header → Page Content
- Global LIVE ACTIVITY bar (`live_activity_bar.html`)
- Common page header include `core/includes/mgl_page_header.html`
- Public Home isolated compact header (intentional); inner pages share `base.html`

See `UFL_DESIGN_SYSTEM.md`. Logged-in header scale: **NEEDS OWNER VISUAL CONFIRMATION**.

---

## Existing integrations

**LOCKED / CONFIRMED**

- **Discord bot** (optional, separate process): `DISCORD_TOKEN`, `UFL_CHANNELS` / legacy `MGL_CHANNELS`
- **Public Discord invite:** `DISCORD_INVITE_URL` (empty hides JOIN DISCORD buttons)
- **Hardcoded Job Centre invite** in `mgl/job_applications.py`: `JOBS_DISCORD_INVITE = "https://discord.gg/Jmf29wBafP"` (separate from settings)
- **Sofifa / FC26 faces:** player-face proxy caches PNGs under `media/player_faces/`
- **FC26 CSV import:** `fc26_players_mgl.csv`, `fc26_players_raw.csv`, management commands
- **Railway** host + Gunicorn
- **Google Fonts** loaded from templates

**UNKNOWN / NEEDS CONFIRMATION**

- Production Discord channel IDs and whether the bot process is currently running
- Whether a CDN or object store is used for media in production (code is filesystem)

---

## Environment / configuration

See `.env.example` and `config/settings.py`. Important variables:

| Variable | Role |
|---|---|
| `DJANGO_DEBUG` | Default `true` locally |
| `DJANGO_SECRET_KEY` | Required in production; must not be `django-insecure-` |
| `DJANGO_ALLOWED_HOSTS` | Required when DEBUG is false |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Scheme + host |
| `DATABASE_URL` / `POSTGRES_*` | Production Postgres |
| `DJANGO_SERVE_MEDIA` | Serve uploads from the app process |
| `DJANGO_EMAIL_BACKEND` / `EMAIL_*` | SMTP in production |
| `GUNICORN_BIND` / `GUNICORN_WORKERS` / `PORT` | Process bind |
| `DISCORD_TOKEN` / `UFL_CHANNELS` | Bot |
| `DISCORD_INVITE_URL` | Public invite buttons |

League rules that must not be hard-coded in frontend JS live in `LeagueSettings` / `mgl.ufl_settings`.

---

## Deployment

**LOCKED / CONFIRMED**

- Persistent WSGI process, not serverless/Vercel
- `railway.toml`: `releaseCommand = "true"` (no migrate-on-release in that file)
- `gunicorn.conf.py`: bind `GUNICORN_BIND` or `0.0.0.0:$PORT`, default 2 workers
- Collectstatic + WhiteNoise for static files
- **No Procfile** in the repo root

---

## LOCKED / CONFIRMED versus UNKNOWN / UNDECIDED

### PHASE 1 LOCKED (Owner)

- Transfer window never closes
- Listings and release listings do not require Admin/Owner approval
- Transfer requests require Admin/Owner approval before official/live
- Admin/Owner control pack availability; per-pack opening limits; 0.5-increment pack costs
- `LeagueSettings.scout_can_recruit` must actually enforce
- Official starting squad is **30** with the locked positional structure
- Starter league is **16 / 14 / 8** (38 clubs); Admin can change club name/logo/branding
- Current 14 Premier League clubs are **test data**, not the final structure
- Tokens use 0.5 increments only
- Matches on the virtual game; website/DB official; Discord outbox should stay in sync
- Weekly rewards Sunday 10:00 AM → Sunday 10:00 AM, with the locked token table
- Job applications require Admin acceptance before appointment
- Job Application is the **single** application process (DEC-041); no extra manager-application approval
- Django `/admin/` remains
- One UFL header + Live Activity + page header (Public Home compact exception)

### LOCKED / CONFIRMED in current code (may lag Phase 1)

- Django monolith, UFL brand, website-as-truth
- Role enum OWNER / ADMIN / MANAGER; capability MEMBER
- Career Mode + public site in one product
- Token ledger on `RewardTransaction`
- FC26 identity field `fc27_id`
- Listings 5 / 3-per-24h; manager auctions 3-per-24h (code defaults — **UNDECIDED** whether Phase 1 changes these caps)
- No loans in code
- Transfer window hook already always returns True (matches Phase 1)
- Listings already go LIVE without Control (matches Phase 1)
- Result official only after Owner/Admin approve
- Public Home isolated; one shared inner header
- Youth Academy and cups are coming-soon structure, not live competitions
- Django `/admin/` enabled

### GAP (Phase 1 locked vs current code — do not implement here)

- Code starting shape is **25**; `max_squad_size` default **28**; locked roster is **30**
- Code production clubs: **14 Premier League** test clubs, not 16/14/8
- Code **releases still require** Control approval
- `scout_can_recruit()` **hard-codes True**
- Pack per-opening limits are **not** confirmed as a per-pack configurable field
- Token 0.5-increment **not** enforced by validation
- Job form: games-per-week options and Discord **username vs numeric ID** differ from Phase 1
- Current code also requires an approved `ManagerApplication` before a club job apply — extra step vs **DEC-041** (Job Application is the single process). **GAP TO IMPLEMENT**
- Weekly period Sunday 10:00 AM and the full weekly/cup reward table are **not confirmed as implemented**

### UNKNOWN / UNDECIDED / NEEDS OWNER

- Logged-in header appearance: **NEEDS OWNER VISUAL CONFIRMATION**
- Whether `Team.tokens` is still used for any live payment path
- Whether `core.Club` has any remaining runtime use
- Password reset / email verification
- Public canonical domain if not the Railway default
- Promotion / relegation
- Listing/auction frequency caps (5 / 3 / 3) — present in code; not re-stated in Phase 1
- Time zone for “Sunday 10:00 AM” (**NEEDS OWNER DECISION** — not specified)
- Monthly awards (code exists; not in Phase 1 weekly table)

---

## Development rule (mandatory from now on)

The UFL documentation is the source of truth.

Before making future UFL changes:

1. Read `UFL_MASTER_SPEC.md`
2. Read the relevant subsystem specification
3. Read `UFL_DECISIONS.md`
4. Read `UFL_PROGRESS.md`
5. Inspect the existing implementation
6. Do not invent rules
7. Preserve existing functionality
8. Implement only the requested change
9. Test the change
10. Update the relevant documentation
11. Update `UFL_PROGRESS.md`
12. Update `UFL_CHANGELOG.md`
