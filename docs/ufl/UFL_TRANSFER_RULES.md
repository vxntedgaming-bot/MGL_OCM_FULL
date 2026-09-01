# UFL Transfer Rules

**Status:** Transfer, listing, auction, and release behaviour as implemented in `mgl/market.py`, `mgl/market_views.py`, `mgl/services.py`, `auctions/`.

Do not invent window, loan, or fee rules.

---

## Currency

**CONFIRMED**

- Personal tokens on `ManagerApplication.tokens`.
- Sale completion debits the buyer and credits the seller through the manager ledger (`credit_manager` / `debit_manager`) plus a `MarketTransaction` row.
- Free-agent sign: **0 TKN**, `MarketTransaction.SALE` note `"Free agent signing"`.
- Auction bids **reserve** tokens (`BID_RESERVE`); outbid / cancel **refunds** (`BID_REFUND`).
- Club `Team.tokens` is not the personal transfer purse.

---

## Transfer window

**CONFIRMED**

```python
def transfer_window_is_open():
    return True
```

`assert_transfer_window()` is called on list/offer paths. Because the hook always returns True, **there is no implemented closed window**.

**UNDECIDED / NOT IMPLEMENTED:** dates, Owner toggle, or blocking behaviour when closed.

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

**CONFIRMED**

`list_player_for_sale`:

- Player must belong to the manager’s club.
- Asking price parsed and validated.
- Window hook (always open).
- No live auction on the player.
- Frequency: `listings_per_24h` default **3**.
- Capacity: `max_active_listings` default **5**.
- Creates `PlayerListing` with status **LIVE immediately**.
- Writes a transfer news post.

**There is no Owner/Admin gate to put a player on the market.** Older README text that said sales need approval before going live is **stale**.

---

## Seller response

`respond_to_transfer_offer`:

- Only the selling club’s manager.
- **Accept:** listing status → **PENDING**. Buyer is told the league office must still approve. Control is notified (`admin-listing-<id>`).
- **Reject:** listing cancelled / offer closed; buyer notified.

Accept does **not** move the player or tokens.

---

## Owner / Admin approval (sale)

`approve_listing` requires status **PENDING**.

- If `reserved_buyer` is set: `_complete_listing_sale` runs atomically (player move, token debit/credit, listing **SOLD**, history, news).
- If no reserved buyer: listing is set **LIVE** (legacy path for listings that were queued before going live). Current `list_player_for_sale` does not use this for new sales.

`reject_listing`: status **REJECTED**, notifications closed.

`control_request_listing_changes`: Control can send the deal back with a note.

---

## Releases

**CONFIRMED**

- Manager POST `release_my_player` creates `PlayerReleaseRequest` **PENDING**. It does **not** immediately free the player.
- Owner/Admin `control_approve_release` / `control_reject_release`.
- Approve calls `release_player` → player leaves the club, `is_free_agent=True` (unless another path says otherwise).
- Unique constraint: one PENDING release per player.

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
- Only Owner/Admin can move **UNASSIGNED** → auction. Managers receive 403 on the unassigned-release POST.
- No-bid league auction can become a Free Agent.
- Control can close or cancel auctions.
- `close_expired_auctions` management command / settlement.

---

## Free agents

**CONFIRMED**

- Sign for 0 TKN onto current club if not in a live auction, no club, `is_free_agent=True`, roster space.
- Unassigned pool players are **not** signable as free agents.

---

## Caps and locks

A player cannot be listed and in a live auction at the same time (`_assert_player_unlocked`).

Roster: `assert_roster_space` uses `effective_roster_limit`.

---

## Permissions

See `UFL_ROLES_PERMISSIONS.md`. Market POSTs are `@login_required` plus `approved_manager()` inside the view (not always `@career_required`). Services still enforce club ownership.

---

## NOT IMPLEMENTED

- Loans
- Closed transfer window
- Direct instant buy of a LIVE listing
- Manager listing requiring pre-approval before LIVE
