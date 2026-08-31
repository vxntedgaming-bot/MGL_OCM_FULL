# Ultimate Fantasy League — Technical Audit

This document is the Phase 1 audit of the live Online Career Mode site
before the UFL transformation. It maps existing systems to the UFL spec.
It does **not** authorise dropping production tables, resetting tokens,
rewriting FC26 ratings, or running `apply_starting_squads` / `mgl_reset`.

Production remains on Railway. Internal URL prefixes (`/mgl/…`) stay so
existing bookmarks, Discord links, and tests keep working.

---

## 1. Current stack

| Layer | Technology |
|---|---|
| Backend | Django 6.x (`config.settings`) |
| Frontend | Django templates + CSS/JS (no React) |
| Database | Railway Postgres via `DATABASE_URL`; local SQLite fallback |
| Auth | `accounts.User` (`AbstractUser` + `role` + `discord_id`) |
| Static | WhiteNoise + `staticfiles/` |
| Process | Gunicorn; `railway.toml` `releaseCommand = "true"` |
| Discord | Separate `discord_bot/bot.py` polling `NewsPost` |

Apps: `core`, `accounts`, `leagues`, `teams`, `managers`, `players`, `auctions`, `mgl`.

## 2. Current database (mapped, not duplicated)

| UFL concept | Existing model | Notes |
|---|---|---|
| Users / Roles | `accounts.User` | OWNER / ADMIN / MANAGER only |
| Managers | `managers.ManagerApplication` | Live token balance; PENDING until appointed |
| Clubs | `teams.Team` | `manager` OneToOne User; `roster_limit` default 30 |
| Players | `players.Player` | `fc27_id` = FC26 ID; `mgl_team`; `is_free_agent` |
| Squads | `Player.mgl_team` | No separate Squad table |
| TokenAccounts | `ManagerApplication.tokens` | Club `Team.tokens` is legacy treasury |
| TokenTransactions | `mgl.RewardTransaction` + `auctions.TokenTransaction` | Two writers; do not double-debit |
| TransferListings | `mgl.PlayerListing` | LIVE immediately; admin gates **deals** |
| TransferOffers / Negotiations | Listing `OFFER` + `reserved_buyer` + swap M2M | Counter via transfer request views |
| Transfers | `mgl.MarketTransaction` | Official completed deals |
| Auctions / Bids | `auctions.PlayerAuction` / `AuctionBid` | Server `ends_at` |
| Matches / Submissions | `mgl.Fixture` / `MatchSubmission` | Opponent confirm then admin approve |
| PlayerStats | Player counters + match events | Official only after approval |
| PressSpeeches | `mgl.PressConference` | Pending → admin approve |
| News / Activity | `mgl.NewsPost` | Activity is a filtered news feed |
| Notifications | `mgl.ManagerNotification` | Header bell is the inbox |
| FreeAgents | `Player.is_free_agent` | Distinct from UNASSIGNED pool |
| Jobs | `mgl.ClubApplication` | Job Centre |
| Approvals | `mgl.ApprovalRequest` + per-entity status | Reuse, do not fork |
| AuditLogs | `mgl.SiteChangeLog` | `mgl.audit.log_ocm_action` |
| DiscordEvents | **missing** | Bot polls `NewsPost.discord_sent` |

## 3. Current authentication

- Login: `/login/` (`manager_login`)
- Signup creates a `User` immediately (`role=MANAGER`) plus a PENDING `ManagerApplication`
- Club/market/match actions require an **approved** application and an assigned club
- Control (`/mgl/control/`) is Owner/Admin only, enforced in `mgl.permissions`

## 4. Current roles (UFL mapping)

| UFL role | How it exists today | Decision |
|---|---|---|
| PUBLIC | Anonymous visitor | Keep |
| MEMBER | Signed-in user without an approved club | **Capability, not a new `User.role`.** Adding MEMBER to the enum would break live users and tests. A member is `is_authenticated` and `approved_manager(user) is None`. |
| MANAGER | Approved application + assigned club | Keep |
| ADMIN / OWNER | `User.role` | Keep hierarchy |

## 5. Current major features

Public: home, tables, fixtures, stats, clubs, player database, free agents, transfer market, auctions, news, pressroom, job centre, history.

Manager: hub, squad, listings, offers/counters/swaps, club auctions, FA sign (0 TKN), match submit, press answers, scouting packs, notifications.

Admin/Owner: Control Centre approval queues, tokens, auctions, clubs, seasons (start / lock / unlock / archive), site CMS, logs.

## 6. Current transfer architecture

```
List (LIVE, no admin gate)
  → Buyer offer (OFFER)
  → Seller accept (PENDING)
  → Admin/Owner approve
  → Atomic sale: tokens + ownership + history + news
```

Types in use: buy (tokens), swap (optional players), release (immediate).
**Loans do not exist in code** (only leftover homepage marketing copy).

## 7. Current admin architecture

GET pages in `mgl/control_views.py`. POST actions in `mgl/market_views.py`.
Shared queues in `mgl/control_desk.py`. Official match writes in `mgl/match_official.py`.

## 8. Reusable components / services

- `mgl.services.create_news`, `assign_player`, `release_player`
- `mgl.market` token + listing + auction settlement
- `mgl.notifications.notify_user`
- `mgl.audit.log_ocm_action`
- `mgl.player_state` UNASSIGNED / AUCTION / FREE AGENT / CLUB PLAYER
- `{% player_card %}` / FC26 face proxy
- Control shell + hub gold/black public theme
- FC26 import: `fc26_players_mgl.csv`, `import_fc27`, `sync_fc26_details`

## 9. Existing problems vs UFL spec

- User-facing identity is still MGL / MetaGamingLeague
- Homepage still mentions loans
- Listings: 6 slots, no 3-per-24h cap
- Releases are immediate (no admin gate)
- Managers can create club auctions
- Roster max 30; starting generator is 14×26 @ 64–70 (RB/LB×2, no RWB/LWB)
- Scouting **assigns** unassigned players (ownership bypass)
- Discord has no retry queue; `discord_id` is unused
- Two token ledgers must stay idempotent
- No LeagueSettings singleton (starting tokens hard-coded to 20)

## 10. What must be removed (UI / rules, not tables)

- User-facing MGL / MetaGamingLeague branding
- Loan copy
- Immediate manager release (replace with approval)
- Scout-to-squad ownership claim (replace with watchlist / auction path)
- Hard-coded 30-man / 6-listing / 64–70 generator for **new** seasons

## 11. What can be reused

Almost all infrastructure: auth, FC26 pool, listings, negotiations, match
approval, press, news, notifications, Control Centre, season lock, TOTW,
token ledgers, player cards.

## 12. Proposed migration architecture

Additive only. No table drops.

1. `LeagueSettings` — Owner-configurable UFL rules
2. `DiscordEvent` — queued, retryable Discord outbox
3. `ScoutWatchlist` + scout attribute / report fields
4. `PlayerReleaseRequest` — pending releases
5. Enforce listing 5 + 3/24h, squad max 28, auction create = Admin/Owner
6. Event engine wraps `create_news` → activity + DiscordEvent
7. Public/manager/control copy → Ultimate Fantasy League / UFL
8. UFL 25-man / 64–69 generator shipped as **dry-run only**
   (`propose_ufl_starting_pool`). Live 14×26 allocations stay put.

## 13. Risks

- Changing listing/auction/scout rules mid-season
- Fragile migrations `0019` / `0020` — new work is `0021+` only
- Production SiteContent rows override template defaults
- Tests assert old MGL strings and 6-listing / 30-man / scout-recruit behaviour
- Discord channel env remains `MGL_CHANNELS` (alias `UFL_CHANNELS`)

## 14. Implementation order (this slice)

Phase 2–5 foundation, Phase 6/8/9 transfer rules, Phase 10 auction create
gate, Phase 12–14 event/Discord/scouting Career Mode, Phase 15–16 public
+ hub identity. Later slices: Discord account linking, full public IA,
Owner-run UFL squad apply, MEMBER enum (only if explicitly required).
