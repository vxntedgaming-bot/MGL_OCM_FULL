# UFL Database Rules

**Status:** Models as defined in the live Django apps.  
Do not reset or delete production data during normal development.

Local default: SQLite `db.sqlite3` (gitignored). Production: PostgreSQL via `DATABASE_URL` / `POSTGRES_*`.

Do **not** run `makemigrations` on a fresh checkout unless a real model change is requested. Apply existing migrations only.

---

## MUST NOT reset or delete in ordinary work

- All `players.Player` rows (FC26 identities, ratings, faces, club assignment, career stats)
- `accounts.User` and `managers.ManagerApplication` (including `tokens`)
- `teams.Team` manager links, logos, `badge_code`
- `RewardTransaction` ledger
- `StartingSquadProposal` / `StartingSquadLock`
- `Fixture` / `MatchSubmission` / official event tables
- `HistoricalSeason` and frozen table rows
- `NewsPost`, `PressConference`, `ManagerNotification`
- `PlayerListing`, `MarketTransaction`, `PlayerAuction`, `AuctionBid`
- `ClubApplication`, `PlayerReleaseRequest`, `ManagerClubSpell`
- `LeagueSettings`
- `DiscordEvent`

Commands that assign starting squads or import FC26 must be dry-run first. `populate_super_league_1` and `import_fc27` are documented as non-resetting for tokens/managers when used as specified — still do not run destructive flags on production without instruction.

---

## Apps and models

### accounts

**User** (`AbstractUser`)

- `role`: OWNER | ADMIN | MANAGER (default MANAGER)
- `discord_id`: optional unique

### leagues

**League**

- `name`, `short_name`, `season`, `is_active`
- `display_name` (public label; canonical name stays for structure)
- `description`, `logo`, `display_order`
- `public_name` property

### teams

**Team** (live UFL clubs)

- `name`, `short_name`
- FK `league`
- OneToOne `manager` → User (`related_name=managed_team`)
- `logo`, `badge_code` (frozen crest key)
- `description`
- `budget` (legacy)
- `roster_limit` default **30**
- `is_ufl_starter` — official Season 1 38-club marker (false until bootstrap apply)
- `tokens` default **50** (club treasury / legacy)

### core

**Club** — separate legacy model (`managed_club`). **Not** the Career Mode club table. Do not confuse with `teams.Team`.

### managers

**ManagerApplication**

- OneToOne `user`
- `display_name`, `gamertag`, `preferred_team`
- `tokens` default 20
- `status` PENDING | APPROVED | REJECTED
- `submitted_at`, `reviewed_at`, `reviewed_by`

### players

**Player**

- Identity: `name`, unique `fc27_id`, `fc27_club`, face URLs, biometrics, `nationality`, `position`, card ratings (`overall`, pace…physical)
- FC26 individual `fc_*` attributes and playstyles
- UFL: FK `mgl_team`, `is_free_agent`, `released_at`, `card_tier`
- **DEC-042:** `is_free_agent` is **not** the product status for unused FC26 rows. Unsigned = no `mgl_team`. Do not mass-update the ~18,000 unused flags. The application must distinguish FC26/unsigned availability, genuine UFL Free Agents, club-owned players, and manager-auction holds.
- Aggregates: `appearances`, `goals`, `assists`, `average_rating`

### auctions

**PlayerAuction**, **AuctionBid**, **TokenTransaction** (legacy ledger)

### mgl (domain)

| Model | Role |
|---|---|
| `ApprovalStatus` | PENDING / APPROVED / REJECTED text choices |
| `Fixture` | League match; `is_released`, status, matchweek, season_number |
| `MatchSubmission` | One per fixture; opponent_response; `stats_applied` |
| `TeamMatchStats` | Goals, shots, possession, cards |
| `GoalEvent`, `AssistEvent` | Scorers / assists |
| `DefenderRating`, `GKSave`, `PlayerMatchRating` | Sheet ratings |
| `PressConference` | Questions/answers + approval |
| `RewardTransaction` | **Authoritative token ledger** |
| `WeeklyAwardBatch`, `MonthlyAwardBatch` | Award cycles |
| `TeamOfTheWeek`, `TOTWSelection`, `ManagerWeek` | TOTW / MOTW |
| `NewsPost` | Published activity; categories RESULTS, TRANSFER, AUCTION, FREE_AGENT, REWARD, PRESS, MANAGER, SIGNING, SCOUTING |
| `Pack`, `PackOpening`, `PackReward` | Pack types |
| `RecruitmentOpening` | Recruitment Drive pack + chosen player |
| `ApprovalRequest` | Generic kind/object_id queue |
| `PlayerOwnershipHistory` | Assignment log |
| `ManagerCareerStat` | Wins/draws/losses etc. |
| `Trophy` | Trophy records |
| `AuctionRequest` | Auction request queue |
| `PlayerListing` | LIVE / OFFER / PENDING / SOLD / CANCELLED / REJECTED |
| `TransferNegotiationEvent` | Offer/accept/reject audit |
| `MarketTransaction` | Completed/pending market money movement |
| `ClubApplication` | Job applications |
| `FixtureReleaseBatch` | Release batches |
| `ManagerClubSpell` | Tenure at a club |
| `ScoutProfile`, `ScoutAssignment`, `ScoutReport`, `ScoutSquadException`, `ScoutWatchlist` | Scouting |
| `SiteContent`, `SiteChangeLog` | Site Management CMS |
| `ManagerNotification` | Inbox |
| `HistoricalSeason`, `SeasonTableRow`, `SeasonTotsPick` | History snapshots |
| `LeagueSettings` | Singleton rules |
| `DiscordEvent` | Outbox queue PENDING/SENT/FAILED |
| `PlayerReleaseRequest` | Release approval |
| `StartingSquadProposal` | DRAFT/APPROVED/REJECTED/SUPERSEDED |
| `StartingSquadLock` | Per-season lock |

---

## Important relationships

```
User 1—1 ManagerApplication
User 1—1 Team (as manager)          # teams.Team.manager
League 1—* Team
Team 1—* Player                     # Player.mgl_team
League 1—* Fixture
Fixture 1—1 MatchSubmission
MatchSubmission 1—* TeamMatchStats
PlayerListing → Player, Team, seller ManagerApplication, reserved_buyer
PlayerAuction → Player
RewardTransaction → ManagerApplication
ClubApplication → ManagerApplication, Team
StartingSquadLock 1—1 StartingSquadProposal (PROTECT)
```

---

## User records and roles

- Every registered manager has a User + ManagerApplication.
- Owner/Admin are Users with `role` set; they may also have applications if they play.
- Staff/superuser for `/admin/` is independent of `role`.

---

## Tokens

- **Do not** zero `ManagerApplication.tokens` or delete `RewardTransaction` rows.
- Dual writers historically: prefer `credit_manager`/`debit_manager` only for new work.
- **Phase 1 LOCKED:** token values use 0.5 increments only. CURRENT CODE: `Decimal` fields with two places; no increment check.

---

## Career Mode data

Preserve applications, spells, career stats, notifications, press, recruitment openings, scout profiles/assignments.

---

## Fixtures, results, statistics, tables

Live tables are computed from **approved** submissions (`build_live_league_table` and stats views). Pending submissions must not move official tables.

`HistoricalSeason` finalized rows are frozen — do not let live data overwrite them.

---

## Transfers, notifications, approvals, news

Preserve listing/negotiation/market rows, release requests, news posts (`published` flag), Discord events (retry queue).

---

## LeagueSettings

Singleton-style: `order_by("id").first()` or create. Fields: starting_tokens, max_squad_size, starting_squad_size, listing caps, auction/scout flags and duration strings, press reward/cap.

`scout_can_recruit` column exists; live helper `scout_can_recruit()` currently ignores it (returns True). **Phase 1 LOCKED:** that setting must actually enforce. GAP.

**Official squad is 30** with the locked positional structure. `starting_squad_size` and `max_squad_size` defaults are **30**. Runtime helpers never cap below 30.

Current production/test data: 14 Premier League clubs, mixed squads. Season 1 bootstrap can retire those UFL-division clubs and create 38, but **production apply is blocked** until the Owner authorises it. Do not run `mgl_reset`.

---

## UNKNOWN / NEEDS CONFIRMATION

- Production row counts
- Whether `core.Club` has rows
- Whether `ApprovalRequest` is still written by current views or is leftover
- Whether `Team.budget` is read anywhere
