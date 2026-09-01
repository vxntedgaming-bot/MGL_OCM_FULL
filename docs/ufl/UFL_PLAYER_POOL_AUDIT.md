# UFL — Player pool audit

**Date:** 2026-09-01  
**Scope:** read-only inspection of the local imported FC26 dataset.  
**Database used:** `/tmp/MGL_LIVE/db.sqlite3` in SQLite read-only mode.  
**Production Railway:** not opened.  
**Writes:** none.  
**Owner lock:** **DEC-042**.

This file has two sections:

1. **Season 1 feasibility under DEC-042** — the current locked interpretation.
2. **Historical default-filter STOP** — what the *current generator code* still sees if it keeps excluding `is_free_agent=True` and matching exact positions.

---

## 1. Season 1 feasibility under DEC-042 (current lock)

### Locked interpretation

| Product status | Meaning |
|---|---|
| **UNSIGNED** | FC26 player with no UFL club. Recruitment pool. **Not** automatically a UFL Free Agent. |
| **UFL Free Agent** | Only via explicit UFL processes (pack/scout reject, admin unsigned auction with no bid, other approved FA paths). |
| **Club-owned** | Assigned to a UFL club. |
| **Temporarily listed** | Manager-released auction. Unsold → **returns to original club**. |
| Stored `is_free_agent` | **Not** product status. Do **not** mass-edit the 18k+ rows. |

**Season 1 starting-squad eligibility (bootstrap only):**

- UNSIGNED players are eligible **regardless of** the stored `is_free_agent` flag.
- RB may fill **RB or RWB**.
- LB may fill **LB or LWB**.
- OVR **64–69**.
- This does **not** publish those players as public UFL Free Agents.

### Dataset size (unchanged)

| Metric | Count |
|---|---|
| Total `mgl_player` rows | 18,407 |
| Rows with `fc27_id` | 18,405 |
| Duplicate `fc27_id` | **0** |
| Rows without `fc27_id` | 2 (test leftovers) |
| Assigned (`mgl_team_id` set) | 364 |
| Unassigned | 18,043 |

### Eligible UNSIGNED pool (OVR 64–69, no club)

| Filter | Count |
|---|---|
| Unassigned, OVR 64–69 | **6,225** |
| of which stored `is_free_agent=True` | 6,225 |
| of which stored `is_free_agent=False` | 0 |

DEC-042 treats all **6,225** as Season 1 eligible. The flag is ignored for this bootstrap only.

### Position availability after RB→RWB / LB→LWB mapping

Demand = 38 clubs × locked 30-player shape.

| Slot | Demand (38 clubs) | Eligible UNSIGNED 64–69 | Surplus after mapping |
|---|---|---|---|
| GK | 76 | 577 | +501 |
| CB | 152 | 1,230 | +1,078 |
| RB | 76 | 501 native RB | +425 leftover after filling RB |
| LB | 76 | 498 native LB | +422 leftover after filling LB |
| RWB | 76 | 0 native RWB; **425 leftover RB** | +349 |
| LWB | 76 | 0 native LWB; **422 leftover LB** | +346 |
| CDM | 76 | 511 | +435 |
| CM | 76 | 746 | +670 |
| CAM | 76 | 315 | +239 |
| LM | 76 | 409 | +333 |
| RM | 76 | 366 | +290 |
| LW | 76 | 101 | +25 |
| RW | 76 | 135 | +59 |
| ST | 76 | 836 | +760 |
| **Total** | **1,140** | **6,225** | every slot covered |

Tightest slot after mapping: **LW** (+25). **RWB / LWB are fully coverable from leftover RB / LB.**

### In-memory allocation simulation

- Dummy clubs: 38 in-memory objects. **No clubs created in the database.**
- Algorithm: same greedy as `mgl/ufl_starting.py` (`build_balanced_proposal`) with DEC-042 eligibility and RB/LB mapping.
- Seeds: `20260901`, `1`, `42`, `99`, `20260831`.
- Database connection: `mode=ro`.

| Seed | Allocated | Unique players | Unique fc27_id | OVR 64–69 | RWB filled by leftover RB | LWB filled by leftover LB | Max club avg − min club avg | Total-OVR spread |
|---|---|---|---|---|---|---|---|---|
| 20260901 | 1,140 | 1,140 | 1,140 | yes | yes | yes | 0.000 | 0 |
| 1 | 1,140 | 1,140 | 1,140 | yes | yes | yes | 0.000 | 0 |
| 42 | 1,140 | 1,140 | 1,140 | yes | yes | yes | 0.033 | 1 |
| 99 | 1,140 | 1,140 | 1,140 | yes | yes | yes | 0.000 | 0 |
| 20260831 | 1,140 | 1,140 | 1,140 | yes | yes | yes | 0.000 | 0 |

Average-OVR gap limit is **1.500**. All seeds are well inside.

**1140 players can be allocated** under DEC-042.

### What this simulation did **not** do

- create clubs
- delete clubs
- assign players
- generate production squads
- run Season 1 bootstrap
- edit `is_free_agent`
- change tokens or locks

---

## 2. Historical STOP (current generator code — not DEC-042)

The shipped generator (`mgl/ufl_starting.py`) still:

- excludes `is_free_agent=True` unless the Control checkbox is ticked
- matches **exact** `Player.position` (no RB→RWB / LB→LWB)

Under those **old** filters:

| Filter | Count |
|---|---|
| Default eligible (unassigned + `is_free_agent=False` + OVR 64–69) | **0** |
| Native RWB / LWB in entire DB | **0 / 0** |

That is why the earlier audit stopped. **DEC-042 replaces that interpretation for Season 1.** The generator code has **not** been updated yet. Do **not** mass-flip `is_free_agent` to paper over the old filter.

### Native positions in the full 18,407-row table (historical)

| `position` | Count | Assigned | Unassigned | Unassigned 64–69 |
|---|---|---|---|---|
| GK | 1,979 | 26 | 1,953 | 577 |
| CB | 3,211 | 52 | 3,159 | 1,230 |
| LB | 1,349 | 26 | 1,323 | 498 |
| RB | 1,352 | 26 | 1,326 | 501 |
| LWB | 0 | 0 | 0 | 0 |
| RWB | 0 | 0 | 0 | 0 |
| CDM | 1,511 | 26 | 1,485 | 511 |
| CM | 2,147 | 52 | 2,095 | 746 |
| CAM | 1,067 | 26 | 1,041 | 315 |
| LM | 1,020 | 26 | 994 | 409 |
| RM | 1,022 | 26 | 996 | 366 |
| LW | 335 | 26 | 309 | 101 |
| RW | 369 | 26 | 343 | 135 |
| ST | 2,045 | 26 | 2,019 | 836 |

---

## 3. Remaining blockers (code / process — not pool size)

| Blocker | Status |
|---|---|
| Eligible UNSIGNED 64–69 pool under DEC-042 | **Resolved** — 6,225 |
| RWB / LWB under DEC-042 mapping | **Resolved** — leftover RB / LB cover demand |
| Generator still uses old FA exclude + exact position | **GAP** — do not generate production squads until updated |
| Free Agents page still lists `is_free_agent=True` | **GAP** — product page must use genuine UFL FA status later |
| Production Season 1 apply | **Blocked** until Owner authorises |
| Production squad generate / approve | **Blocked** until generator implements DEC-042 and Owner authorises |

---

## Confirmations

- NO PRODUCTION CHANGES
- NO CLUBS CREATED
- NO CLUBS DELETED
- NO PLAYERS ASSIGNED
- NO SQUADS GENERATED
- NO TOKENS CHANGED
- NO LOCKS CHANGED
- NO mass-edit of `is_free_agent`
