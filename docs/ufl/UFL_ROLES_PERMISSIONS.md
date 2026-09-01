# UFL Roles and Permissions

**Status:** Current behaviour as implemented, plus Phase 1 locked product rules where they differ.

**Sources:** `accounts.User`, `mgl/permissions.py`, `mgl/ufl_settings.py`, view decorators, in-view checks, Owner Phase 1 (2026-09-01).

If a cell cannot be proven from code it is marked **UNKNOWN**. Phase 1 locks that the code does not yet match are marked **GAP**.

---

## Role model (two layers)

### Stored role (`accounts.User.role`)

| Value | Who |
|---|---|
| `OWNER` | League owner |
| `ADMIN` | League office |
| `MANAGER` | Default on registration |

There is **no `MEMBER` value** in the database.

### Capability role (`ufl_access_role()`)

| Capability | How it is derived |
|---|---|
| PUBLIC | Not authenticated |
| MEMBER | Authenticated, and not (approved application **and** `managed_team`) |
| MANAGER | `approved_manager(user)` and `user.managed_team` |
| ADMIN | `User.role == ADMIN` |
| OWNER | `User.role == OWNER` |

A signed-in user with `role=MANAGER` and a **PENDING** application is therefore a **Member** for capability purposes, even though `User.role` says MANAGER.

---

## Server-side gates

| Gate | Effect |
|---|---|
| `@login_required` | Unauthenticated users go to `/login/` |
| `@career_required` | If not Owner/Admin and not approved manager → redirect `job_centre` |
| `@owner_admin_required` | Unauthenticated → login; other roles → `manager_hub` + error message |
| `@site_manage_required` | Unauthenticated → login; other roles → HTTP **403** |
| In-view `approved_manager()` | Many market POSTs: message + redirect if not approved |
| In-view club ownership | Sell/release/list/submit only for the manager’s own club |
| `is_owner()` | Starting-squad approve; match override |

`career_required` does **not** require an assigned club. An approved manager without a team can open career GET pages; club actions then fail with ValueError / flash messages.

---

## Permission matrix

Legend: **Y** = yes, **N** = no, **Own** = only own club / own records, **OA** = Owner or Admin, **O** = Owner only, **SS** = enforced in the view or service (not only hidden in the UI).

### Accounts and identity

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| View Public Home | Y | Y (if not approved → home; approved → hub redirect) | Redirect `/` to hub | Redirect if approved manager else home | Same as Admin unless also approved manager | `home()` |
| Register | Y | N (already has account) | N | N | N | Public form |
| Login / logout | Y | Y | Y | Y | Y | Django auth |
| View own profile `/mgl/profile/` | N → jobs | N → jobs | Y | Y | Y | `career_required` |
| Resign from club | N | N | Own | Y (control also removes managers) | Y | `career_required` + service |
| Change another user’s role | N | N | N | UNKNOWN (Django admin staff only if permitted) | UNKNOWN | Django admin; **no UFL Control role editor found** |
| Delete a user | N | N | N | UNKNOWN | UNKNOWN | No UFL view found |

### Public league pages

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| View leagues / tables / clubs / club pages | Y | Y | Y | Y | Y | Public views |
| View released fixture detail | Y | Y | Y | Y | Y | `is_released=True` |
| View stats (approved results only) | Y | Y | Y | Y | Y | Public |
| View jobs / apply form | Y | Y | Y | Y | Y | Public GET |
| Apply for a vacant club | N | **Y** — Job Application | N if already appointed | Y | Y | `@login_required` + server-side pending/club checks |
| View rules | Y | Y | Y | Y | Y | Public |
| View live activity / pressroom | Y | Y | Y | Y | Y | Public |
| View public completed transfers | Y | Y | Y | Y | Y | Public |
| Player compare | 404 | 404 | 404 | 404 | 404 | `Http404` |

### Career Mode

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| Hub, team, fixtures list | N → jobs | N → jobs (unless approved) | Y | Y | Y | `career_required` |
| Submit match for own club | N | N | Own club, released fixture | Can open career pages; submit still club-scoped | Same | `career_required` + club check |
| Opponent Accept/Reject result | N | N | Own inbox | — | — | Notification respond |
| Approve official result | N | N | N | Y | Y (+ override) | `owner_admin_required` |
| View Youth Academy page | N → jobs | N → jobs | Coming soon page | Y | Y | `career_required` |
| Scout / recruit / recruitment packs | N | N | Y (need club for dispatch) | Y | Y | `career_required` |
| Sign free agent (0 TKN) | N | N | Y if roster space | Y | Y | `career_required` + service |

### Transfers and market

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| View transfer market | N → jobs | N → jobs | Y | Y | Y | `career_required` |
| List own player for sale (goes **LIVE** immediately) | N | N | Own | — | — | `@login_required` + `approved_manager` + club ownership |
| Cancel own listing | N | N | Own | — | — | Same |
| Send buy / transfer request | N | N | Other clubs | — | — | Same |
| Seller accept/reject offer | N | N | Own | — | — | Club manager check |
| Approve completed sale | N | N | N | Y | Y | `owner_admin_required` |
| Reject listing / request changes | N | N | N | Y | Y | `owner_admin_required` |
| Instant buy without request | N | N | N | N | N | `buy_listed_player` raises; `buy_player` redirects to BUY page |
| Request player release | N | N | Own — immediate FA | — | — | `career_required` + club ownership. No Control gate |
| Approve / reject leftover release | N | N | N | Y (leftover PENDING only) | Y (leftover PENDING only) | Official manager release no longer queues |
| Create club auction | N | N | Own, if `allow_manager_auctions` | Y | Y | Caps in `mgl/market.py` |
| Bid on auction | N | N | Y (tokens reserved) | Y | Y | `career_required` |
| Close / cancel auction | N | N | N | Y | Y | `owner_admin_required` |
| Auction unassigned pool player | N | N | N (403 on unassigned-release) | Y | Y | Control / admin |

### Tokens

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| View own token history | N | N | Y | Y | Y | `career_required` |
| Spend / receive via market, scout, press, match | N | N | Automatic | Automatic | Automatic | `credit_manager` / `debit_manager` |
| Manual adjust | N | N | N | Y | Y | `control_adjust_tokens` |

### Press, news, notifications

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| Read published activity / press | Y | Y | Y | Y | Y | Public |
| Answer own press question | N | Login required | Own | — | — | `@login_required` + ownership in view |
| Approve / reject press | N | N | N | Y | Y | `owner_admin_required` |
| Read own notifications | N | N | Own recipient | Own | Own | Views are career-scoped; **confirm panel auth** — views exist under `/mgl/notifications/` |
| Mark read / respond | N | N | Own | Own | Own | Recipient-scoped |

Notification view decorators: `manager_notifications` and related views in `mgl/views.py` are under career routes; treat panel POSTs as **server-side recipient-scoped**. If a future change loosens that, re-audit.

### Jobs and managers

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| Apply for vacant club | See above | **Y** via Job Application | N if already appointed | Y | Y | POST protected; one PENDING per manager |
| Approve / reject job | N | N | N | Y | Y | `owner_admin_required` — **this is the official DEC-041 accept** |
| Approve / reject manager application | N | N | N | Y (code) | Y (code) | **CURRENT CODE** extra queue. **LOCKED:** not part of the official job path |
| Change / remove club manager | N | N | N | Y | Y | `owner_admin_required` on `/mgl/admin/clubs/…` and Control |

### Starting squads

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| Preview / generate draft | N | N | N | Y (Control page) | Y | `owner_admin_required` |
| Approve and lock season allocation | N | N | N | **N** | **Y** | `approve_proposal` → `is_owner` + confirm |
| Reject draft | N | N | N | Control page exists | Y | Confirm in `ufl_starting.reject_proposal` — Admin can open the page; **approve is Owner-only** |
| Run `apply_starting_squads` (legacy 14×26) | Management command | — | — | Staff with shell | Staff with shell | Not a public route |

### Site Management and Django admin

| Action | Public | Member | Manager | Admin | Owner | Server-side |
|---|---|---|---|---|---|---|
| Inspect / retry Discord outbox | N | N | N | Y | Y | `owner_admin_required` on `/mgl/control/discord/` |
| Site Management CMS | N | N | 403 | Y | Y | `site_manage_required` |
| Edit display names / logos / copy | N | N | N | Y | Y | Display-only paths documented in README |
| Django `/admin/` | N | N | N unless `is_staff` | Only if staff | Only if staff | Django staff. **Phase 1 LOCKED: retain `/admin/`.** |

Site Management (owner/admin only) can change club **display** name, logo, and copy. **Phase 1 LOCKED:** Admin must be able to change club name, logo, and branding/identity where supported at any time. CURRENT CODE: display edits; `badge_code` is a frozen crest key and is not rewritten when the short name changes.

---

## Manager ownership restrictions (DEC-004)

Confirmed in services:

- Sell / auction / release: player must belong to the manager’s club
- Submit match: fixture must include that club
- Respond to transfer offer: `listing.team.manager_id == seller_user.id`
- Cannot buy own listed player
- Scout dispatch requires a current club
- Free-agent sign assigns to current club only

---

## What Members cannot do

Members (signed in, not appointed) cannot use Career Mode routes. `career_required` sends them to Job Centre. They can browse public pages and log out. They submit the official Job Application from Job Offers. Registration may create a PENDING `ManagerApplication` identity/token row; that is **not** a second approval gate.

**LOCKED (DEC-041):** A Member submits the Job Application; Admin reviews that one form and accepts; the member becomes the manager. No second manager-application approval.

**IMPLEMENTED (Phase 4):** `apply_for_club` accepts a PENDING identity. Admin Job Application accept is the official promotion.
