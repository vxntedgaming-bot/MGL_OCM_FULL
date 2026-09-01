# UFL Approval System

**Status:** Phase 1 locked approval distinctions plus current Control Centre workflows.

Opponent or seller “accept” is **not** the same as official league approval.

---

## PHASE 1 LOCKED — what needs approval

| Item | Admin/Owner approval before official/live? |
|---|---|
| Player listings | **No** |
| Release listings | **No** |
| Transfer requests | **Yes** |
| Job applications | **Yes** — this is the **only** application Admin reviews (DEC-041). Accept → job/manager appointment |
| Match results | **Yes** (unchanged; not reversed in Phase 1) |
| Press answers | **Yes** (unchanged) |
| Starting squad apply | Owner-gated in code; structure now locked at 30 |
| Pack availability | Admin/Owner **control** (not a manager submit/approve queue) |

Do not describe all market activity as requiring approval.

Discord Outbox retry is **not** a football approval. Owner/Admin may re-queue a notification only. It cannot approve transfers, jobs, matches, awards, or Season 1.

---

## Who can approve

| Item | Approver |
|---|---|
| Manager application | Owner or Admin |
| Club job application | Owner or Admin |
| Match result | Owner or Admin (Owner may override missing opponent accept) |
| Transfer sale (PENDING listing) | Owner or Admin |
| Press answer | Owner or Admin |
| Player release | **Phase 1: no.** CURRENT CODE: Owner or Admin still approve `PlayerReleaseRequest` — GAP |
| Weekly / monthly awards | Owner or Admin |
| Starting squads | **Owner only** (`is_owner` + confirm). Code generator is still 25; locked structure is 30 |
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
| Release request | `PlayerReleaseRequest` PENDING | **CURRENT CODE:** player stays until Control. **Phase 1:** should not need this gate |
| Press answer | `PressConference` PENDING | Not published/rewarded until approved |
| Club application | `ClubApplication` PENDING | Not appointed |
| Club auction (if allowed) | `PlayerAuction` | Live/pending per auction rules |
| Recruitment pack / scout | Domain rows | Pack/scout **choice** writes club ownership immediately. Unselected stay UNSIGNED. No extra approval queue. Owner/Admin configure packs and scout levels. |

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

**PHASE 1 LOCKED:** no Admin/Owner approval for release listings.

**IMPLEMENTED (Phase 4)**

1. Manager releases their own club-owned player.
2. `request_player_release` immediately calls `release_player` → genuine UFL Free Agent (`released_at`).
3. No Control approval on the official path. Leftover PENDING rows can still be rejected (player stays) or approved.

**DEC-042:** a club release that is an explicit UFL FA process creates a Free Agent; unsigned FC26 players must not be bulk-converted to FA.

Admin unsigned auctions: no bid may create a Free Agent. Manager club auctions: no bid returns the player home (**CURRENT CODE** already does this).

---

**LOCKED UFL RULE (DEC-041):** MEMBER → Job Application → Admin reviews → Admin accepts → member gets the job and becomes the manager. **No** extra manager-application approval.

**IMPLEMENTED (Phase 4)**

1. Registration still creates `ManagerApplication` PENDING as the identity/token row. That is not the official job review.
2. Members submit Job Application (`ClubApplication`) without a prior identity approval.
3. Control `control_approve_job` atomically approves the identity if needed and sets `Team.manager`.
4. Reject job: Job Application REJECTED; identity stays as it was; club stays vacant; the Member may apply again.

---

## Press

1. System creates `PressConference` questions (match, signing, etc.).
2. Manager answers (`answer_press`).
3. Control approve: status APPROVED, reward via `credit_manager` (Phase 1 locked press reward **+0.5 TKN**; code default 0.50, 4/24h cap in settings), published press.
4. Reject: REJECTED, no reward.

Exact reward category string: inspect `control_approve_press` at change time.

---

## Starting squads

See `UFL_CAREER_MODE.md`. Draft generation writes **no** ownership. Owner confirm assigns players (`source=UFL_STARTING`) and creates `StartingSquadLock`. Reject does not assign. Admin cannot approve.

Phase 1 locked **30-player** shape. Current generator is **25**. Do not apply a new allocation from this documentation task.

---

## Awards

Weekly/monthly batches: calculate → Control approve → token/news side effects. Reject/recalculate exist for weekly.

**Phase 1 locked weekly amounts** (Sunday 10:00 AM → Sunday 10:00 AM): approved league game +1; TOTW +0.5 per selected player; press +0.5; MOTW +1; weekly #1 goals +0.5; weekly #1 assists +0.5; cup winner +10; cup runner-up +5.

Whether the current award calculator pays those figures is **not confirmed**. Time zone **NEEDS OWNER DECISION**.

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
- Whether the award calculator matches the Phase 1 weekly/cup table
- Whether Admin can reject starting-squad drafts from the UI (reject function exists; Owner-only is for **approve**)
- Time zone for Sunday 10:00 AM
