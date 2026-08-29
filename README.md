# MGL Online Career Mode

Django site and Discord outbox bot for MetaGamingLeague Online Career Mode: managers, clubs, FC26 player pool, fixtures, match approval, auctions, tokens, and rewards.

This tree is the existing MGL project (not a rewrite).

Presentation lives in `core/templates/core/base.html`, `core/static/core/css/mgl.css`, and the overlay design system `core/static/core/css/mgl-theme.css`. Inner pages inherit header, footer, cards, badges, tables, and mobile navigation from that base. Player market states stay visually distinct: **UNASSIGNED**, **AUCTION**, and **FREE AGENT**.

Assigned managers are sent from `/` to the Manager Hub. Public visitors keep the simplified homepage. Club squads are at `/clubs/<club-name-slug>/` (short codes such as `/clubs/ARS/` still resolve). News, Live Activity and Pressroom reuse `NewsPost` and `PressConference`. Set `DISCORD_INVITE_URL` to show Discord buttons (header **DISCORD**, footer **JOIN OUR DISCORD**); leave it empty to hide them. Do not hardcode an invite.

## Local development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-mgl.txt
```

Optional environment file (safe local defaults work without it):

```bash
cp .env.example .env
```

Apply the migrations that already ship in this repository. Do **not** run `makemigrations` on a fresh checkout.

```bash
python manage.py migrate
python manage.py seed_packs
python manage.py createsuperuser
python manage.py runserver
```

Optional player import (FC26 CSV is already in the repo). Every imported player stays **UNASSIGNED**, not a Free Agent. MGL clubs start with 0 players:

```bash
python manage.py populate_super_league_1
```

That command creates the 14 official Premier League clubs if missing and imports `fc26_players_mgl.csv` **without** assigning anyone to an MGL club. `fc27_club` is FC26 reference data only. It does not reset tokens, managers, fixtures, or history. Assign the approved starting 26s with `apply_starting_squads` (dry-run first).

Player market states:

- **UNASSIGNED** — unused FC26 pool. No club, not in auction, not a Free Agent. These players are not available to sign.
- **AUCTION** — owner/admin released an unassigned player into the existing auction system.
- **FREE AGENT** — an unassigned auction closed with **no bids**, or a club manager released their own player. Eligible managers can sign them for **0 TKN**.
- **CLUB PLAYER** — belongs to an MGL club (starting squad, auction win, free-agent signing, transfer, or scout).

Only an owner/admin can move UNASSIGNED → AUCTION. Managers receive HTTP 403 if they POST the unassigned-release endpoint. A no-bid auction becomes a Free Agent. A manager can only release players on their own club; that player becomes a Free Agent with no auction.

Do **not** run `generate_balanced_squads`. It is disabled. Official 14×26 starting squads use the approved allocation (seed `20260828`, 1,741 OVR per club). Dry-run first; `--apply` writes club assignments only:

```bash
python manage.py apply_starting_squads
python manage.py apply_starting_squads --apply
```

That command does not change ratings, FC26 IDs, faces, club treasuries, or manager balances, and does not create auctions. After a successful apply: 364 club players, remaining FC26 players UNASSIGNED, 0 Free Agents, 0 auctions.

Optional: dry-run a *new* balanced pool (does not write, does not replace the approved allocation):

```bash
python manage.py propose_starting_auction_pool --seed 20260828 --attempts 120
```

If production rows are still labelled as Free Agents by mistake, correct flags only (no assignments, no auctions):

```bash
python manage.py correct_unassigned_flags
python manage.py correct_unassigned_flags --apply
```

```bash
python manage.py import_fc27 fc26_players_mgl.csv
python manage.py sync_fc26_details fc26_players_raw.csv --faces-only
python manage.py sync_fc26_details fc26_players_raw.csv --attributes-only
python manage.py sync_fc26_names fc26_players_raw.csv
python manage.py close_expired_auctions
```

`--attributes-only` copies FC26 individual skills (pace/shooting/passing/dribbling/defending/physical breakdowns plus goalkeeper attributes) onto existing `Player` rows by `fc27_id` = CSV `player_id`. It also refreshes the recognised FC26 display name. It does not create or delete players and does not change MGL club, transfers, OVR, position, card ratings, faces or MGL statistics. Missing source values stay empty and the profile shows —. Re-run is safe.

`--faces-only` copies `player_face_url` from `fc26_players_raw.csv` onto existing `Player` rows by `fc27_id` = CSV `player_id` (Sofifa FC26 headshots). It fills empty `player_face_url` / `image_url` only and does not overwrite URLs that are already set. Sofifa blocks hotlinking, so `{% player_card %}` loads those faces through `/mgl/players/<id>/face/` and caches the PNG under `media/player_faces/`. Missing or broken faces keep the silhouette fallback. Cards show **UNASSIGNED**, **FREE AGENT**, **AUCTION**, or the MGL club short name.

`sync_fc26_names` rewrites **only** `Player.name` on existing rows. It derives the recognised FC26 display name from `short_name` + `long_name` (so Salah, Mbappé and Hakimi, not Ghaly / Lottin / Mouh), matches by `fc27_id`, and does not create or delete players. Player search is accent-insensitive (`Mbappe` finds `Mbappé`). `convert_fc26.py` uses the same mapping when rebuilding `fc26_players_mgl.csv`.

- Site: http://127.0.0.1:8000/
- Django admin: http://127.0.0.1:8000/admin/
- Manager register / login: `/register/`, `/login/`
- Manager tools: `/mgl/hub/`
- Owner / admin control: `/mgl/control/`
- Public pages: `/leagues/`, `/market/`, `/stats/premier-league/`, `/jobs/`

Statistics are per division (`/stats/premier-league/`, `/stats/championship/`, `/stats/league-one/`) and use **approved** match submissions only. Pending results do not move the table or player leaderboards. Waiting Room League and the Compare page are not in navigation; those URLs 404.

Managers submit results only for fixtures that include their club (`/mgl/fixtures/<id>/submit/`). Goal and assist player fields follow the goal count; defender ratings accept decimals 0.0–10.0; goalkeeper saves are stored on the same submission. Admin/owner approval is unchanged.

If a 14-team division has no round-robin yet, create the missing 13-game single schedule locally (91 fixtures, no duplicates, no deadline):

```bash
python manage.py ensure_league_fixtures
```

Do not run that command against production. It does not delete existing fixtures or invent clubs for Championship / League One until those divisions have 14 teams.

## Core OCM

- MGL currently has three active divisions: **Premier League**, **Championship** and **League One**. Super League 1 was renamed in place to Premier League so existing club IDs, squads and fixtures stay attached. MLS is not an active competition.
- Official Premier League clubs (created idempotently): Real Madrid, Barcelona, Atletico Madrid, Manchester United, Chelsea, Manchester City, Arsenal, Liverpool, Tottenham, Paris Saint-Germain, Lyon, Marseille, Bayer Leverkusen, Bayern Munich. Club treasury rows still start at 50 tokens; that figure is not the manager's personal balance.
- Transfer currency is **tokens**. New manager sign-ups receive **20 personal tokens**. That balance belongs to the manager account and is not reset when they leave, join, or apply for a club.
- Scouting is a **manager-wide** network (not per Bronze/Silver/Gold). Level 1 is free. Level 2 costs 18 personal tokens and Level 3 costs 25. Times are 8/10/12 hours at Level 1, 4/5/6 at Level 2, and 1/2.5/3 at Level 3. Completed scouts recruit an eligible **unassigned** FC26 player onto the manager's current club, which cannot exceed 30 players.
- Squads stay with the club if a manager leaves. Token balances stay with the manager.
- Manager sales need owner/admin approval before they go live on `/market/`.
- Auction bids reserve the manager's personal tokens. Being outbid refunds the previous manager automatically.

Local defaults:

- SQLite at `db.sqlite3` (gitignored)
- `DEBUG=true`
- console email (no SMTP credentials required)
- static files from app directories + `static/`
- media uploads under `media/`

## Environment variables

See `.env.example` for the full list. Important ones:

| Variable | Local default | Production |
|---|---|---|
| `DJANGO_SECRET_KEY` | development fallback | **required**, not `django-insecure-` |
| `DJANGO_DEBUG` | `true` | `false` |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost,testserver` | **required** real hostnames |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `http://127.0.0.1:8000,http://localhost:8000` | `https://your-domain` |
| `DATABASE_URL` or `POSTGRES_*` | unset (SQLite) | PostgreSQL |
| `DJANGO_SERVE_MEDIA` | n/a (`DEBUG` already serves media) | `true` if no nginx/media server |
| `DJANGO_EMAIL_BACKEND` / `EMAIL_*` | console | SMTP |

Do not commit `.env` or real secrets.

Production HTTPS settings (`SECURE_SSL_REDIRECT`, secure cookies, HSTS) turn on automatically when `DJANGO_DEBUG=false`. If the app sits behind a reverse proxy that terminates TLS, keep `DJANGO_USE_X_FORWARDED_PROTO=true` (the production default).

## Database

**Development:** SQLite. Leave `DATABASE_URL` and `POSTGRES_*` unset. Do not convert or delete an existing local `db.sqlite3`.

**Production:** PostgreSQL, either:

```bash
export DATABASE_URL=postgres://mgl:mgl@127.0.0.1:5432/mgl
```

or:

```bash
export POSTGRES_DB=mgl
export POSTGRES_USER=mgl
export POSTGRES_PASSWORD=...
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
```

Then run `python manage.py migrate` against that database. This does not migrate or replace a local SQLite file.

## Static and media files

Collect hashed/compressed static files for production:

```bash
python manage.py collectstatic --noinput
```

WhiteNoise serves files from `STATIC_ROOT` when `DEBUG` is false. Development still uses Django’s staticfiles finders, so `runserver` keeps serving `core/css/mgl.css` and `static/mgl/cards/`.

Team logos and other uploads use `MEDIA_ROOT` (default `media/`). In production without a dedicated media server, set `DJANGO_SERVE_MEDIA=true`.

## Production startup

This is a persistent Django WSGI process, not a Vercel/serverless app. The Discord bot remains a second process.

```bash
source venv/bin/activate
export DJANGO_DEBUG=false
export DJANGO_SECRET_KEY=...          # long random value
export DJANGO_ALLOWED_HOSTS=ocm.example.com
export DJANGO_CSRF_TRUSTED_ORIGINS=https://ocm.example.com
# export DATABASE_URL=postgres://...
python manage.py migrate
python manage.py import_fc27 fc26_players_mgl.csv
python manage.py collectstatic --noinput
gunicorn --config gunicorn.conf.py
```

Use one Gunicorn worker with SQLite. Use two or more workers with PostgreSQL (`GUNICORN_WORKERS`).

Checks:

```bash
python manage.py check
DJANGO_DEBUG=false DJANGO_SECRET_KEY=... DJANGO_ALLOWED_HOSTS=ocm.example.com python manage.py check --deploy
```

`python manage.py check --deploy` with the local `DEBUG=true` defaults still reports development-only email and insecure-cookie warnings. That is expected. Run it with production environment variables before deploying.

## Discord bot

Optional, separate process. Do not start it from `install` or Gunicorn.

```bash
export DISCORD_TOKEN=...
export MGL_CHANNELS="RESULTS:123,NEWS:456"
python run_mgl_bot.py
```
