# UFL Approval System

**Status:** Workflows implemented in Control Centre, notifications, and services.

Opponent or seller “accept” is **not** the same as official league approval.

---

## Who can approve

| Item | Approver |
|---|---|
| Manager application | Owner or Admin |
| Club job application | Owner or Admin |
| Match result | Owner or Admin (Owner may override missing opponent accept) |
| Transfer sale (PENDING listing) | Owner or Admin |
| Press answer | Owner or Admin |
| Player release | Owner or Admin |
| Weekly / monthly awards | Owner or Admin |
| Starting squads (UFL 25) | **Owner only** (`is_owner` + confirm) |
| Scout squad-full exception | Owner or Admin |
| Auction close/cancel | Owner or Admin |

Generic `ApprovalRequest` model exists. Current queues mostly use **domain status fields** (`MatchSubmission.status`, `PlayerListing.status`, etc.), not only `ApprovalRequest`.

---

## What Managers can submit

| Submission | Record | Immediate effect |
|---|---|---|
| Match result | `MatchSubmission` PENDING | Opponent notified; stats **not** official |
| List player for sale | `PlayerListing` **LIVE** | Visible on market (no Control gate) |
| Transfer offer / BUY | Listing OFFER | Seller notified |
| Seller accept | Listing PENDING | Control notified; player not moved |
| Release request | `PlayerReleaseRequest` PENDING | Player stays at club |
| Press answer | `PressConference` PENDING | Not published/rewarded until approved |
| Club application | `ClubApplication` PENDING | Not appointed |
| Club auction (if allowed) | `PlayerAuction` | Live/pending per auction rules |
| Recruitment pack / scout | Domain rows | Scout recruit may assign immediately when due |

---

## Match results

1. Home or away manager submits on a released fixture involving their club.
2. Opposing manager gets an inbox card (Accept/Reject).
3. Opponent response is stored on `MatchSubmission.opponent_response`. **This does not officialise the match.**
4. Control Scores: Owner/Admin approve.
   - If opponent has not accepted: Admin is blocked; Owner can POST `override=1`.
   - Season lock blocks changes.
5. On approve (`approve_match_submission`):
   - `apply_match_statistics` (player appearances/goals/assists/ratings, career W/D/L)
   - Match token pay 1.00 TKN per side
   - Submission APPROVED, fixture COMPLETED
   - `NewsPost` RESULTS
   - Match press questions created
   - Admin result notices closed
6. Reject: stays non-official; managers notified.
7. Rollback: `unapprove_match_submission` reverses official stats when used from Control.

**Official tables and public stats** only use approved submissions.

---

## Transfers

1. Listing LIVE (seller listed) or OFFER (buyer requested).
2. Seller accept → PENDING.
3. Control Transfers approve → `_complete_listing_sale`: player ownership changes, tokens move, listing SOLD, news, history.
4. Reject → REJECTED; no sale.
5. Request changes → seller/buyer notified; deal not complete.

Until step 3, the player remains at the selling club.

---

## Releases

1. Manager requests release.
2. Control approve → `release_player` → Free Agent (typical path).
3. Reject → request REJECTED; player stays.

---

## Jobs and manager applications

1. Registration application PENDING until Control approve/reject.
2. Job apply PENDING until Control approve → `Team.manager` set (and related appointment side effects in `control_approve_job`).
3. Reject job: application REJECTED; club stays vacant.

---

## Press

1. System creates `PressConference` questions (match, signing, etc.).
2. Manager answers (`answer_press`).
3. Control approve: status APPROVED, reward via `credit_manager` (default 0.50, 4/24h cap in settings), published press.
4. Reject: REJECTED, no reward.

Exact reward category string: inspect `control_approve_press` at change time.

---

## Starting squads

See `UFL_CAREER_MODE.md`. Draft generation writes **no** ownership. Owner confirm assigns players (`source=UFL_STARTING`) and creates `StartingSquadLock`. Reject does not assign. Admin cannot approve.

---

## Awards

Weekly/monthly batches: calculate → Control approve → token/news side effects. Reject/recalculate exist for weekly.

---

## Database status fields

Common pattern: `PENDING` / `APPROVED` / `REJECTED` (`ApprovalStatus`).

Listings add `LIVE`, `OFFER`, `SOLD`, `CANCELLED`.

Starting squads add `DRAFT`, `SUPERSEDED`.

Notifications: `response_status` NONE / PENDING / ACCEPTED / REJECTED for action cards.

---

## Activity, statistics, tables

| Event | Live Activity / news | Tables / player stats |
|---|---|---|
| Pending result | Not official RESULTS | No |
| Approved result | RESULTS post | Yes |
| LIVE listing | TRANSFER listed news | No table change |
| Completed sale | TRANSFER/SIGNING style posts | Squad change only |
| Approved press | PRESS when published | No |
| Scout recruit | SCOUTING | Squad change |

Discord outbox (`DiscordEvent`) follows official/published events; it is not a second source of truth.

---

## UNKNOWN / NEEDS CONFIRMATION

- Whether every Control queue item also writes `ApprovalRequest`
- Award token amounts per winner
- Whether Admin can reject starting-squad drafts from the UI (reject function exists; Owner-only is for **approve**)
