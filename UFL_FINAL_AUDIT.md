# UFL Final Project Audit

Audited against the final pre-launch master specification.
Status values: **PASS** | **PARTIAL** | **FAIL** | **NOT IMPLEMENTED**

This file is the pre-rebuild snapshot plus the intended fix. Implementation follows in the same pass.

## 1. Brand / source of truth

| Requirement | Status | Notes |
|---|---|---|
| Website is source of truth | PASS | Discord is outbox-only after commit |
| Discord is notification layer only | PASS | `discord_queue.queue_event` never rolls back website tx |
| EA FC26 is master player identity | PASS | IDs/names/source ratings not mutated by UFL workflows |
| Public copy is UFL not MGL | PARTIAL | User-facing copy is UFL; asset filenames still `mgl-*`; `/mgl/` routes kept for compatibility |
| Production CMS defaults UFL | PASS | `ufl_branding` + SiteSettings |

## 2. Players / economy

| Requirement | Status | Notes |
|---|---|---|
| No monetary player values | PASS | Tokens only |
| FC26 IDs/names/source ratings preserved | PASS | |
| Unassigned / assigned / listed / auction / FA statuses | PASS | `player_ufl_status` |

## 3. Starting squads

| Requirement | Status | Notes |
|---|---|---|
| 25 players, 64–69 OVR, UNASSIGNED only | PASS | `mgl/ufl_starting.py` |
| Written 22 + official extras +1 CB +1 CM +1 ST | PARTIAL | Generator already uses 5 CB / 3 CM / 3 ST. Control copy still said “no silent extras” |
| Preview only until Owner approval | PASS | |
| Generate does not assign / change tokens / Discord | PASS | |
| Owner-only approve, confirmation, atomic, stale-safe | PASS | Admin cannot approve |
| Never auto-apply | PASS | |

## 4. Squad limit 28

| Requirement | Status | Notes |
|---|---|---|
| Backend enforces 28 | PASS | `effective_roster_limit()` |
| Frontend communicates 28 | PARTIAL | Occupancy uses 28; some Team.roster_limit displays still show 30 |
| No transfer / auction / scout bypass | PASS | Occupancy includes incoming reservations |

## 5. Transfers

| Requirement | Status | Notes |
|---|---|---|
| BUY / SELL / SWAP, no loans | PASS | |
| List / offer / counter / accept / reject / withdraw | PASS | |
| League office approval before official | PASS | |
| Cross-club blocked server-side | PASS | |
| Max 5 active listings | PASS | |
| Max 3 new listings / 24h | PASS | |
| Listed remain owned, shown listed, off active XI | PASS | |
| Request releases | PASS | Approval required |

## 6. Auctions

| Requirement | Status | Notes |
|---|---|---|
| Max 3 submissions / 24h from own squad | PASS | |
| Durations 30/60/90/120 | PASS | |
| Seller cannot bid (UI + POST + crafted) | PASS | |
| Highest bidder wins, atomic tokens | PASS | |
| No bids → return to seller (club) | PASS | League-office unsold → FA |
| Active / ending soon / ended / won / unsold / returned | PARTIAL | Data exists; public UI grouping incomplete |
| Public cannot bid | PARTIAL | POST blocked for non-managers; signed-in members still saw bid chrome |
| Manager vs league-office Control split | FAIL | Control auctions mixed in one list |
| Managers cannot create official office auctions | PASS | `listing_kind` server-side |

## 7. Scouting

| Requirement | Status | Notes |
|---|---|---|
| Recruitment, not Send to team | PASS | Auto-recruit on success |
| One active scout | PASS | |
| Country / position / tier / level | PASS | |
| Tier OVR + base hours | PASS | Bronze 45–60 8h … Elite 82–91 48h |
| Level 1: 10 TKN, −2h all | FAIL | Code was L1 free/0h; paid ladder started at L2 |
| Level 2: 18 TKN, −4h | FAIL | Was L3 = −4h |
| Level 3: 25 TKN, −8h | FAIL | Was L4 flat −8h |
| Level 4: halves Gold/Elite only | PARTIAL | L4 halved Gold/Elite **and** still applied −8h on other tiers |
| Server-side timers | PASS | `returns_at` stored |
| Squad full → Control exception, not discard | PASS | |
| No invented players / no FC26 mutation | PASS | |

## 8. Press

| Requirement | Status | Notes |
|---|---|---|
| Max 4 qualifying questions / 24h | PASS | Create-time cap |
| +0.5 TKN per approved answer | PASS | `press:{pk}` idempotent |
| Max 2 TKN / 24h hard cap | PARTIAL | Implied by 4×0.5; no second ledger cap |
| No duplicate rewards | PASS | Idempotency key |
| Real activity questions, no fake cups | PASS | |
| Approval workflow | PASS | |

## 9. Matches / results

| Requirement | Status | Notes |
|---|---|---|
| Submit → opponent confirm → office approve | PASS | |
| Only approved results update table/stats | PASS | |

## 10. Releases

| Requirement | Status | Notes |
|---|---|---|
| Request does not immediately release | PASS | |
| Approval → FREE AGENT + Discord | PASS | |
| Visible on player / FA / activity | PASS | |

## 11. Tokens

| Requirement | Status | Notes |
|---|---|---|
| One authoritative ledger | PARTIAL | Balance = `ManagerApplication.tokens`; writes `RewardTransaction` **and** `auctions.TokenTransaction` on market/auction |
| UI does not double-count | PASS | Wallet/Control read RewardTransaction only |
| No negative balances | PASS | |
| Atomic / idempotent | PASS | `tx_key` |

## 12. Discord

| Requirement | Status | Notes |
|---|---|---|
| Website → commit → outbox → bot | PASS | |
| Discord failure does not roll back site | PASS | |
| Channels NEWS / PRESS / TRANSFER MARKET / AUCTIONS / FREE AGENTS | PASS | Aliases + legacy keys |
| DM only with numeric Discord User ID | PASS | |
| Creative listing / auction / FA payloads | PASS | |

## 13. UI / design system

| Requirement | Status | Notes |
|---|---|---|
| One unified UFL design system | FAIL | Multiple `mgl-*.css` skins + Control gold/black |
| Midnight / slate / controlled gold / cyan | FAIL | Heavy black-gold remaining |
| Shared tokens + components | PARTIAL | `mgl-theme.css` tokens exist but pages drift |
| Official logo consistently | PARTIAL | Used; filename still mgl-logo.png |
| Complete page rebuild (not a recolour) | FAIL | Pre-rebuild state |

## 14. Navigation / IA

| Requirement | Status | Notes |
|---|---|---|
| Public: HOME / LEAGUE / CLUBS / PLAYERS / TRANSFERS / AUCTIONS / SCOUTING / NEWS / PRESS / JOBS / RULES | PARTIAL | TABLES not LEAGUE; no public SCOUTING; extra STATISTICS |
| Manager MY CAREER set | PARTIAL | Hub exists; some dashboard modules missing |
| Control Centre authorised only | PASS | |
| Cups not presented as live | FAIL | Homepage “VIEW UFL CUP”; nav still listed Cups as live |

## 15. Manager Career Mode

| Requirement | Status | Notes |
|---|---|---|
| Hub attention-first | PARTIAL | Inbox exists; next fixture / active scout / press not on hub |
| My Squad 28 + valid actions only | PARTIAL | Listed players shown off-roster; some roster_limit 30 |
| My Auctions 3/24h | PASS | |
| My Scouting Career Mode | PASS | |
| My Tokens single ledger | PASS | |
| Notifications prioritised | PASS | |
| Career History | PASS | |

## 16. Control Centre

| Requirement | Status | Notes |
|---|---|---|
| Same design system as public | FAIL | Separate black/gold Control skin |
| Required Control pages | PARTIAL | No dedicated Releases page (approvals cover it) |
| Auction Control split | FAIL | |
| Starting squads Control copy | PARTIAL | Missing official +1/+1/+1 extras explanation |
| Permissions server-side | PASS | |

## 17. Dead / fake UI

| Requirement | Status | Notes |
|---|---|---|
| No decorative / dead buttons | FAIL | SQUAD REPORT disabled; holiday placeholder; footer `#` socials; live cup CTA |
| No fake live data | PARTIAL | Empty states honest; cup CTA was not |
| Holiday mode | NOT IMPLEMENTED | Placeholder only |

## 18. Security / safety

| Requirement | Status | Notes |
|---|---|---|
| Cross-club / self-bid / Control / ownership / tokens | PASS | Covered by tests |
| No destructive migrations / no FC26 mutation / no auto squads | PASS | |
| Railway config intact | PASS | |

## 19. Tests (pre-rebuild)

449 tests passing on SQLite isolation. Coverage not collected.

## Pre-rebuild verdict

**NOT READY — FIX REQUIRED**

Must fix before claiming manual-test readiness: design system, public IA, cups honesty, scout level math, Control auction split, token dual-write, dead buttons, hub completeness.
