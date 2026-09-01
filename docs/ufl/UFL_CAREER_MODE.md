# UFL Career Mode

**Status:** Existing Career Mode as implemented.  
Do not modify these systems unless explicitly instructed.

---

## Product shape

Career Mode is **not a separate app**. It is the signed-in league product on the same Django site.

- Public Home is isolated.
- Assigned approved managers hitting `/` go to **Dashboard** `/mgl/hub/`.
- Career routes sit under `/mgl/` and `/market/` plus `/auctions/`.
- Internal URL prefix `/mgl/` is intentional compatibility. Users see UFL.

---

## Data that must be preserved

| Data | Model / field | Notes |
|---|---|---|
| Manager account | `accounts.User` | `role`, `discord_id`, auth |
| Application + tokens | `ManagerApplication` | `status`, `tokens`, display name, gamertag |
| Club appointment | `Team.manager` OneToOne | Current job |
| Spell history | `ManagerClubSpell` | Resign / join history |
| Career W/D/L | `ManagerCareerStat` | Updated when a result is official |
| FC26 identity | `Player.fc27_id` and FC attribute fields | Never rewrite IDs / source ratings / names in ordinary work |
| Club assignment | `Player.mgl_team`, `is_free_agent` | Market state |
| Ownership log | `PlayerOwnershipHistory` | Source includes INITIAL_SQUAD, UFL_STARTING, FREE_AGENT, SCOUT, sales |
| Token ledger | `RewardTransaction` | Authoritative |
| Starting-squad drafts/locks | `StartingSquadProposal`, `StartingSquadLock` | Owner flow |
| Notifications | `ManagerNotification` | Inbox |
| Fixtures / official stats | `Fixture`, `MatchSubmission`, event tables | Only approved stats are official |

---

## FC26 identities

**CONFIRMED**

- Master key is `Player.fc27_id` (name kept from an older FC27 import path; data is FC26).
- Import commands: `import_fc27`, `sync_fc26_details`, `sync_fc26_names`, `populate_super_league_1`.
- Faces: Sofifa URLs stored on the player; served via `/mgl/players/<id>/face/` and cached under `media/player_faces/`.
- `fc27_club` is **reference only**. It does not mean the player is at that UFL club.
- Unassigned imported players are **not** Free Agents.

Do not change FC26 identities, names, or source ratings unless the Owner asks for a specific import/sync.

---

## Tokens

**CONFIRMED**

- Balance: `ManagerApplication.tokens`.
- Register: `starting_tokens()` from `LeagueSettings` (default 20).
- Writes: `mgl.services.credit_manager` / `debit_manager` (select-for-update, idempotent on category+reference).
- Resign: tokens stay with the manager; squad stays with the club.
- `Team.tokens` is club treasury / legacy (default 50). Not the dashboard “personal balance”.
- `auctions.TokenTransaction` is legacy.

See `UFL_TRANSFER_RULES.md` for market movement.

---

## Job Offers and manager assignment

**CONFIRMED**

1. User registers → `User.role=MANAGER`, `ManagerApplication` **PENDING**, tokens granted.
2. Owner/Admin approve or reject the **manager application** (`control_approve_manager` / `control_reject_manager`).
3. Approved manager applies for a vacant club (`ClubApplication`).
4. Owner/Admin approve the job (`control_approve_job`) → user becomes `Team.manager`.
5. Capability role becomes MANAGER only when approved **and** assigned.

Hub, market, and scouting expect a club for most actions.

Resign: `resign_from_club` / `resign_manager_from_club`. Control can also change or remove a club manager.

---

## Club ownership

**CONFIRMED**

- One manager per club (`Team.manager` OneToOne).
- One current club per manager (reverse `managed_team`).
- Managers may only operate their own squad (list, release, auction, submit).
- Public club pages: `/clubs/`, `/clubs/<slug>/`.

Legacy `core.Club` exists in the database. Career Mode clubs are `teams.Team`. Do not use `core.Club` for new Career Mode work.

---

## Owner starting-squad approval

**CONFIRMED — PROTECTED**

Official UFL starting structure: **25 players** (see `UFL_GAME_RULES.md`).

Flow (`mgl/ufl_starting.py`, Control → Season → Starting Squads):

1. Owner/Admin generate a **draft** `StartingSquadProposal` (JSON payload). Generation does **not** write ownership.
2. Owner **approve** with explicit confirm (`approve_proposal`). Admin cannot approve.
3. Players are assigned with source `UFL_STARTING`. FC26 id and overall are checked so identities cannot change mid-apply.
4. `StartingSquadLock` records the season. A second approve in the same season is rejected until a new season.
5. Reject leaves draft rejected; does not assign.

Manager token snapshot is taken during approve so balances are not silently rewritten.

**Do not** run `apply_starting_squads` to create these UFL 25s. That command is the older 14×26 official allocation (364 club players). `generate_balanced_squads` is disabled.

---

## Existing Career Mode routes

| URL | Name | Gate |
|---|---|---|
| `/mgl/` | `mgl_index` | Career |
| `/mgl/hub/` | `manager_hub` | Career |
| `/mgl/team/` | `team_management` | Career |
| `/mgl/team/release/<id>/` | `release_my_player` | Career POST |
| `/mgl/team/auction/<id>/` | `list_player_for_auction` | Career POST |
| `/mgl/team/sell/<id>/` | `sell_player` | login + approved manager POST |
| `/mgl/players/` | `player_database` | Career |
| `/mgl/players/<id>/` | `player_profile` | Career |
| `/mgl/unassigned/` | `unassigned_players` | Career |
| `/mgl/free-agents/` | `free_agents` | Career |
| `/mgl/free-agents/<id>/sign/` | `sign_free_agent` | Career POST |
| `/mgl/profile/` | `manager_profile` | Career |
| `/mgl/profile/resign/` | `resign_from_club` | Career |
| `/mgl/rewards/` | `manager_rewards` | Career |
| `/mgl/fixtures/` | `fixture_list` | Career |
| `/mgl/fixtures/<id>/submit/` | `submit_match` | Career |
| `/mgl/fixtures/<id>/stats/` | `fixture_stats` | Career (same view) |
| `/mgl/fixtures/<id>/press/` | `press_conference` | Career |
| `/mgl/notifications/` … | inbox | Career |
| `/mgl/transfer-requests/` | `transfer_requests` | Career |
| `/market/` | `transfer_market` | Career |
| `/market/transfers/` | `transfer_history` | Career |
| `/market/scouting/` | `scouting` | Career |
| `/market/youth-academy/` | `youth_academy` | Career, Coming Soon |
| `/market/recruitment/` … | recruitment | Career |
| `/auctions/` | `live_auctions` | Career |
| `/auctions/<id>/bid/` | `place_bid` | Career POST |

Public (not career-gated): `/`, leagues, clubs, jobs, rules, news/activity, pressroom, stats, `/history/`, `/transfers/`, released `/mgl/fixtures/<id>/`.

---

## Existing Career Mode permissions

See `UFL_ROLES_PERMISSIONS.md`.

- `career_required` = approved `ManagerApplication` **or** Owner/Admin.
- Club mutations additionally require `managed_team` and ownership checks.
- Members (pending or unassigned) are sent to Job Centre.

---

## Hub (do not redesign)

`/mgl/hub/` layout is complete. Required strings/links include PENDING ACTIONS, Club Profiles, Recruitment Drive, TRANSFER REQUESTS, PERSONAL BALANCE, RESIGN, OUTSTANDING FIXTURES, ENTER RESULT, `data-notify-dropdown`, `mgl-notify-count`, class `mgl-dash-badge`.

Do **not** add Academy / Head To Head / Propose Transfer **cards** on the hub body. Youth Academy may appear in the global header as Coming Soon.

---

## Scouting, recruitment, youth

- Scouting: manager-wide HQ, one active mission, recruit into current club, exceptions to Control if squad full.
- Recruitment Drive: existing pack open + choose one.
- Youth Academy: placeholder only.

---

## UNKNOWN / NEEDS CONFIRMATION

- Whether production season already has a `StartingSquadLock`.
- Whether any manager still holds tokens only on a legacy `TokenTransaction` path.
- Whether `core.Club` rows exist in production and if anything still reads them.
