# UFL Starting Squad Audit (Phase 2.1)

**Status:** INSPECTION ONLY. No application, database, migration, production, squad-generation, or lock changes were made for this document.

**Inspected tree:** live Career Mode source (`MGL_OCM_FULL` / `mgl/` Django app).  
**Date of inspection:** 1 September 2026.  
**Method:** source read only. Management commands that write data were **not** executed. No database was queried or written.

**Official locked product rule (DEC-030, not implemented in code):** every UFL club official starting squad = **exactly 30 players**:

| Position | Count |
|---|---|
| GK | 2 |
| CB | 4 |
| RB | 2 |
| LB | 2 |
| RWB | 2 |
| LWB | 2 |
| CDM | 2 |
| CM | 2 |
| CAM | 2 |
| LM | 2 |
| RM | 2 |
| LW | 2 |
| RW | 2 |
| ST | 2 |
| **Total** | **30** |

Roster limit (locked product rule) = **30**.

**This document describes what the code does today.** It does not implement the locked 30-player rule.

---

## 1. Current implementation

Career Mode uses **three separate starting-squad mechanisms**. They do not share a single entry point. Confusing them is the main operational risk.

### Path A — Official Control Centre generator (current “UFL” path)

| Item | Location |
|---|---|
| Settings / shape / runtime roster helper | `mgl/ufl_settings.py` |
| Generate, validate, assign, lock | `mgl/ufl_starting.py` |
| HTTP UI + POST actions | `mgl/control_views.py` → `control_starting_squads` |
| URL | `/mgl/control/season/starting-squads/` (`mgl/urls.py`, name `control_starting_squads`) |
| Template | `templates/mgl/control_starting_squads.html` |
| Models | `StartingSquadProposal`, `StartingSquadLock` in `mgl/models.py` |
| Dry-run print command | `mgl/management/commands/propose_ufl_starting_pool.py` |
| Tests | `mgl/test_ufl_starting.py` |

This path writes a **proposal JSON** first. Players are assigned only when the Owner **approves** with `confirm_approval=1`. Approval creates `StartingSquadLock`. Shape in code is **25 players**, not 30.

### Path B — Legacy approved JSON apply (`apply_starting_squads`)

| Item | Location |
|---|---|
| Command | `mgl/management/commands/apply_starting_squads.py` |
| Logic | `mgl/starting_squads.py` → `apply_starting_squads()` |
| Payload | `mgl/data/approved_starting_squads.json` |
| Tests | `mgl/test_starting_squads.py` |

Default is **dry-run**. Writes only with `--apply`. Shape is **14 official Super League 1 clubs × 26 players**. Does **not** create `StartingSquadLock`. Official clubs must be **empty**.

### Path C — `generate_balanced_squads` (disabled)

| Item | Location |
|---|---|
| Command | `mgl/management/commands/generate_balanced_squads.py` |

`handle()` raises `CommandError` immediately. The body below that raise is unreachable. If it were enabled, it would fill **empty** `teams.Team` rows from **Free Agents**, **26 players**, `roster_limit=30`, history source `INITIAL_SQUAD`. **Running it today changes nothing.**

### Related but unused / adjacent

| Item | Role |
|---|---|
| `mgl/starting_pool.py` + `propose_starting_auction_pool` | 26-player auction-pool **preview** (dry-run). Not wired to Control. |
| `mgl/management/commands/populate_super_league_1.py` | Creates 14 official clubs + FC26 import (unassigned). `--fill-squads` optional 26-player fill (off by default). |
| `mgl/management/commands/mgl_reset.py` | Catastrophic Career Mode wipe. Not a season-start tool. |
| `mgl/admin.py` | Does **not** register `StartingSquadProposal` or `StartingSquadLock`. |

### Runtime assignment primitive (shared)

All real assignment goes through `assign_player()` in `mgl/services.py`:

- Sets `Player.mgl_team` and `Player.is_free_agent = False` (no `assigned_at` field)
- Writes `PlayerOwnershipHistory`
- Enforces `effective_roster_limit(team)`
- Does not change `fc27_id`, ratings, face, or tokens

Sources used by starting-squad paths:

- Path A approve: `UFL_STARTING`
- Path B apply: `INITIAL_SQUAD`
- Path C (dead): `INITIAL_SQUAD`

---

## 2. Current production data state

From Owner lock / prior documentation (this inspection **did not** query production):

- 14 clubs, all Premier League
- Squads are **test / development** data
- Player numbers and positions are mixed
- Data is **not** the final UFL season setup
- Nothing is locked (`StartingSquadLock` is empty in the intended live state)
- Production is live
- Only the Owner currently has access / visibility

**This audit did not change any of that.**

Implication for code: Path A’s `target_clubs()` is `Team.objects.all()`, not “the 14 official clubs”. Path B uses `teams.official_sl1.OFFICIAL_SL1_SHORT_NAMES` (14 clubs). Path A and Path B therefore target **different club sets** if extra `Team` rows exist.

There is also a **42-club bootstrap** (`teams/official_ufl_clubs.py`, Control → Season Controls → Owner `ENSURE CLUBS`). That is **14 + 14 + 14**, not the locked **16 / 14 / 8**. This audit did not run it.

---

## 3. Starting squad generation process (Path A)

Functions: `create_proposal()`, `generate_allocation()`, `target_clubs()`, `eligible_queryset()`, `load_eligible_players()`, `_attempt()`, `_snake_deal()`, `_equalize()` in `mgl/ufl_starting.py`.

HTTP: POST `action=generate` or `action=regenerate` on `control_starting_squads` (`mgl/control_views.py`). Owner-only (`is_owner`). The current view does **not** require a `confirm_generation` checkbox (unlike approve, which requires `confirm_approval=1`).

### What generate does

1. Calls `create_proposal()` → `generate_allocation()`. Season number is **not** required for generate. `_season_number()` / `StartingSquadLock` are checked only on **approve**.
2. A lock for the current season does **not** block generate. A new DRAFT can still be written. Approve of that draft will then fail if a lock exists.
3. Loads **all** `teams.Team` rows (`target_clubs()`).
4. Builds eligible pool (`eligible_queryset()` / `load_eligible_players()`):
   - `Player` with `overall` in `UFL_MIN_OVR`–`UFL_MAX_OVR` (**64–69**)
   - `position` in `UFL_SQUAD_SHAPE` keys
   - `mgl_team` is null
   - not in a live auction (`Auction.STATUS_LIVE`)
   - not in a live listing (`TransferListing` LIVE)
   - Free Agents excluded unless `include_free_agents=True` (Control form checkbox)
5. Up to **80** allocation attempts (`MAX_ATTEMPTS`). Each attempt snake-deals by position then `_equalize()` (up to **20 000** same-position swaps). Accepts when the largest club average-OVR gap is ≤ **1.500**.
6. Validates counts, uniqueness, identity snapshot (`fc27_id` + `overall` per selected player).
7. Writes `StartingSquadProposal` (`status=DRAFT`) with JSON `allocation` and `snapshot`.
8. Marks other DRAFT proposals `SUPERSEDED`.

### What generate does **not** do

- Does not call `assign_player`
- Does not call `apply_starting_squads` or `generate_balanced_squads`
- Does not create `StartingSquadLock`
- Does not change tokens, managers, fixtures, transfers, or player identity fields
- Does not empty existing club squads

`propose_ufl_starting_pool` only **prints** a 25-player structure. It does not write.

---

## 4. Starting squad application process

There are two apply mechanisms.

### 4.1 Path A — `approve_proposal()` (Control “Approve & assign”)

HTTP: POST `action=approve`, Owner-only, `confirm_approval=1` required.

1. Rejects if `StartingSquadLock` already exists for the current season.
2. Re-runs `validate_allocation` (shape, uniqueness, still-unassigned, not FA unless opted in, not listed/auctioned).
3. Checks FC26 id + overall unchanged vs snapshot.
4. Snapshots `ManagerApplication.tokens` **only for managers currently attached to the clubs in the proposal** (`club.manager_id`). Fails if those balances change mid-transaction. Unattached manager balances are not snapshotted.
5. For each club/player: `assign_player(..., source="UFL_STARTING")`.
6. Creates `StartingSquadLock` (unique per season; `proposal` PROTECT).
7. Sets proposal `APPROVED`.
8. `emit_official_event` (news / Discord outbox) + `write_audit("starting_squads.approve")`.

**Does not empty existing club squads.** Roster check is:

`occupied + PLAYERS_PER_CLUB > effective_roster_limit(team)`

If a club already has players **and** remaining space, approval can **add 25 players on top**. If selected players already have `mgl_team`, validation fails and nothing is assigned.

### 4.2 Path B — `apply_starting_squads(dry_run=...)` in `mgl/starting_squads.py`

Command default: dry-run (`dry_run=True`). `--apply` sets `dry_run=False`.

Writes only if validation passes:

- 14 official clubs exist (`teams.official_sl1.OFFICIAL_SL1_SHORT_NAMES`)
- those clubs have **zero** assigned players
- no live auctions
- selected players unassigned and not Free Agents
- JSON payload: 14 × 26, **1741** total OVR per club (avg 66.9615)
- player overall and position must still match the JSON (ratings must not have changed)

Then `assign_player(..., source="INITIAL_SQUAD")`. **No `StartingSquadLock`.** After write, fails the transaction if any official club `Team.tokens` (treasury) changed or if any selected player's `overall` changed. Does not change ratings, IDs, faces, treasuries, or manager balances on success. Does not create auctions.

On production with existing mixed squads: **validation fails, no write** (any official club with players blocks apply).

---

## 5. StartingSquadLock behaviour

Model (`mgl/models.py`, ~1290–1375):

- `season` — `PositiveIntegerField`, **unique**
- `proposal` — `OneToOneField(StartingSquadProposal, on_delete=PROTECT)`
- `approved_by`, `approved_at`
- `club_count`, `players_assigned`

Helpers:

- `season_lock()` — lock row for `_season_number()` (`mgl/season_history.py` `ensure_active_season` + `current_season_number`)
- Second **approve** in the same season is rejected
- Generate is **not** blocked by an existing lock
- `start_next_season` creates a new `HistoricalSeason` but **does not** clear squads or delete the previous season’s lock (new season number → new lock slot)

**Not** registered in Django admin.  
**Not** written by Path B or Path C.  
Generate is blocked when a lock exists for the current season.

---

## 6. Player selection logic

| Topic | Path A (Control) | Path B (JSON apply) | Path C (disabled) |
|---|---|---|---|
| Source of players | `mgl.Player` rows already in DB | Same; IDs from `approved_starting_squads.json` | Free Agents (`Team` named Free Agents) |
| FC26 identity | `Player.fc27_id` required; snapshot compared on approve | Uses stored players; does not rewrite identity | Uses existing FA rows |
| Position matching | Exact `Player.position` vs `UFL_SQUAD_SHAPE` | JSON position vs player row | Position buckets in dead code |
| Duplicate prevention | Unique player ids in allocation; validate on approve | Unique across 364 slots | Per-team fill from remaining FA |
| Club assignment | All `teams.Team` | 14 `OFFICIAL_SL1_SHORT_NAMES` only | Every empty `teams.Team` (optional `--official-sl1`) |
| Free Agents | Excluded unless checkbox | Must **not** be FA | **Only** FA |
| Existing squad membership | Eligible pool requires `mgl_team` null. Approve does **not** clear clubs | Official clubs must be empty | Empty teams only |
| Player values / ratings | Not written | Not written | Not written |
| Player history | `PlayerOwnershipHistory` on approve only | History on `--apply` only | Would write `INITIAL_SQUAD` |
| Tokens | Snapshotted; approve aborts if changed | Untouched | Untouched (dead) |

Identity fields (`fc27_id`, name, face, overall) are **read**, not rewritten, by starting-squad code.

---

## 7. Position logic

### Current generator shape (`mgl/ufl_settings.py` → `UFL_SQUAD_SHAPE`)

```
2 GK, 5 CB, 1 RB, 1 LB, 1 RWB, 1 LWB,
3 CM, 2 CDM, 2 CAM, 1 RM, 1 LM, 1 RW, 1 LW, 3 ST
```

`PLAYERS_PER_CLUB` = sum of that tuple = **25**.  
`DEFAULT_STARTING_SQUAD` = **25**.  
`LeagueSettings.starting_squad_size` default **25** — **stored only**. The generator does **not** read this field. A repo-wide search shows `starting_squad_size` only on the model, `SettingsProxy`, and its migration.

Comment in `ufl_settings.py` mentions writing 22 then adding +1 CB / +1 CM / +1 ST; those extras are already in the tuple. UI copy still says “official 25-player starting structure”.

### Path B shape (`mgl/starting_squads.py` `SHAPE`)

26 players, no RWB/LWB keys:

`2 GK, 4 CB, 2 RB, 2 LB, 2 CDM, 2 CM, 2 CAM, 2 RM, 2 LM, 2 ST, 2 LW, 2 RW`

JSON players must match those exact `Player.position` values. OVR band in the approved JSON is **64–70** (totals 1741 per club).

Unused constant `LEGACY_SQUAD_SHAPE` in `ufl_settings.py` is the same 22-outfield+GK list **without** RWB/LWB and without the +1 CB/CM/ST extras. Nothing imports it for generation.

### Locked product shape (not in generator)

See table at top of this file (30 players, 2 of each listed role, 4 CB).

### Other hard-coded positional / size numbers found

| Number | Where | Role |
|---|---|---|
| 25 | `UFL_SQUAD_SHAPE`, `PLAYERS_PER_CLUB`, `DEFAULT_STARTING_SQUAD`, Control copy, `test_ufl_starting.py` | Path A size |
| 26 | `starting_squads.py`, `approved_starting_squads.json`, `starting_pool.py`, `populate_super_league_1` `--fill-squads`, disabled `generate_balanced_squads` | Legacy size |
| 28 | `DEFAULT_MAX_SQUAD`, `LeagueSettings.max_squad_size`, `SQUAD_LIMIT` / scouting, hub fallback, tests | Runtime roster cap |
| 30 | `Team.roster_limit` default, product lock, some press/CMS copy, disabled command sets `roster_limit=30` | Stored default; often **not** the runtime cap |
| 22 | Comment only in `ufl_settings.py` | Documentation drift, not a runtime size |

`site_cms.py` still contains stale public copy: “26 players and cannot exceed 30.”

---

## 8. Club / team model relationships

### `teams.Team` — **live Career Mode club**

Used by:

- Career Mode hub / team pages
- Starting squads (all three paths)
- Managers: `Team.manager` OneToOne → `User`
- Transfers, listings, auctions, recruitment, scouting
- Fixtures (`Fixture` / results attach to `Team`)
- Control Centre club/season tools
- `Player.mgl_team` → `teams.Team`

Fields relevant to this audit:

- `roster_limit` — `PositiveSmallIntegerField`, **default 30**
- `manager` — optional OneToOne User
- Official 14 short names live in `teams/official_sl1.py` (`OFFICIAL_SL1_SHORT_NAMES`). Names in code are mixed European clubs stored on the Premier League / Super League 1 row. Owner-stated production: 14 Premier League **test** clubs.

### `core.Club` — **legacy, unused by Career Mode**

Defined in `core/models.py` (`managed_club`). Inspection found **no** Python imports of `Club.objects` or `from core.models import Club` outside the model and its migration.

| Surface | Model used |
|---|---|
| Career Mode | `teams.Team` |
| Starting squads | `teams.Team` |
| Managers | `teams.Team.manager` + `ManagerApplication` |
| Transfers | `teams.Team` / `Player.mgl_team` |
| Fixtures | `teams.Team` |
| Control Centre | `teams.Team` |
| Production Career Mode | `teams.Team` |
| `core.Club` | Appears leftover. **Do not delete or merge** without a dedicated task |

Both model classes can remain. Starting-squad work must target `teams.Team` only.

---

## 9. Season reset process

There is **no** current command that “starts a new UFL season with 38 clubs and 30-player squads.”

### 9.1 `finalise_season` (`mgl/season_history.py`)

- Snapshots table / awards
- Sets season `FINALIZED` + `is_locked`
- **Does not** unassign players, recreate clubs, or clear locks for a *new* season number

### 9.2 `start_next_season` (`mgl/season_history.py`)

- Calls `ensure_active_season()` first (creates Season 1 only if **no** `HistoricalSeason` rows exist)
- Then requires there is **no** `ACTIVE` season (`ValueError` if one is still active — finalise first)
- Creates next `HistoricalSeason` (`number = latest + 1`)
- Updates active `League.season` string
- **Does not** reset squads, tokens, managers, fixtures, or `StartingSquadLock` rows (old season keeps its lock; new season has none)

### 9.3 Control “ENSURE CLUBS” (`control_season_controls`)

Owner-only POST `action=ensure_clubs` with confirm text `ENSURE CLUBS`. Calls `ensure_official_ufl_clubs()`:

- Creates **missing** official clubs: 14 PL (`official_sl1`) + 14 Championship + 14 League One = **42**
- May **rename / re-league** existing `Team` rows matched by short name or name
- Sets new clubs’ `Team.tokens` to **50.00**; does not overwrite tokens on reused clubs
- Does **not** apply starting squads, delete extra clubs, or touch players
- **Conflicts with locked 16 / 14 / 8 (38 clubs).** Do not run as the official season bootstrap.

This audit did not invoke it.

### 9.4 `mgl_reset` (`mgl/management/commands/mgl_reset.py`) — **catastrophic**

Deletes fixtures, results, press, rewards, news, packs, auctions; unassigns all players; **sets all manager tokens to 50**; clears `Team.manager`; **deletes all `Team` and `League` rows**. Keeps FC player identity rows.

**Do not run.** This is not a season-start tool.

### 9.5 What a future official season start would need (not implemented)

38 clubs: **16 Premier League / 14 Championship / 8 League One**, each with the locked 30-player squad. That pipeline does not exist. Do not reuse Path B’s 14×26 JSON or Path C.

---

## 10. Data safety risks

### If someone runs `generate_balanced_squads` today

`handle()` raises immediately. **No database writes. No clubs, players, managers, tokens, transfers, identities, or locks change.**

### If someone runs `apply_starting_squads` (no `--apply`)

Dry-run report only. **No writes.**

### If someone runs `apply_starting_squads --apply`

| Question | Answer |
|---|---|
| What data would change? | Only if validation passes: 364 `Player.mgl_team` assignments + ownership history. |
| Which clubs? | The 14 official Super League 1 `teams.Team` rows. |
| Which players? | Those listed in `approved_starting_squads.json` (must be unassigned, not FA). |
| Managers? | No. |
| Tokens? | No. |
| Transfers? | Blocked if live auctions exist; listings not rewritten. Assigned players leave the free pool. |
| Player identities? | No (`fc27_id`, ratings, faces unchanged). |
| `StartingSquadLock`? | **No** — Path B does not write it. |
| Could test data be lost? | **Not by overwrite of assigned players.** If any official club already has players, **apply aborts**. Empty official clubs would receive 26-player squads (wrong vs locked 30). |
| Could production be overwritten? | Assigned production squads are **not** cleared. Risk is assigning onto **empty** official clubs, or operators later combining this with `mgl_reset`. |

### If someone uses Control **Generate**

Proposal rows only. Live squads unchanged. Other DRAFT proposals marked SUPERSEDED. **Not blocked** by an existing `StartingSquadLock`. Approve of that draft would still fail if a lock exists.

### If someone uses Control **Approve & assign** (Owner + confirm)

| Question | Answer |
|---|---|
| What data would change? | Selected unassigned players get `mgl_team`; history `UFL_STARTING`; one `StartingSquadLock`; proposal APPROVED; news/audit. |
| Which clubs? | **All** `teams.Team` rows at generate time (not only the 14 official). |
| Which players? | Allocation set (OVR 64–69, unassigned). Already-owned players fail validation. |
| Managers / tokens? | Tokens must be unchanged or approve rolls back. Managers not reassigned. |
| Transfers? | Selected players cannot be live-listed or in live auctions. |
| Identities? | Must match snapshot or approve fails. |
| Lock? | **Yes** — created for current season. |
| Stacking risk? | **Yes.** Existing club squads are not cleared. If `occupied + 25 ≤ effective_roster_limit`, players are **added on top**. |
| Production overwrite? | Does not unassign existing players. Can **grow** test squads or fail closed if roster is full / players already owned. |

### Other high-severity risks (do not run)

- `mgl_reset` — wipes Career Mode structure and resets tokens to 50.
- Changing `UFL_SQUAD_SHAPE` to 30 while `max_squad_size` remains 28 would make `occupied + 30 > 28` fail approve.
- Path A vs Path B targeting different club sets.

---

## 11. Conflicting limits — which fields are actually used

### `effective_roster_limit(team)` (`mgl/ufl_settings.py`)

```
configured = max_squad_size()          # LeagueSettings.max_squad_size, default 28
stored     = team.roster_limit         # model default 30
if stored and stored < configured:
    return stored
return configured
```

A default team (`roster_limit=30`) therefore uses **28** at runtime (`30 < 28` is false → configured 28).

`assign_player`, market `assert_roster_space`, recruitment, most hub/team UI, and scouting roster checks use `effective_roster_limit`.

Exceptions (source-verified):

- `mgl/scouting.py` still defines unused `SQUAD_LIMIT = 28` and `SQUAD_FULL_MESSAGE = "Your squad is full — maximum 28 players."` The message is still raised on some scout-assign failures. `_squad_limit()` reads `max_squad_size()` (28 by default).
- `mgl/views.py` `admin_club_squad` computes `available_spaces` from **`team.roster_limit`** (default 30), not `effective_roster_limit`. That admin page can disagree with runtime enforcement.

### Field-by-field

| Field / constant | Default | Used at runtime for starting squads? |
|---|---|---|
| `UFL_SQUAD_SHAPE` / `PLAYERS_PER_CLUB` | 25 | **Yes** — Path A generate + approve |
| `LeagueSettings.starting_squad_size` | 25 | **No** — persisted only |
| `LeagueSettings.max_squad_size` | 28 | **Yes** — via `max_squad_size()` / `effective_roster_limit` |
| `DEFAULT_MAX_SQUAD` | 28 | Fallback when settings row missing |
| `Team.roster_limit` | 30 | **Only if strictly less than** configured max; default 30 is ignored in favour of 28 |
| Path B JSON / `PLAYERS_PER_CLUB` in `starting_squads.py` | 26 | **Yes** — only if `apply_starting_squads --apply` is used |
| Product lock | 30 | Documentation only — **not** in generator |

### Conflict summary (do not guess)

1. Generator produces **25** players (`UFL_SQUAD_SHAPE`).
2. `max_squad_size` defaults to **28** and **is** the usual runtime cap.
3. `Team.roster_limit` defaults to **30** but is **not** the runtime cap unless it is set **below** 28.
4. Path B and dead Path C still assume **26**.
5. Locked product rule is **30**. Code and tests still assume 25 and 28 (`test_ufl_starting.py`, `test_ufl_foundation.py`, hub “2/28”).

---

## 12. Required changes (plan only — not done)

These are gaps between locked product rules and current code. **Do not implement from this document.**

1. Replace `UFL_SQUAD_SHAPE` with the locked 30-player position table; `PLAYERS_PER_CLUB` becomes 30.
2. Align runtime roster: `DEFAULT_MAX_SQUAD`, `LeagueSettings.max_squad_size`, scouting `SQUAD_LIMIT`, hub fallback, and `effective_roster_limit` so **30** is the actual cap. Default `Team.roster_limit=30` then matches runtime instead of being ignored.
3. Decide whether `LeagueSettings.starting_squad_size` should drive the generator or be removed from the mental model (today it does nothing).
4. Generator must **not** stack on existing test squads: require empty clubs **or** an explicit Owner-approved clear/reassign policy.
5. Club bootstrap for **16 / 14 / 8** — new work. Do **not** reuse Path B 14×26 JSON. Do **not** treat `ensure_official_ufl_clubs()` (42 clubs: 14+14+14) as the official starter. That helper can **create and rename** `Team` rows.
6. Keep identity + token guards on approve.
7. Retire or permanently fence Path B `--apply` and Path C so operators cannot apply 26-player squads by habit.
8. Update tests and Control copy that hard-code 25 / 26 / 28.
9. Do not use `mgl_reset` as a season tool.
10. Leave `core.Club` untouched.

---

## 13. Recommended safe implementation sequence

Work on a **copy / staging** database. Keep production test data until the Owner explicitly authorises a cutover.

1. **Documentation freeze** (this file). Owner confirms the 30-player table and 38-club split.
2. **Limit alignment in code** (shape 30, max squad 30, `effective_roster_limit` actually 30) **without** running generate/approve on production.
3. **Empty-or-replace policy** — Owner decides how to retire the 14 mixed test squads (manual unassign vs dedicated one-shot that is not `mgl_reset`).
4. **Club bootstrap** 16 Premier League / 14 Championship / 8 League One (names/logos separately; Admin may rename later per DEC-032). Fence or replace the existing 42-club `ENSURE CLUBS` action so it cannot silently create 14+14+14.
5. **Generate on staging** — proposal only; inspect JSON; confirm 30 × 38, positions, unique `fc27_id`, OVR band.
6. **Approve on staging** — lock written; tokens/identities unchanged; no stacking.
7. **Tests** updated for 30 / 38; Path B/C still dry-run or error.
8. **Owner confirm**, then production generate + approve. Never `mgl_reset`. Never `generate_balanced_squads`. Do not use `apply_starting_squads --apply` for the official 30-player season.

---

## 14. Exact testing plan

Do **not** run write commands against production as part of this audit. Future implementation tests:

### Safety (must stay true today)

- `generate_balanced_squads` still raises `CommandError` with no writes.
- `apply_starting_squads` without `--apply` is dry-run.
- Control generate does not call `assign_player` and is **not** blocked by `StartingSquadLock`.
- Approve is Owner-only and requires `confirm_approval=1`.
- Approve blocked when `StartingSquadLock` exists for the season.
- `ENSURE CLUBS` is Owner-only and requires typed confirmation; still must not be used for the locked 38-club season.
- Token snapshot mismatch aborts approve.
- FC26 id / overall snapshot mismatch aborts approve.

### After a future 30-player implementation (staging)

- Each club exactly 30 players; exact locked position counts.
- Unique `fc27_id` across the allocation.
- Eligible OVR band as then specified.
- Existing assigned players not silently overwritten.
- Empty-club (or explicit replace) policy enforced — no stacking.
- Tokens and identities unchanged.
- Lock created once; second approve rejected.
- `core.Club` unused and untouched.
- Hub / recruitment / market / scouting all show roster **30**, not 28.

### UI / Control

- Owner can generate / regenerate / reject / approve.
- Admin can view the Control page; cannot approve (current `is_owner` gate).
- Empty, loading, and validation error states remain visible.

---

## 15. Rollback considerations

| State | Rollback |
|---|---|
| Proposal `DRAFT` or `REJECTED` | Delete or supersede proposal rows. **No live squad change.** |
| Generate only | Same. Safe. |
| Path B dry-run | Nothing to roll back. |
| Path B `--apply` succeeded | Ownership history `INITIAL_SQUAD`; **no lock**. Rollback = explicit unassign of those 364 players. **No safe built-in command exists.** Do not use `mgl_reset`. |
| Path A approve succeeded | `StartingSquadLock` + `UFL_STARTING` history + assigned `mgl_team`. Rollback needs an explicit, reviewed unassign that also deletes or archives the lock. **That command does not exist.** Inventing one is out of scope for this audit. |
| `mgl_reset` | Not a rollback tool. Destroys clubs, fixtures, and sets tokens to 50. |

Until a dedicated, Owner-approved revert exists, **treat approve and `--apply` as one-way on a given database.**

---

## File / function index

| File | Symbols |
|---|---|
| `mgl/ufl_settings.py` | `UFL_SQUAD_SHAPE`, `PLAYERS_PER_CLUB`, `DEFAULT_MAX_SQUAD`, `DEFAULT_STARTING_SQUAD`, `max_squad_size()`, `effective_roster_limit()` |
| `mgl/ufl_starting.py` | `target_clubs`, `eligible_queryset`, `generate_allocation`, `create_proposal`, `validate_allocation`, `approve_proposal`, `season_lock`, `reject_proposal` |
| `mgl/control_views.py` | `control_starting_squads`, `control_season_controls` (`ensure_clubs`) |
| `mgl/starting_squads.py` | `apply_starting_squads`, `validate_against_database` |
| `mgl/starting_pool.py` | unused 26-player pool preview |
| `mgl/services.py` | `assign_player` |
| `mgl/season_history.py` | `ensure_active_season`, `current_season_number`, `finalise_season`, `start_next_season` |
| `mgl/models.py` | `StartingSquadProposal`, `StartingSquadLock`, `LeagueSettings`, `HistoricalSeason`, `PlayerOwnershipHistory` |
| `players/models.py` | `Player` (`fc27_id`, `position`, `overall`, `mgl_team`, `is_free_agent`) |
| `teams/models.py` | `Team` (`roster_limit`, `manager`, `tokens`) |
| `teams/official_sl1.py` | 14 official short names + `ensure_official_sl1_clubs` |
| `teams/official_ufl_clubs.py` | 42-club ensure (14+14+14) — not the locked 38 |
| `core/models.py` | `Club` (legacy unused by Career Mode; still registered in `core/admin.py`) |
| `mgl/management/commands/propose_ufl_starting_pool.py` | print-only |
| `mgl/management/commands/apply_starting_squads.py` | dry-run / `--apply` |
| `mgl/management/commands/generate_balanced_squads.py` | **disabled** |
| `mgl/management/commands/populate_super_league_1.py` | 14-club bootstrap |
| `mgl/management/commands/mgl_reset.py` | catastrophic wipe |
| `mgl/data/approved_starting_squads.json` | Path B payload |
| `mgl/super_league.py` | official 14 club names |
| `mgl/test_ufl_starting.py` | asserts 25 |
| `templates/mgl/control_starting_squads.html` | Control UI |

---

## Inspection confirmations

- NO APPLICATION CHANGES
- NO DATABASE CHANGES
- NO MIGRATIONS
- NO PRODUCTION CHANGES
- NO SQUADS GENERATED
- `generate_balanced_squads` NOT RUN
- `apply_starting_squads` NOT RUN
- NO LOCKS CHANGED
- `StartingSquadLock` NOT MODIFIED
- Tokens, Career Mode logic, authentication, and permissions NOT CHANGED
