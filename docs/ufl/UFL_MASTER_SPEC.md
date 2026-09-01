# UFL Master Specification

**Status:** Audit snapshot of the live codebase.  
**Audited tree:** production Django application (`MGL_OCM_FULL`, branch `main`).  
**Date:** 1 September 2026.  
**Scope:** documentation only. This file describes what exists. It does not change the application.

This document is the project source of truth. Before any future UFL change, follow the development rule at the end of this file.

---

## PROTECTED SYSTEMS — DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION

A design or content task must not become a data or logic rewrite. Do not change, reset, delete, or “clean up” any of the following unless the Owner explicitly asks:

- Existing Career Mode data (applications, club spells, career stats, rewards, notifications)
- FC26 identities (`Player.fc27_id`, names, source ratings, faces, individual FC attributes)
- Tokens (`ManagerApplication.tokens` and the `RewardTransaction` ledger)
- Owner starting-squad approval state (`StartingSquadProposal`, `StartingSquadLock`)
- Authentication (`accounts.User`, login/register/logout, session cookies)
- Existing database records
- Existing manager/club relationships (`Team.manager`, `ManagerApplication`, `ManagerClubSpell`)
- Existing working functionality (routes, approval workflows, market, fixtures, Discord outbox)

Internal `/mgl/` URL prefixes and `mgl_*` identifiers may remain. Users must see **UFL**.

---

## What UFL is

**LOCKED / CONFIRMED**

Ultimate Fantasy League (UFL) is a Django website for an EA FC 26 Career Mode football league.

- Managers apply for clubs, receive a personal token balance, run a squad, list and buy players, scout, open recruitment packs, submit match results, and answer press questions.
- Owner and Admin approve results, transfers, job applications, releases, press answers, awards, and (Owner only) official starting squads.
- The **website is the source of truth**. Discord is an outbox only: official events are queued (`DiscordEvent`) and a separate bot process reports them.
- User-facing brand is **UFL / Ultimate Fantasy League**. Internal app labels, Python packages, and many URLs still use `mgl` so existing Railway, Discord, and test links keep working.

**UNKNOWN / UNDECIDED**

- Whether the public product name will ever drop the internal `mgl` URL prefix.
- Whether Championship and League One currently have live clubs/fixtures in production. Code supports those divisions; live row counts were not queried in this audit.

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
| Starting squads (UFL 25) | Complete (Owner approve) | `mgl/ufl_starting.py` |
| Legacy 14×26 apply command | Exists; do not use for UFL 25 | `apply_starting_squads` |
| Discord outbox | Complete | `DiscordEvent` + bot |
| Loans | **Not implemented** | — |
| Transfer window close | Hook exists; always open | `transfer_window_is_open()` |
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
- Squad cap: `LeagueSettings.max_squad_size` default **28**. `Team.roster_limit` model default is still **30**. `effective_roster_limit()` uses the configured max unless the stored team limit is smaller.
- Player identity master is FC26 (`Player.fc27_id`). Do not change IDs, names, or source ratings in ordinary work.
- Starting squads: official UFL structure is **25 players** (see Career Mode / Approval docs). Preview-only until Owner approves.

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

1. **Django admin** `/admin/` — staff/superuser. Includes match-approval actions that call the same `approve_match_submission` path.
2. **UFL Control Centre** `/mgl/control/` — Owner/Admin only (`owner_admin_required`). Queues for scores, transfers, press, managers, jobs, releases, awards, tokens, scouting exceptions, auctions, clubs, notifications, logs, season, league, starting squads.

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

Managers can submit: match results, transfer listings/offers, release requests, press answers, club job applications, auction listings (when allowed).

Owner/Admin make those official (except starting squads: Owner only). Opponent Accept/Reject on a result does **not** make the result official.

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
- Global LIVE ACTIVITY bar (`live_activity_bar.html`)
- Common page header include `core/includes/mgl_page_header.html`
- Public Home isolated; inner pages share `base.html`

See `UFL_DESIGN_SYSTEM.md` for tokens and the known logged-in header scale/crop issue.

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

### LOCKED / CONFIRMED

- Django monolith, UFL brand, website-as-truth
- Role enum OWNER / ADMIN / MANAGER; capability MEMBER
- Career Mode + public site in one product
- Token ledger on `RewardTransaction`
- FC26 identity field `fc27_id`
- Squad cap 28 via settings; listings 5 / 3-per-24h; manager auctions 3-per-24h
- No loans in code
- Transfer window hook always returns True
- Owner starting-squad 25-player approve/lock
- Result official only after Owner/Admin approve
- Public Home isolated; one shared inner header
- Youth Academy and cups are coming-soon structure, not live competitions

### UNKNOWN / UNDECIDED / NEEDS CONFIRMATION

- Live production row counts (how many Championship / League One clubs, whether UFL 25 squads are locked this season)
- Whether a transfer window will ever close
- Whether `Team.tokens` is still used for any live payment path
- Whether `core.Club` has any remaining runtime use
- Password reset / email verification
- Remaining logged-in header crop versus Owner screenshots
- Public canonical domain if not the Railway default
- Whether `LeagueSettings.scout_can_recruit` is intended to gate recruit (function `scout_can_recruit()` currently **hard-codes True**)

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
