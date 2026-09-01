# UFL Route Inventory

**Status:** Routes that exist in `config/urls.py`, `core/urls.py`, `mgl/urls.py`, `managers/urls.py`, `auctions/urls.py`.  
Do not add product routes that are not listed here.

Protection column is the **server-side** gate. UI hiding is not protection.

Status values: **Live** (implemented page), **Coming soon** (placeholder), **Redirect**, **404**, **Django admin**.

---

## Auth (`managers/urls.py`)

| URL | Name | Purpose | Access | Role | Protection | Status | System |
|---|---|---|---|---|---|---|---|
| `/register/` | `manager_register` | Create User + pending `ManagerApplication` (tokens/identity). **LOCKED (DEC-041):** this is **not** the Admin job-review step | Public | — | None (form) | Live | Auth |
| `/login/` | `manager_login` | Session login | Public | — | Django LoginView | Live | Auth |
| `/logout/` | `manager_logout` | Session logout | Public POST | — | Django LogoutView | Live | Auth |

---

## Root / public site (`core/urls.py`)

| URL | Name | Purpose | Access | Role | Protection | Status | System |
|---|---|---|---|---|---|---|---|
| `/` | `home` | Public Home; approved managers → hub | Public | — | Redirect if `approved_manager` | Live | Public Home |
| `/leagues/` | `leagues_page` | All league tables | Public | — | None | Live | Leagues |
| `/leagues/<slug>/` | `competition_page` | Division or cup page | Public | — | None | Live / Coming soon for cup slugs | Leagues/Cups |
| `/clubs/` | `clubs_index` | Club directory | Public | — | None | Live | Clubs |
| `/clubs/<slug>/` | `club_page` | Club profile + squad | Public | — | None | Live | Clubs |
| `/news/` | `news_centre` | Redirect to activity (or pressroom `?tab=`) | Public | — | Redirect | Redirect | News |
| `/news/activity/` | `live_activity` | UFL Live Activity / Newsroom | Public | — | None | Live | News |
| `/news/pressroom/` | `pressroom` | Press Conference list | Public | — | None | Live | Press |
| `/news/pressroom/<id>/answer/` | `answer_press` | Answer a press question | Private | Author | `@login_required` + ownership in view | Live | Press |
| `/stats/` | `stats_page` | Stats landing | Public | — | None | Live | Stats |
| `/stats/history/` | `historical_tables` | Historical tables | Public | — | None | Live | History |
| `/history/` | `hall_of_fame` | Hall of Fame | Public | — | None | Live | History |
| `/managers/<username>/` | `manager_public_profile` | Public manager page; own username → profile | Public GET | — | Own-user redirect | Live | Career |
| `/stats/compare/` | `compare_players` | Removed | — | — | `Http404` | 404 | Stats |
| `/stats/managers/` | `manager_search` | Manager search | Public | — | None | Live | History |
| `/stats/<slug>/` | `league_stats` | Division stats | Public | — | None | Live | Stats |
| `/jobs/` | `job_centre` | Job Centre | Public | — | None | Live | Jobs |
| `/job-offers/` | `job_offers` | Same view as jobs | Public | — | None | Live | Jobs |
| `/job-centre/` | — | Redirect to jobs | Public | — | Redirect | Redirect | Jobs |
| `/rules/` | `ufl_rules` | Rules page | Public | — | None | Live | Public |
| `/market/` | `transfer_market` | Transfer market | Career | Approved / OA | `career_required` | Live | Transfers |
| `/market/transfers/` | `transfer_history` | Transfer history | Career | Approved / OA | `career_required` | Live | Transfers |
| `/transfers/` | `public_transfers` | Public completed transfers | Public | — | None | Live | Transfers |
| `/market/scouting/` | `scouting` | Scouting HQ | Career | Approved / OA | `career_required` | Live | Scouting |
| `/market/youth-academy/` | `youth_academy` | Youth Academy | Career | Approved / OA | `career_required` | Coming soon | Market |
| `/market/recruitment/` | `recruitment_drive` | Recruitment Drive | Career | Approved / OA | `career_required` | Live | Recruitment |
| `/market/recruitment/open/` | `open_recruitment_pack` | Open pack | Career POST | Approved / OA | `career_required` | Live | Recruitment |
| `/market/recruitment/<id>/choose/` | `choose_recruitment_player` | Pick pack player | Career POST | Approved / OA | `career_required` | Live | Recruitment |
| `/matches/` | — | Redirect to fixture list | — | — | Redirect | Redirect | Fixtures |
| `/auctions/history/` | — | Redirect `/auctions/?tab=history` | — | — | Redirect | Redirect | Auctions |
| `/mgl/` | include | Career + Control | Mixed | Mixed | Per-route | Live | Career |

Competition slugs in `COMPETITIONS`: `premier-league`, `championship`, `league-one`, `cups`, `phantom-cup`, `champions-league`, `europa-league`, `conference-league`. Live table data only for PL / CH / L1 when those leagues exist.

---

## Auctions (`auctions/urls.py`)

| URL | Name | Purpose | Access | Role | Protection | Status | System |
|---|---|---|---|---|---|---|---|
| `/auctions/` | `live_auctions` | Live auctions | Career | Approved / OA | `career_required` | Live | Auctions |
| `/auctions/<id>/bid/` | `place_bid` | Place bid | Career POST | Approved / OA | `career_required` | Live | Auctions |

---

## Career (`mgl/urls.py`)

| URL | Name | Purpose | Access | Role | Protection | Status | System |
|---|---|---|---|---|---|---|---|
| `/mgl/` | `mgl_index` | Career index | Career | Approved / OA | Inspect view — treated as career entry | Live | Career |
| `/mgl/hub/` | `manager_hub` | Manager Dashboard | Career | Approved / OA | `career_required` | Live | Career |
| `/mgl/notifications/` | `manager_notifications` | Inbox | Career | Recipient | Career views | Live | Notifications |
| `/mgl/notifications/panel/` | `notification_panel` | Header panel fragment | Career | Recipient | Career views | Live | Notifications |
| `/mgl/notifications/read-all/` | `notification_mark_all_read` | Mark all read | Career POST | Recipient | Career views | Live | Notifications |
| `/mgl/notifications/<id>/read/` | `notification_mark_read` | Mark one read | Career POST | Recipient | Career views | Live | Notifications |
| `/mgl/notifications/<id>/respond/` | `manager_notification_respond` | Accept/Reject action | Career POST | Recipient | Career views | Live | Notifications |
| `/mgl/transfer-requests/` | `transfer_requests` | Seller transfer inbox | Career | Manager | Career | Live | Transfers |
| `/mgl/transfer-requests/<id>/respond/` | `respond_transfer_request` | Accept/Reject offer | Career POST | Selling manager | Service ownership | Live | Transfers |
| `/mgl/live-activity/` | `live_activity_alias` | Redirect to news activity | — | — | Redirect | Redirect | News |
| `/mgl/pressroom/` | `pressroom_alias` | Redirect to pressroom | — | — | Redirect | Redirect | Press |
| `/mgl/team/` | `team_management` | Squad | Career | Approved / OA | `career_required` | Live | Career |
| `/mgl/team/release/<player_id>/` | `release_my_player` | Request release | Career POST | Own club | `career_required` | Live | Releases |
| `/mgl/team/auction/<player_id>/` | `list_player_for_auction` | List club auction | Career POST | Own club | `career_required` | Live | Auctions |
| `/mgl/team/sell/<player_id>/` | `sell_player` | List for sale | Login POST | Approved manager | `@login_required` + `approved_manager` | Live | Transfers |
| `/mgl/players/` | `player_database` | Player DB | Career | Approved / OA | `career_required` | Live | Players |
| `/mgl/players/<id>/face/` | `player_face_image` | Face proxy | Public GET | — | None (image fetch) | Live | Players |
| `/mgl/players/<id>/` | `player_profile` | Player profile | Career | Approved / OA | `career_required` | Live | Players |
| `/mgl/players/<id>/request-transfer/` | `request_player_transfer` | BUY request | Login POST | Approved manager | `@login_required` + `approved_manager` | Live | Transfers |
| `/mgl/unassigned/` | `unassigned_players` | Unassigned pool | Career | Approved / OA | `career_required` | Live | Players |
| `/mgl/free-agents/` | `free_agents` | Free agents | Career | Approved / OA | `career_required` | Live | Players |
| `/mgl/free-agents/<id>/sign/` | `sign_free_agent` | Sign FA 0 TKN | Career POST | Manager with club | `career_required` | Live | Players |
| `/mgl/free-agents/<id>/auction/` | `auction_free_agent` | Auction a FA | Career POST | Inspect — typically OA path | `career_required` | Live | Auctions |
| `/mgl/profile/` | `manager_profile` | Career profile | Career | Approved / OA | `career_required` | Live | Career |
| `/mgl/profile/resign/` | `resign_from_club` | Resign | Career | Appointed manager | `career_required` | Live | Career |
| `/mgl/rewards/` | `manager_rewards` | Token history | Career | Approved / OA | `career_required` | Live | Tokens |
| `/mgl/fixtures/` | `fixture_list` | Fixture list | Career | Approved / OA | `career_required` | Live | Fixtures |
| `/mgl/fixtures/<id>/` | `fixture_detail` | Match detail | Public if released | — | `is_released=True` | Live | Fixtures |
| `/mgl/fixtures/<id>/submit/` | `submit_match` | Submit result | Career | Own club | `career_required` | Live | Results |
| `/mgl/fixtures/<id>/stats/` | `fixture_stats` | Same submit view | Career | Own club | `career_required` | Live | Results |
| `/mgl/fixtures/<id>/press/` | `press_conference` | Match press | Career | Involved manager | `career_required` | Live | Press |
| `/mgl/market/listings/<id>/buy/` | `buy_player` | Redirect to BUY page | Login POST | Approved | `@login_required` | Live | Transfers |
| `/mgl/market/listings/<id>/purchase/` | `purchase_listing` | BUY listed player | Login | Approved + club | `@login_required` + `approved_manager` | Live | Transfers |
| `/mgl/market/listings/<id>/cancel/` | `cancel_player_listing` | Withdraw listing | Login POST | Seller | `@login_required` + `approved_manager` | Live | Transfers |
| `/mgl/jobs/<team_id>/apply/` | `apply_for_club` | Submit Job Application for a vacant club | Login POST | **LOCKED:** Member. **CODE:** approved manager only | `@login_required` + **CURRENT CODE** `approved_manager` | Live — **GAP TO IMPLEMENT** vs DEC-041 | Jobs |

---

## Legacy club admin URLs (`mgl/urls.py`)

Gated `owner_admin_required` (confirm on each view). README: team edit redirects to Site Management.

| URL | Name | Purpose | Access | Protection | Status | System |
|---|---|---|---|---|---|---|
| `/mgl/admin/clubs/` | `club_management_admin` | Club admin list | OA | `owner_admin_required` | Live | Owner |
| `/mgl/admin/clubs/<id>/edit/` | `edit_club_admin` | Edit club | OA | `owner_admin_required` | Redirect/live | Site Mgmt |
| `/mgl/admin/clubs/<id>/manager/` | `change_club_manager` | Change manager | OA | `owner_admin_required` | Live | Owner |
| `/mgl/admin/clubs/<id>/remove-manager/` | `remove_club_manager` | Remove manager | OA | `owner_admin_required` | Live | Owner |
| `/mgl/admin/clubs/<id>/squad/` | `club_squad_admin` | Admin squad | OA | `owner_admin_required` | Live | Owner |

---

## Control Centre (`/mgl/control/…`)

All **GET pages** below are `owner_admin_required` unless noted. POST approve/reject actions are `owner_admin_required` + `require_POST`.

| URL | Name | Purpose | Status | System |
|---|---|---|---|---|
| `/mgl/control/` | `control_centre` | Command dashboard | Live | Admin |
| `/mgl/control/pending/` | `control_pending` | Approval queue | Live | Approvals |
| `/mgl/control/approvals/` | `control_approvals` | Alias pending | Redirect/alias | Approvals |
| `/mgl/control/scores/` | `control_scores` | Match approvals | Live | Results |
| `/mgl/control/approvals/scores/` | alias | Scores | Alias | Results |
| `/mgl/control/transfers/` | `control_transfers` | Transfer approvals | Live | Transfers |
| `/mgl/control/approvals/transfers/` | alias | Transfers | Alias | Transfers |
| `/mgl/control/press/` | `control_press` | Press approvals | Live | Press |
| `/mgl/control/approvals/press/` | alias | Press | Alias | Press |
| `/mgl/control/managers/` | `control_managers` | Manager applications | Live | Managers |
| `/mgl/control/approvals/managers/` | alias | Managers | Alias | Managers |
| `/mgl/control/awards/weekly/` | `control_weekly_awards` | Weekly awards | Live | Awards |
| `/mgl/control/history/weekly-rewards/` | alias | Weekly | Alias | Awards |
| `/mgl/control/awards/monthly/` | `control_monthly_awards` | Monthly awards | Live | Awards |
| `/mgl/control/history/monthly-rewards/` | alias | Monthly | Alias | Awards |
| `/mgl/control/tokens/` | `control_tokens` | Token desk | Live | Tokens |
| `/mgl/control/scouting/` | `control_scouting` | Scout exceptions | Live | Scouting |
| `/mgl/control/management/scouting/` | alias | Scouting | Alias | Scouting |
| `/mgl/control/auctions/` | `control_auctions` | Auction desk | Live | Auctions |
| `/mgl/control/management/auctions/` | alias | Auctions | Alias | Auctions |
| `/mgl/control/clubs/` | `control_clubs` | Clubs desk | Live | Clubs |
| `/mgl/control/management/clubs/` | alias | Clubs | Alias | Clubs |
| `/mgl/control/notifications/` | `control_notifications` | Notification desk | Live | Notifications |
| `/mgl/control/logs/` | `control_logs` | Audit logs | Live | Admin |
| `/mgl/control/season/history/` | `control_season_history` | Season history | Live | Season |
| `/mgl/control/season/controls/` | `control_season_controls` | Season controls | Live | Season |
| `/mgl/control/season/starting-squads/` | `control_starting_squads` | UFL 25 preview/approve | Live | Starting squads |
| `/mgl/control/league/` | `control_league` | League controls | Live | League |

### Site Management (`site_manage_required` → 403 for managers)

| URL | Name | Purpose | Status |
|---|---|---|---|
| `/mgl/control/site/` | `site_management` | Site Management home | Live |
| `/mgl/control/site/teams/` | `site_management_teams` | Teams list | Live |
| `/mgl/control/site/teams/<id>/` | `site_management_team_edit` | Team display edit | Live |
| `/mgl/control/site/content/` | `site_management_content` | CMS | Live |
| `/mgl/control/site/content/<section>/` | `site_management_content_section` | CMS section | Live |
| `/mgl/control/site/settings/` | `site_management_settings` | Site settings | Live |
| `/mgl/control/site/seasons/` | `season_management` | Seasons | Live |
| `/mgl/control/site/leagues/` | `site_management_leagues` | Leagues list | Live |
| `/mgl/control/site/leagues/<id>/` | `site_management_league_edit` | League display edit | Live |

### Control POST actions

| URL | Name | Purpose |
|---|---|---|
| `/mgl/control/managers/<id>/approve/` | `control_approve_manager` | Approve **registration** `ManagerApplication`. **LOCKED (DEC-041):** not the official job-review step. **CURRENT CODE / GAP** |
| `/mgl/control/managers/<id>/reject/` | `control_reject_manager` | Reject registration application. Same GAP vs DEC-041 |
| `/mgl/control/listings/<id>/approve/` | `control_approve_listing` | Complete or go-live listing |
| `/mgl/control/listings/<id>/reject/` | `control_reject_listing` | Reject listing |
| `/mgl/control/listings/<id>/changes/` | `control_request_listing_changes` | Request changes |
| `/mgl/control/scouting/exceptions/<id>/resolve/` | `control_resolve_scout_exception` | Resolve full-squad scout |
| `/mgl/control/results/<id>/approve/` | `control_approve_result` | Officialise match |
| `/mgl/control/results/<id>/reject/` | `control_reject_result` | Reject match |
| `/mgl/control/results/<id>/rollback/` | `control_rollback_result` | Unapprove |
| `/mgl/control/awards/weekly/<id>/approve/` | `control_approve_weekly_awards` | Approve weekly |
| `/mgl/control/awards/weekly/<id>/reject/` | `control_reject_weekly_awards` | Reject weekly |
| `/mgl/control/awards/weekly/<id>/recalculate/` | `control_recalculate_weekly_awards` | Recalculate |
| `/mgl/control/awards/monthly/<id>/approve/` | `control_approve_monthly_awards` | Approve monthly |
| `/mgl/control/tokens/adjust/` | `control_adjust_tokens` | Manual token adjust |
| `/mgl/control/auctions/<id>/close/` | `control_close_auction` | Close auction |
| `/mgl/control/auctions/<id>/cancel/` | `control_cancel_auction` | Cancel auction |
| `/mgl/control/jobs/<id>/approve/` | `control_approve_job` | **Official (DEC-041):** Admin accept of the Job Application → appoint manager |
| `/mgl/control/jobs/<id>/reject/` | `control_reject_job` | Reject Job Application |
| `/mgl/control/press/<id>/approve/` | `control_approve_press` | Approve press |
| `/mgl/control/press/<id>/reject/` | `control_reject_press` | Reject press |
| `/mgl/control/releases/<id>/approve/` | `control_approve_release` | Approve release |
| `/mgl/control/releases/<id>/reject/` | `control_reject_release` | Reject release |

Starting-squad generate/approve POSTs are handled on `control_starting_squads` (same URL, form posts). Exact extra paths: **confirm in `control_views.control_starting_squads`** if new sub-URLs are added later — none are registered separately in `mgl/urls.py`.

---

## Django admin

| URL | Name | Purpose | Access | Protection | Status | System |
|---|---|---|---|---|---|---|
| `/admin/` | Django admin | ORM admin + match actions | Staff | Django staff | Live | Admin |

---

## Media

When DEBUG or `DJANGO_SERVE_MEDIA`: Django serves `MEDIA_URL` from `MEDIA_ROOT`.

---

## Existing redirects (summary)

- `/` → `/mgl/hub/` for approved managers
- `/news/` → live activity (or pressroom if `?tab=pressroom`)
- `/job-centre/` → job centre
- `/matches/` → fixture list
- `/auctions/history/` → `/auctions/?tab=history`
- `/mgl/live-activity/` → live activity
- `/mgl/pressroom/` → pressroom
- Career URLs → Job Centre when `career_required` fails
- Control URLs → login or hub when `owner_admin_required` fails
- Site Management → 403 for non-OA
- Own `/managers/<username>/` → `manager_profile`

---

## Middleware

No custom middleware. Standard Django + WhiteNoise. Route protection is **decorators and in-view checks only**.
