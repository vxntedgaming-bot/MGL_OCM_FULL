# UFL Game Rules

**Status:** Official Phase 1 locked rules (Owner, 2026-09-01) plus what the current code actually does.

Anything not in Phase 1 and not confirmed in code is **UNDECIDED / NEEDS OWNER DECISION**.

Do not implement gaps from this documentation pass.

---

## PHASE 1 LOCKED — official product rules

### Starter league

| Division | Clubs |
|---|---|
| Premier League | 16 |
| Championship | 14 |
| League One | 8 |
| **Total** | **38** |

Clubs start randomly generated. Admin can change name, logo, and branding/identity where supported at any time.

### Starting squad (every new season / reset)

Roster limit **30**. Structure:

```
2 GK
4 CB
2 RB
2 LB
2 RWB
2 LWB
2 CDM
2 CM
2 CAM
2 LM
2 RM
2 LW
2 RW
2 ST
```

Total = 30.

### Transfer window

Does **not** close. Remains open continuously. No automatic closing period.

### Market approvals

- Player listings: **no** Admin/Owner approval
- Release listings: **no** Admin/Owner approval
- Transfer requests: **yes** — Admin/Owner approval before official/live

### Tokens

0.5 increments only (0, 0.5, 1, 1.5, …). Invalid: 0.25, 0.75, 1.25, 1.75.

### Weekly rewards

Period: **Sunday 10:00 AM → next Sunday 10:00 AM**. Time zone: **NEEDS OWNER DECISION** (not specified).

| Reward | Amount |
|---|---|
| Approved league game | +1 TKN |
| TOTW | +0.5 TKN per selected player from that manager’s team |
| Press conference answer | +0.5 TKN |
| Manager of the Week | +1 TKN |
| Weekly #1 goalscorer (that player’s manager) | +0.5 TKN |
| Weekly #1 assists (that player’s manager) | +0.5 TKN |
| Cup winner | +10 TKN |
| Cup runner-up | +5 TKN |

No other cup placing is locked.

### Packs / scouting / recruitment

Admin/Owner control pack availability (add/remove/release/replace/change/temporary). Each pack has its **own** max opening count. Pack costs use 0.5 increments. Scout/recruitment setting must enforce configured restrictions.

### Jobs

MEMBER → job application → Admin reviews → Admin accepts → member gets the job.

Fields: EA ID / gamertag, Discord username, games per week **1–3 / 3–5 / 6+**, referred by, new-gen checkbox: “I confirm I am playing on a new-generation console.”

### Virtual game

Matches are played on the external/virtual football game. The website stores official UFL state.

---

## CURRENT PRODUCTION / TEST STATE (not the final league)

Owner confirmed:

- 14 clubs currently exist; all Premier League.
- Test/development data. Mixed player counts/positions. Not the 30-player structure.
- Nothing currently locked.
- Production is live; only the Owner currently has visibility/access.
- **Do not reset this data** in a documentation or ordinary development task.

---

## Divisions and clubs

**CURRENT CODE**

- Three division slugs in navigation: Premier League (`PL`), Championship (`CH`), League One (`L1`).
- Super League 1 was renamed in place to Premier League.
- Seed/import creates 14 Premier League clubs (Real Madrid, Barcelona, Atletico Madrid, Manchester United, Chelsea, Manchester City, Arsenal, Liverpool, Tottenham, Paris Saint-Germain, Lyon, Marseille, Bayer Leverkusen, Bayern Munich).
- MLS is not an active competition in code/nav.
- Cups exist as **Coming soon** catalogue pages only.

**GAP:** Phase 1 locked 16/14/8. Current code/data: 14 Premier League test clubs.

**UNDECIDED:** Promotion / relegation. Fixture format per division size (14-team round-robin exists as a command; 16- and 8-club formats are **not** specified beyond club counts).

---

## Squad size

**PHASE 1 LOCKED:** 30.

**CURRENT CODE:** `LeagueSettings.max_squad_size` default **28**. `UFL_SQUAD_SHAPE` totals **25**. Scouting `SQUAD_LIMIT = 28`. `Team.roster_limit` default **30**. `effective_roster_limit()` uses league max unless the stored team limit is smaller.

**GAP:** Do not change code or production squads in this pass.

---

## Starting squad shape

**PHASE 1 LOCKED:** 30-player structure above.

**CURRENT CODE** (`mgl/ufl_settings.py` `UFL_SQUAD_SHAPE`) is still:

```
2 GK, 5 CB, 1 RB, 1 LB, 1 RWB, 1 LWB,
3 CM, 2 CDM, 2 CAM, 1 RM, 1 LM, 1 RW, 1 LW, 3 ST
```

OVR band for the current generator: **64–69**. Preview-only until Owner approves. `StartingSquadLock` is protected.

Legacy 14×26 `apply_starting_squads` is a different path. `generate_balanced_squads` is disabled. Do not run either to invent the locked 30s unless the Owner asks in a later implementation task.

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

**PHASE 1 LOCKED:** 0.5 increments only.

**CURRENT CODE**

- Personal balance: `ManagerApplication.tokens`.
- New registration credit: `LeagueSettings.starting_tokens` default **20**.
- On some approve paths, `managers.services.STARTING_TOKENS = 20` if tokens are 0/None.
- Authoritative writes: `credit_manager` / `debit_manager` → `RewardTransaction`.
- Free-agent signing costs **0** (valid increment).
- Auction bids reserve personal tokens; being outbid refunds the previous bidder.
- Press reward default **0.50 TKN**, cap **4** answers / 24h.
- Match approval pays **1.00 TKN** per side (matches Phase 1 approved-league-game reward).
- Scout **upgrade** costs: L2 **18**, L3 **25**, L4 **25**. L1 is granted at hire (listed cost 10 in comments; not charged again).
- Scout **mission** token cost is used only if `scout_requires_tokens` is True (default **False**).
- `Pack.cost` is Decimal; **no 0.5-increment validator found**.
- Club `Team.tokens` default 50 is **not** the personal balance.

**GAP:** Code will accept 0.25 etc. if posted. Weekly TOTW / MOTW / top scorer / assists / cup amounts are locked in Phase 1; whether the award calculator pays those exact figures is **not confirmed as implemented**.

**UNDECIDED:** Whether club treasury is spent on the current market path. Monthly awards (code exists; not in the Phase 1 weekly table).

---

## Transfer rules (summary)

**PHASE 1 LOCKED:** window never closes. Listings need no approval. Transfer requests need Admin/Owner approval before official.

**CURRENT CODE**

- No loans.
- Transfer window function **always returns True** (matches Phase 1).
- Max **5** active listings per club; max **3** new listings / 24h (code defaults; not restated in Phase 1 — **UNDECIDED** whether they stay).
- Manager auctions: max **3** club auctions / 24h; durations 30/60/90/120 minutes (configurable).
- Listing a player for sale creates status **LIVE** immediately (matches Phase 1).
- A buy offer goes to the seller; seller accept sets listing **PENDING**; Owner/Admin approve completes the sale (matches Phase 1 transfer-request approval).
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

**PHASE 1 LOCKED:** Admin/Owner control packs. Per-pack opening limits. 0.5-increment costs. `scout_can_recruit` must enforce.

**CURRENT CODE**

- One manager-wide scout HQ (not per Bronze/Silver/Gold parallel).
- One active scout at a time.
- Level 1–4; level survives leaving/joining clubs.
- Hour reductions by level: L1 −2h, L2 −4h, L3 −8h; L4 halves Gold/Elite only.
- Completed scout recruits an eligible **unassigned** FC26 player onto the current club if space exists.
- Full squad: assignment can raise a Control exception (`ScoutSquadException`).
- `scout_can_recruit()` in `ufl_settings` **hard-codes True**. `LeagueSettings.scout_can_recruit` exists and a migration once set it False; the live helper ignores the row.

**GAP:** Setting does not enforce. Per-pack max openings are not confirmed as a dedicated configurable field.

---

## Recruitment Drive and Youth Academy

**PHASE 1 LOCKED:** Admin/Owner decide which packs are available (add/remove/release/replace/change/temporary). Each pack has its own opening limit.

**CURRENT CODE**

- Recruitment Drive: open a pack, choose one player (`RecruitmentOpening`). `Pack.active` and `Pack.cost` exist.
- Youth Academy: Coming Soon page only. No academy players generated.

**GAP:** Per-pack configurable maximum openings is not confirmed in the current `Pack` model. Do not invent pack catalogue contents.

---

## Press

**CONFIRMED**

- Triggers include MATCH, SIGNING, APPOINTMENT, ODD_MATCHDAY, DAILY, RELEASE.
- Answers need Owner/Admin approval before they are official / rewarded.
- Reward and 24h cap from LeagueSettings (defaults 0.50 / 4).

---

## Jobs

**PHASE 1 LOCKED:** MEMBER submits job application → Admin reviews → Admin accepts → member gets the job. Fields: EA ID / gamertag, **Discord username**, games per week **1–3 / 3–5 / 6+**, referred by, new-gen wording “I confirm I am playing on a new-generation console.”

**CURRENT CODE**

- Vacant clubs listed on `/jobs/` and `/job-offers/`.
- Application fields: gamertag, **Discord user id (must be numeric)**, games per week **1, 2, 3, 4, 5+**, referred by, new-gen confirmation.
- Owner/Admin approve assigns the manager to the club.
- Account registration does **not** appoint a club. `apply_for_club` also requires an **approved** `ManagerApplication` first.

**GAP:** Dropdown options and Discord username vs ID. Extra manager-application approval step vs locked MEMBER → job → accept flow. **NEEDS OWNER DECISION** whether that extra step stays.

---

## Awards and history

**PHASE 1 LOCKED:** Weekly window Sunday 10:00 AM → Sunday 10:00 AM and the token table in the Phase 1 section.

**CURRENT CODE**

- Weekly and monthly award batches exist and require Control approval.
- Historical seasons can be finalized and locked.
- Hall of Fame is `/history/` (`historical_tables` with `is_hall_of_fame=True`).

**GAP:** Sunday 10:00 AM period and the exact TOTW / MOTW / top scorer / assists / cup amounts are not confirmed as implemented. Time zone **NEEDS OWNER DECISION**.

---

## What is not a current game rule

Do not invent:

- Loan rules
- A closing transfer window (Phase 1 locked: never closes)
- Promotion/relegation (**UNDECIDED**)
- Live cup competitions (pages exist; cup winner/runner-up token amounts are locked for when cups go live)
- Youth Academy contracts
- Player compare / head-to-head
- A stored MEMBER role
- Token fractions other than 0.5 increments
