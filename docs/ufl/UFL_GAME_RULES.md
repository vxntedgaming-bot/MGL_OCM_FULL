# UFL Game Rules

**Status:** Rules that are actually implemented.  
Anything not found in code is **UNDECIDED / NEEDS CONFIRMATION**.

Do not treat this file as a wishlist.

---

## Divisions and clubs

**CONFIRMED**

- Three division slugs are live in navigation: Premier League (`PL`), Championship (`CH`), League One (`L1`).
- Super League 1 was renamed in place to Premier League so club IDs and fixtures stay attached.
- Official Premier League club set created by seed/import (14): Real Madrid, Barcelona, Atletico Madrid, Manchester United, Chelsea, Manchester City, Arsenal, Liverpool, Tottenham, Paris Saint-Germain, Lyon, Marseille, Bayer Leverkusen, Bayern Munich.
- MLS is not an active competition in code/nav.
- Cups exist as **Coming soon** catalogue pages only: Phantom Cup, UFL Champions League, UFL Europa League, UFL Europa Conference League. No live cup fixture system was found.

**UNDECIDED / NEEDS CONFIRMATION**

- Promotion / relegation between PL, Championship, League One.
- How many clubs Championship / League One must have before fixtures are generated.
- Whether a 14-team single round-robin (13 games, 91 fixtures) is the standing league format for every division. `ensure_league_fixtures` implements that shape for a 14-team division; running it on production is forbidden by README.

---

## Squad size

**CONFIRMED**

- League setting `max_squad_size` default **28**.
- Official UFL **starting** squad size **25** (`UFL_SQUAD_SHAPE`).
- Scouting copy and `mgl/scouting.py` `SQUAD_LIMIT = 28` (also reads `max_squad_size()`).
- `Team.roster_limit` model default is **30**. Effective cap is `effective_roster_limit(team)`: stored team limit if it is smaller than the league max, otherwise the league max.

**UNDECIDED**

- Whether any live club still has `roster_limit` 30 and is therefore allowed 28 (league) or 30 (if someone raises league max). Do not “fix” stored limits without instruction.

---

## Starting squad shape (UFL official)

**CONFIRMED** (`mgl/ufl_settings.py`)

```
2 GK, 5 CB, 1 RB, 1 LB, 1 RWB, 1 LWB,
3 CM, 2 CDM, 2 CAM, 1 RM, 1 LM, 1 RW, 1 LW, 3 ST
```

Comment in code: written structure totals 22; generator then adds +1 CB, +1 CM, +1 ST (already reflected in the tuple above).

OVR band for the UFL generator: **64–69**.

Preview-only until Owner approves. See `UFL_APPROVAL_SYSTEM.md`.

Legacy 14×26 `apply_starting_squads` (seed `20260828`, 1,741 OVR per club) is a **different** path. Do not use it to create UFL 25-player squads. `generate_balanced_squads` is disabled.

---

## Player states

**CONFIRMED**

| State | Meaning |
|---|---|
| UNASSIGNED | FC26 pool player, no UFL club, not a Free Agent |
| ASSIGNED | `mgl_team` set |
| TRANSFER LISTED | Club still owns the player; listing LIVE / OFFER / PENDING |
| IN NEGOTIATION | Accepted or open offer waiting |
| AUCTION | Live or pending auction; occupies a roster slot until settlement |
| FREE AGENT | Approved release, or unsold league-office auction. Sign for **0 TKN** |

Unused FC26 pool players must not be flagged Free Agent. `fc27_club` is FC26 reference data only.

---

## Tokens (currency)

**CONFIRMED**

- Personal balance: `ManagerApplication.tokens`.
- New registration credit: `LeagueSettings.starting_tokens` default **20**.
- On some approve paths, `managers.services.STARTING_TOKENS = 20` if tokens are 0/None.
- Authoritative writes: `credit_manager` / `debit_manager` → `RewardTransaction`.
- Free-agent signing costs **0**.
- Auction bids reserve personal tokens; being outbid refunds the previous bidder.
- Press reward default **0.50 TKN**, cap **4** answers / 24h (`press_reward`, `press_per_24h`).
- Match approval pays **1.00 TKN** per side (`match_official._pay_match_tokens`, category `MATCH`).
- Scout **upgrade** costs: L2 **18**, L3 **25**, L4 **25**. L1 is granted at hire (listed cost 10 in comments; not charged again).
- Scout **mission** token cost is used only if `scout_requires_tokens` is True (default **False**).
- Recruitment Drive pack costs: **UNKNOWN** without reading pack open function each time — packs have `Pack.cost`. Do not invent prices here.
- Club `Team.tokens` default 50 is **not** the personal balance.

**UNDECIDED**

- Full published reward table (weekly/monthly award amounts) — batches exist; exact token figures should be read from award code before stating them.
- Whether club treasury is spent anywhere on the current market path.

---

## Transfer rules (summary)

**CONFIRMED**

- No loans.
- Transfer window function **always returns True**.
- Max **5** active listings per club; max **3** new listings / 24h.
- Manager auctions: max **3** club auctions / 24h; durations 30/60/90/120 minutes (configurable).
- Listing a player for sale creates status **LIVE** immediately (no Owner gate to list).
- A buy offer goes to the seller; seller accept sets listing **PENDING**; Owner/Admin approve completes the sale and moves the player.
- Instant purchase without that flow is blocked.
- Swaps (offered players) are supported on listed purchase offers.

See `UFL_TRANSFER_RULES.md`.

---

## Fixtures and results

**CONFIRMED**

- Fixtures are gated by `is_released`.
- Managers submit only for fixtures that include their club.
- Submission stores team stats, goals, assists, defender ratings (0.0–10.0), GK saves, outfield ratings (1.0–10.0).
- Opponent inbox Accept/Reject does **not** make the result official.
- Owner/Admin approve applies stats, marks fixture COMPLETED, writes news, creates press questions, pays match tokens.
- Owner may override missing opponent accept (`override=1`).
- Locked season (`HistoricalSeason.is_locked`) blocks official result changes.
- Tables and public stats use **approved** submissions only.
- Rollback of an approved result exists (`control_rollback_result` / `unapprove_match_submission`).

**UNDECIDED**

- Lineup deadline enforcement (`Fixture.lineup_deadline` exists; whether submit is blocked after it is **NEEDS CONFIRMATION** — inspect `submit_match` before stating a rule).
- Walkover / forfeit rules — not found as a named system.

---

## Scouting

**CONFIRMED**

- One manager-wide scout HQ (not per Bronze/Silver/Gold parallel).
- One active scout at a time.
- Level 1–4; level survives leaving/joining clubs.
- Hour reductions by level: L1 −2h, L2 −4h, L3 −8h; L4 halves Gold/Elite only.
- Completed scout recruits an eligible **unassigned** FC26 player onto the current club if space exists.
- Full squad: assignment can raise a Control exception (`ScoutSquadException`).
- `scout_can_recruit()` in `ufl_settings` **hard-codes True**. `LeagueSettings.scout_can_recruit` exists and a migration once set it False; the live helper ignores the row.

**UNDECIDED**

- Whether Owner wants `LeagueSettings.scout_can_recruit` to actually gate recruitment again.

---

## Recruitment Drive and Youth Academy

**CONFIRMED**

- Recruitment Drive: open a pack, choose one player (`RecruitmentOpening`).
- Youth Academy: Coming Soon page only. No academy players generated.

---

## Press

**CONFIRMED**

- Triggers include MATCH, SIGNING, APPOINTMENT, ODD_MATCHDAY, DAILY, RELEASE.
- Answers need Owner/Admin approval before they are official / rewarded.
- Reward and 24h cap from LeagueSettings (defaults 0.50 / 4).

---

## Jobs

**CONFIRMED**

- Vacant clubs listed on `/jobs/` and `/job-offers/`.
- Application fields: gamertag, Discord user id, games per week (1–5+), referred by, new-gen confirmation.
- Owner/Admin approve assigns the manager to the club.
- Account registration does **not** appoint a club. Club apply does not appoint until approved.

---

## Awards and history

**CONFIRMED**

- Weekly and monthly award batches exist and require Control approval.
- Historical seasons can be finalized and locked.
- Hall of Fame is `/history/` (`historical_tables` with `is_hall_of_fame=True`).

**UNDECIDED**

- Exact award criteria and token amounts until read from the award calculator at change time.

---

## What is not a current game rule

Do not invent:

- Loan rules
- Closed transfer windows
- Promotion/relegation
- Live cup competitions
- Youth Academy contracts
- Player compare / head-to-head
- A stored MEMBER role
