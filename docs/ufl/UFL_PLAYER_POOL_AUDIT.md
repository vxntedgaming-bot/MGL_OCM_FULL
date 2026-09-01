# UFL Player Pool Audit (Phase 2.2)

**Status:** INSPECTION ONLY.  
**Date:** 1 September 2026.  
**Method:** Read-only SQLite (`mode=ro`) against the project FC26 player database. In-memory calculation only. No Django writes. No generate/approve. No Season 1 apply.

**Database inspected:** local project SQLite used by this Career Mode tree (`db.sqlite3`).  
Player count matches the documented FC26 import size (~18,405 identities) plus two test rows without `fc27_id`. Production Railway was **not** opened. No production credentials were used.

**Rules used (unchanged):**

- Unassigned (`mgl_team` is null)
- Default generator excludes Free Agents (`is_free_agent=False`)
- OVR 64–69
- Exact `Player.position` match to the locked 30-player shape
- Exclude live/pending auction (`PENDING`, `LIVE`)
- Exclude pending/live listing (`PENDING`, `LIVE`)
- 38 clubs × 30 = **1,140** required

---

## STOP — shortages exist

The current default generator **cannot** build Season 1 starting squads.

Two independent blockers:

1. **Default eligible pool is 0.** Every unassigned FC26 player is flagged `is_free_agent=True`, so the canonical default filter excludes the entire unused pool.
2. **RWB and LWB do not exist in this FC26 dataset.** Required 76 + 76. Available **0 + 0** at every OVR, assigned or unassigned.

No players were invented. OVR was not loosened. Positions were not remapped. Owner decision is required.

---

## 1. Total player count

| Item | Count |
|---|---|
| `players.Player` rows | **18,407** |
| Clubs in this database | 14 (current test clubs) |
| `StartingSquadLock` rows | 0 |

---

## 2. Eligible player count

| Pool | Count | Can supply 1,140? |
|---|---|---|
| Canonical default (`include_free_agents=False`) | **0** | **No** |
| Same filters but including Free Agents (Control checkbox, not used here) | **6,225** | Numerically yes, except RWB/LWB are still 0 |
| All players OVR 64–69 | 6,470 | Includes 245 currently assigned |

OVR distribution below is for the **canonical default eligible pool (0)**. The Free-Agent-included 64–69 unassigned distribution is given in section 4 for visibility only. **This audit did not enable that checkbox and did not change the rule.**

---

## 3. Position availability (38 clubs)

Required = per-club count × 38.

### Canonical default (unassigned, not FA, 64–69, official positions, not auction/listing)

| Position | Required | Available | Surplus / Shortfall |
|---|---|---|---|
| GK | 76 | 0 | **−76** |
| CB | 152 | 0 | **−152** |
| RB | 76 | 0 | **−76** |
| LB | 76 | 0 | **−76** |
| RWB | 76 | 0 | **−76** |
| LWB | 76 | 0 | **−76** |
| CDM | 76 | 0 | **−76** |
| CM | 76 | 0 | **−76** |
| CAM | 76 | 0 | **−76** |
| LM | 76 | 0 | **−76** |
| RM | 76 | 0 | **−76** |
| LW | 76 | 0 | **−76** |
| RW | 76 | 0 | **−76** |
| ST | 76 | 0 | **−76** |
| **Total** | **1,140** | **0** | **−1,140** |

### If Free Agents were included (current checkbox — not enabled; report only)

Unassigned, OVR 64–69, official positions, not in live auction/listing:

| Position | Required | Available | Surplus / Shortfall |
|---|---|---|---|
| GK | 76 | 577 | +501 |
| CB | 152 | 1,230 | +1,078 |
| RB | 76 | 501 | +425 |
| LB | 76 | 498 | +422 |
| **RWB** | **76** | **0** | **−76** |
| **LWB** | **76** | **0** | **−76** |
| CDM | 76 | 511 | +435 |
| CM | 76 | 746 | +670 |
| CAM | 76 | 315 | +239 |
| LM | 76 | 409 | +333 |
| RM | 76 | 366 | +290 |
| LW | 76 | 101 | +25 |
| RW | 76 | 135 | +59 |
| ST | 76 | 836 | +760 |
| **Total** | **1,140** | **6,225** | still missing 152 wing-backs |

**Entire FC26 table, any OVR:** `RWB = 0`, `LWB = 0`. No player in this database has those position codes. Current 14-club test squads also have 0 RWB and 0 LWB.

---

## 4. OVR distribution

### Canonical default eligible (64–69)

| OVR | Count |
|---|---|
| 64 | 0 |
| 65 | 0 |
| 66 | 0 |
| 67 | 0 |
| 68 | 0 |
| 69 | 0 |
| **TOTAL eligible** | **0** |

### Unassigned 64–69 (all flagged Free Agent today)

| OVR | Count |
|---|---|
| 64 | 1,018 |
| 65 | 1,073 |
| 66 | 1,077 |
| 67 | 1,049 |
| 68 | 1,081 |
| 69 | 927 |
| **Total** | **6,225** |

### All players 64–69 (includes 245 assigned)

| OVR | Count |
|---|---|
| 64 | 1,066 |
| 65 | 1,120 |
| 66 | 1,117 |
| 67 | 1,080 |
| 68 | 1,131 |
| 69 | 956 |
| **Total** | **6,470** |

---

## 5. Exclusion counts

Independent counts (a player can appear in more than one row):

| Filter | Players |
|---|---|
| Already assigned to a club (`mgl_team` set) | **364** |
| Unassigned | 18,043 |
| `is_free_agent=True` | **18,043** (exactly the unassigned set) |
| `is_free_agent=True` and unassigned | 18,043 |
| Assigned and not Free Agent | 364 |
| OVR outside 64–69 | 11,937 |
| OVR inside 64–69 | 6,470 |
| Position not in official 14-role shape | **0** (no CF rows; no other codes) |
| Live or pending auction | **0** (2 auctions exist, both `ENDED`) |
| Pending or live listing | **0** (8 listings exist, all `CANCELLED`) |
| Offer listing (`OFFER`) | 0 |

Sequential funnel matching `eligible_queryset(include_free_agents=False)`:

| Step | Remaining |
|---|---|
| All players | 18,407 |
| OVR 64–69 | 6,470 |
| + official position | 6,470 |
| + unassigned | 6,225 |
| + not Free Agent | **0** |
| + not live/pending auction | 0 |
| + not pending/live listing | **0** |

**Primary exclusion of the unused FC26 pool:** `is_free_agent=True` on every unassigned row. Product copy says unused FC26 players are unassigned, not Free Agents. The stored flags do not match that rule. **This audit did not correct them.**

If Season 1 later unassigns the current 364 club players and leaves `is_free_agent=False`, only those 364 would enter the default eligible pool. Of those, **245** are OVR 64–69, and **0** are RWB/LWB. That is still far below 1,140 and still fails wing-backs.

---

## 6. FC26 identity integrity

| Check | Result |
|---|---|
| Player rows | 18,407 |
| With `fc27_id` (non-blank) | **18,405** |
| Without `fc27_id` | **2** |
| Duplicate `fc27_id` values | **0** |
| Blank names | 0 |

Rows without `fc27_id` (test leftovers, OVR outside the starting band):

| id | name | position | overall | assigned |
|---|---|---|---|---|
| 18406 | History Test Winger | LW | 74 | no |
| 18407 | Live Auction Midfielder | CM | 81 | no |

Both are Free Agents. They are not in the 64–69 eligible window.

---

## 7. Duplicate analysis

- **No duplicate FC26 IDs.** `fc27_id` is unique where present.
- **178** display-name groups share a name (198 extra rows). Examples: Pedrinho ×4, Juan Pérez ×4. These are different FC26 identities (different `fc27_id`), not duplicate records.
- No blank-name duplicates.
- Two rows without `fc27_id` are unique test names, not clones of FC26 players.

The generator keys uniqueness on player id and `fc27_id`. Name collisions are not a uniqueness failure.

---

## 8. Balanced-random feasibility

The live algorithm (`generate_allocation` → `_attempt` → `_snake_deal` → `_equalize`, max 80 attempts, max average-OVR gap 1.500) **returns immediately** if any position’s `have < need`.

An in-memory simulation of that algorithm was prepared for 38 dummy clubs. It was **not** run against a successful pool because:

- Default eligible count = 0
- Even the Free-Agent-included 64–69 unassigned pool has **RWB 0** and **LWB 0**

Therefore:

- Exact 30-player shape for 38 clubs: **not feasible** with current filters and current position codes
- No-duplicate 1,140 allocation: **not feasible** (cannot fill 152 wing-back slots)
- Average-OVR gap ≤ 1.500: **not reached** — the allocator never builds teams

No proposal was written. No players were assigned.

---

## 9. Shortages (Owner decision required)

| Shortage | Detail |
|---|---|
| Default eligible pool | **0 / 1,140** because unassigned FC26 rows are all Free Agents |
| RWB | **0 available in the entire database** (need 76) |
| LWB | **0 available in the entire database** (need 76) |

All other official positions have surplus in the unused 64–69 Free-Agent-flagged pool (LW is the tightest surplus: 101 vs 76). That surplus cannot be used under the current default FA filter, and it cannot replace missing wing-backs without a new Owner rule.

**Stopped.** Did not invent players, loosen OVR, change positions, or alter records.

---

## 10. Recommended next step

Wait for Owner decisions. Do **not** generate or approve starting squads. Do **not** run Season 1 apply.

Decisions needed (not implemented):

1. **Wing-backs.** FC26 in this database never uses `RWB` / `LWB`. Options only the Owner can choose later: change the locked shape, map from `RB`/`LB`, or import a different identity source. Mapping would be a new product rule.
2. **Free Agent flags.** The unused FC26 pool is stored as Free Agents, so the default generator sees nobody. Options later: include Free Agents for Season 1 only, or correct flags so unused players are unassigned (that would be a data change — not done here).
3. After those rules are decided, re-run this audit, then consider Season 1 bootstrap + Control generate.

---

## Confirmations

- NO APPLICATION CHANGES
- NO DATABASE CHANGES
- NO MIGRATIONS
- NO PRODUCTION CHANGES
- NO PLAYERS ASSIGNED
- NO CLUBS CREATED OR DELETED
- NO SQUADS GENERATED
- NO SEASON 1 BOOTSTRAP
- NO TOKENS CHANGED
- NO LOCKS CHANGED
