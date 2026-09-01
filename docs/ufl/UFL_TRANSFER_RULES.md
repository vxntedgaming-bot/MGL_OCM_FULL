# UFL Transfer Rules

**Status:** Phase 1 locked market rules plus current `mgl/market.py` behaviour.

Do not implement gaps from this documentation pass.

---

## PHASE 1 LOCKED

- The transfer window **never closes**. No automatic close period.
- **Player listings** do **not** require Admin/Owner approval.
- **Release listings** do **not** require Admin/Owner approval.
- **Transfer requests** **do** require Admin/Owner approval before becoming official/live.
- Token amounts on the market use **0.5 increments only**.

Do not describe all market activity as requiring approval.

---

## Currency

**PHASE 1 LOCKED:** 0.5 increments only.

**CURRENT CODE**

- Personal tokens on `ManagerApplication.tokens`.
- Sale completion debits the buyer and credits the seller through the manager ledger (`credit_manager` / `debit_manager`) plus a `MarketTransaction` row.
- Free-agent sign: **0 TKN**, `MarketTransaction.SALE` note `"Free agent signing"`.
- Auction bids **reserve** tokens (`BID_RESERVE`); outbid / cancel **refunds** (`BID_REFUND`).
- Club `Team.tokens` is not the personal transfer purse.
- Asking-price parser is Decimal; **0.5-increment validation is not confirmed**.

---

## Transfer window

**PHASE 1 LOCKED:** never closes. There is no automatic closing period.

**CURRENT CODE**

```python
def transfer_window_is_open():
    return True
```

`assert_transfer_window()` is called on list/offer paths. The hook always returns True, which **matches** the Phase 1 lock. Do not add a close period unless the Owner later reverses DEC-024.

---

## Loans

**CONFIRMED:** loans do not exist in models or views.

---

## Buying

Two related flows exist.

### A. Listed player (seller already listed LIVE)

1. Buyer opens `/mgl/market/listings/<id>/purchase/` (`purchase_listing`).
2. Buyer posts tokens and optional swap players.
3. `create_listed_purchase_offer` sets listing status **OFFER**, stores `reserved_buyer`, `asking_price`, `offered_players`.
4. Seller is notified.
5. Instant `buy_listed_player` is **disabled** (raises). `buy_player` POST redirects to the BUY page.

### B. Unlisted club player (BUY from profile / club page)

1. `request_player_transfer` → `create_transfer_offer`.
2. Creates a listing in **OFFER** (waiting for selling manager).
3. Same seller + Owner/Admin path as below.

Buyer must be an approved manager with a club, enough tokens (unless swaps allow zero tokens), roster space after swaps, and cannot buy their own player.

---

## Selling (list for sale)

**PHASE 1 LOCKED:** no Admin/Owner gate to list. Creates LIVE immediately — this **matches** Phase 1.

**CURRENT CODE**

`list_player_for_sale`:

- Player must belong to the manager’s club.
- Asking price parsed and validated.
- Window hook (always open).
- No live auction on the player.
- Frequency: `listings_per_24h` default **3**.
- Capacity: `max_active_listings` default **5**.
- Creates `PlayerListing` with status **LIVE immediately**.
- Writes a transfer news post.

**There is no Owner/Admin gate to put a player on the market.** That is now a **Phase 1 locked rule**, not a gap. Older README text that said sales need approval before going live is stale.

---

## Seller response

`respond_to_transfer_offer`:

- Only the selling club’s manager.
- **Accept:** listing status → **PENDING**. Buyer is told the league office must still approve. Control is notified (`admin-listing-<id>`).
- **Reject:** listing cancelled / offer closed; buyer notified.

Accept does **not** move the player or tokens.

---

## Owner / Admin approval (sale / transfer request)

This is the **transfer request** path. **Phase 1 LOCKED:** Admin/Owner must approve before the move is official. CURRENT CODE matches: seller accept → PENDING → Control `approve_listing` completes the sale.

`approve_listing` requires status **PENDING**.

- If `reserved_buyer` is set: `_complete_listing_sale` runs atomically (player move, token debit/credit, listing **SOLD**, history, news).
- If no reserved buyer: listing is set **LIVE** (legacy path for listings that were queued before going live). Current `list_player_for_sale` does not use this for new sales.

`reject_listing`: status **REJECTED**, notifications closed.

`control_request_listing_changes`: Control can send the deal back with a note.

---

## Releases

**PHASE 1 LOCKED:** release listings do **not** require Admin/Owner approval.

**CURRENT CODE (GAP)**

- Manager POST `release_my_player` creates `PlayerReleaseRequest` **PENDING**. It does **not** immediately free the player.
- Owner/Admin `control_approve_release` / `control_reject_release`.
- Approve calls `release_player` → player leaves the club, `is_free_agent=True` (unless another path says otherwise).
- Unique constraint: one PENDING release per player.

Do **not** remove the Control release queue in this documentation pass.

**UNDECIDED:** whether a released player can be re-signed immediately by the same club (cool-down). Not found as a dedicated rule.

---

## Transfer requests UI

- `/mgl/transfer-requests/` — seller inbox.
- `/mgl/transfer-requests/<listing_id>/respond/` — accept/reject.
- Notifications carry Accept/Reject actions.

History:

- `/market/transfers/` — career transfer history (`transfer_history`).
- `/transfers/` — public completed transfers (`public_completed_transfers`).
- `MarketTransaction` + `TransferNegotiationEvent` + `PlayerOwnershipHistory`.

---

## Token handling (sale complete)

**CONFIRMED in principle:** completion is atomic in `_complete_listing_sale`. Buyer must still have the offered token amount; swaps move additional players both ways with roster checks.

Exact debit/credit category strings: inspect `_complete_listing_sale` at change time rather than duplicating them here.

---

## Auctions

**CONFIRMED**

- `PlayerAuction` + `AuctionBid` (`auctions` app).
- Manager club auctions allowed if `LeagueSettings.allow_manager_auctions` (default True).
- Durations 30/60/90/120 minutes (configurable).
- Max **3** club auctions / 24h.
- Only Owner/Admin can move **UNSIGNED** FC26 players → auction. Managers receive 403 on the unassigned-release POST.
- **DEC-042 LOCKED:** no-bid **admin/unsigned** auction **may** become a UFL Free Agent. No-bid **manager club** auction **returns the player to the original club** and must not create a Free Agent.
- **CURRENT CODE** already restores `listing_kind=CLUB` auctions to `origin_team` (`mgl/market.py` `_restore_unsold_player`). Keep that path; do not add a second auction system.
- Control can close or cancel auctions.
- `close_expired_auctions` management command / settlement.

---

## Free agents

**CONFIRMED**

- Sign for 0 TKN onto current club if not in a live auction, no club, genuine UFL Free Agent, roster space.
- **DEC-042:** the Free Agents page must not list every unsigned FC26 player. FA examples: pack reject/release, scout reject/release, no-bid admin auction, other explicit FA processes.
- Unsigned FC26 players are the recruitment/scouting/admin-auction pool, not public Free Agents.
- **CURRENT CODE** still uses `is_free_agent=True` for the FA page. Many unused FC26 rows are flagged true in the database. GAP — do not mass-edit those flags in a docs pass.

---

## Caps and locks

A player cannot be listed and in a live auction at the same time (`_assert_player_unlocked`).

Roster: `assert_roster_space` uses `effective_roster_limit`.

---

## Permissions

See `UFL_ROLES_PERMISSIONS.md`. Market POSTs are `@login_required` plus `approved_manager()` inside the view (not always `@career_required`). Services still enforce club ownership.

---

## NOT IMPLEMENTED / GAPS

- Loans
- Closed transfer window (and Phase 1 says it must stay open)
- Direct instant buy of a LIVE listing
- Manager listing requiring pre-approval before LIVE (and Phase 1 forbids that)
- Immediate manager release without Control (Phase 1 wants this; **code still requires Control**)
- 0.5-increment validation on asking prices
