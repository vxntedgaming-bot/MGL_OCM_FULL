# UFL Final Pre-Launch Report

Status: **READY FOR MANUAL TESTING**

This pass audited the live Django Career Mode app, aligned remaining rule mismatches, unified the visual system, and re-ran the full local suite. Production data, tokens, FC26 identities, and starting squads were not touched. No destructive migrations were added.

## 1. Requirements audit

| Area | Status | Notes |
|---|---|---|
| Website source of truth / Discord outbox | PASS | Discord cannot roll back website commits |
| FC26 master identity | PASS | IDs, names, source ratings unchanged |
| Tokens-only economy | PASS | Authoritative ledger is `RewardTransaction` |
| Starting squads 25 / 64–69 / preview / Owner approve | PASS | Official extras +1 CB +1 CM +1 ST documented |
| Squad cap 28 | PASS | Backend occupancy + display now use 28 |
| Transfers BUY/SELL/SWAP + office approval | PASS | No loans |
| Listings 5 active / 3 per 24h | PASS | |
| Auctions 3/24h, 30–120m, no self-bid, unsold return | PASS | Bid chrome is manager-only |
| Control manager vs league-office auctions | PASS | Split lists |
| Scouting recruit, one active, tiers, country/position | PASS | |
| Scout levels L1 −2h / L2 −4h / L3 −8h / L4 half Gold+Elite | PASS | Existing L1 managers now get −2h (buff). L4 Gold/Elite 16h/24h |
| Press 4/24h, +0.5, hard 2 TKN cap, idempotent | PASS | |
| Matches submit → confirm → approve | PASS | |
| Releases request → approve → FA | PASS | |
| Discord channels + numeric User ID DMs | PASS | |
| Public IA HOME / LEAGUE / CLUBS / PLAYERS / TRANSFERS / AUCTIONS / SCOUTING / NEWS / PRESS / JOBS / RULES | PASS | |
| Manager MY CAREER | PASS | |
| Cups not presented as live | PASS | Coming soon |
| Unified UFL design system | PASS | Shared tokens + shell; inner pages inherit `mgl-*` class names |
| Holiday mode | NOT IMPLEMENTED | Placeholder removed; no fake holiday controls |
| Public asset filenames still `mgl-*` | PARTIAL | Compatibility; user-facing copy is UFL |
| Internal `/mgl/` routes | PARTIAL | Kept for Railway / Discord / tests |

## 2. Token architecture

**Authoritative ledger:** `ManagerApplication.tokens` written only through `credit_manager` / `debit_manager` → `RewardTransaction`.

`auctions.TokenTransaction` is **LEGACY**. `record_token_transaction()` is a no-op. Market/auction/scout payments still call it for compatibility but no longer insert rows. Wallet, Control, and hub history read `RewardTransaction` only.

Idempotency: `reference` + open-row lookup. No negative balances unless explicitly allowed.

## 3. Transfer architecture

Manager lists or offers → counter/accept/reject/withdraw → League Office approve → atomic ownership + token settlement → news + Discord outbox.

Listed players remain owned, leave the active XI, and count toward occupancy. Cross-club actions are rejected server-side. Max 5 live listings and 3 new listings / 24h.

## 4. Auction architecture

Managers list own squad players (3 / 24h). Durations 30/60/90/120. Seller cannot bid (UI + POST). Highest bidder wins; tokens settle once. Club auctions with no bids return to the seller. League-office unsigned auctions with no bids become free agents. Public users cannot bid.

Control splits **MANAGER AUCTIONS** from **LEAGUE OFFICE AUCTIONS**. Only Owner/Admin can release unsigned players.

## 5. Scouting architecture

One active scout. Country + position + tier. Random eligible FC26 player. Auto-recruit on success. Squad-full creates a Control exception — the player is not discarded.

| Level | Cost to reach | Duration |
|---|---|---|
| 1 (granted at hire) | listed 10 TKN | −2h all tiers |
| 2 | 18 TKN | −4h all tiers |
| 3 | 25 TKN | −8h all tiers |
| 4 | 25 TKN | Gold/Elite halved; Bronze/Silver keep L3 cut |

Timers are stored as `ready_at` server-side.

## 6. Press architecture

Create cap: 4 questions / rolling 24h. Reward: +0.5 TKN on **approval** with `press:{pk}`. Hard ledger cap: 2.00 TKN / 24h. Duplicate approve does not double pay. Questions come from live activity — no invented cups.

## 7. Starting squad architecture

25 players, OVR 64–69, UNASSIGNED only. Written 22 + official +1 CB +1 CM +1 ST. Generate/regenerate is preview only. Owner approval is confirmation-gated, atomic, stale-safe. Admin can view, not approve.

## 8. Manager experience

MY CAREER: Dashboard, squad, transfers, negotiations, auctions, scouting, matches, press, tokens, notifications, history.

Hub now leads with **What do I need to do?** — next fixture, active scout, press remaining, live auctions — then pending actions, squad, competition.

## 9. Control Centre

Same midnight/slate/cyan system as the public site. Approvals, auctions (split), scouting exceptions, tokens, starting squads, season, site, audit logs remain server-side gated.

## 10. UI/UX

- Background: midnight / charcoal blue
- Surfaces: dark slate
- Accent: controlled metallic gold + cool cyan
- Status: green / red / orange / cyan / gold
- Type: Barlow Condensed + Manrope
- Shared header, footer, nav, cards, empty states
- Official logo in header, footer, login, Control sidebar

Inner page class names still use the `mgl-*` prefix so existing templates inherit the system without a risky rename.

## 11. Mobile

CSS: no page `overflow-x`, tables scroll, 44px nav targets, logo-only header at 430px.

Browser inspect (desktop ~1280px plus Home and League table at 390px): no horizontal overflow, honest empty states, UFL branding throughout, cups labelled Coming soon. Remaining viewports (320 / 430 / 768 / 1024 / 1440 / 1920) are still on the owner checklist.

## 12. Security

Covered by the suite: cross-club, self-bid, Control access, ownership, token replay, press duplicate, scout one-active, squad 28, starting-squad Owner-only, crafted POST. Frontend never trusted.

## 13. Discord

Website commit → `DiscordEvent` outbox → bot → NEWS / PRESS / TRANSFER MARKET / AUCTIONS / FREE AGENTS. DMs only with a numeric Discord User ID. Bot failure does not roll back the site.

## 14. Old MGL remnants

Kept on purpose:

- `/mgl/` URL prefix
- `mgl_*` Python modules, templates, CSS class names, logo filename `mgl-logo.png`
- `auctions.TokenTransaction` table (unread legacy)
- `Team.roster_limit` column default 30 (enforcement uses 28)

No public MGL marketing copy. Hero jersey was already UFL.

## 15. Routes

Public IA rebuilt in `mgl/nav.py` + `core/templates/core/base.html`. No new Django URL names. Compatibility `/mgl/` aliases unchanged.

## 16. Templates updated

`base.html`, `home.html`, `manager_hub.html`, `control_auctions.html`, `control_starting_squads.html`, `scouting.html`, `pressroom.html`, `team_management.html`, `live_auctions.html`, `club_page.html`, `fixtures.html`, `job_centre.html`, `leagues.html`, `competition.html`, admin club pages, login/register inherit the shell.

## 17. CSS / static

- New `core/static/core/css/ufl-system.css`
- Retokenised `mgl-theme.css` and `mgl-control.css`
- No `collectstatic -c`

## 18. Database

No new migrations. No table drops. No token reset. No FC26 writes. No starting-squad apply.

## 19. Tests

```
TOTAL    450
PASSED   450
FAILED   0
SKIPPED  0
COVERAGE not collected
```

Local SQLite isolation (`DATABASE_URL` unset). Includes press daily cap, scout level table, Control auction headings, and nav IA.

## 20. Manual testing required

1. Sign in as an approved manager and walk MY CAREER: hub, squad, list, offer, counter, auction bid, scout dispatch, press answer.
2. Confirm a second manager cannot bid on their own auction or act on another club.
3. Owner: Control auction split, starting-squad **preview** (do not approve on production), press/score/transfer approve.
4. Confirm Discord outbox rows after a real listing / auction / FA / press approve.
5. Mobile Safari/Chrome at 320 / 390 / 430 / 768 — open League table, squad, auctions, Control.
6. Confirm existing production token balances are unchanged after deploy.
7. Confirm existing scout_level 1–4 managers see the new duration table (L1 is now 2 hours faster).

## 21. Known issues

- CSS/class/file prefixes remain `mgl-*` for compatibility.
- `Team.roster_limit` stored value may still be 30; UI and enforcement use 28.
- Holiday mode is not implemented.
- Public scouting URL redirects guests to login (nav is public; workflow is manager-only).
- Some inner page headers still say “MY CLUB” as a breadcrumb label.
- Visual pixel-pass recorded for ~1280px (major public pages) and 390px (Home + League table). Other listed widths still need a human pass.

## 22. Pre-launch status

**READY FOR MANUAL TESTING**

Career Mode rules that were FAIL (scout math, token dual-write, Control auction split, live cup CTA, dead squad-report, public IA) are implemented and covered by tests. Remaining PARTIAL items are compatibility leftovers, not broken official rules. Do not treat this as “launch finished” until the manual list above is signed off.
