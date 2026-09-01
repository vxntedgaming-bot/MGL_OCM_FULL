# UFL Discord / YourBot Audit

**Status:** Inspection only. 1 September 2026.  
**No application code, migrations, production data, Discord messages, or Season 1 work were performed for this audit.**

Locked rules this audit does **not** change: website/database is the source of truth; Discord is an outbox (DEC-010, DEC-035); Job Application is the single application process (DEC-041); unsigned ≠ Free Agent (DEC-042); Season 1 production bootstrap is not authorised; the current 14 clubs are test production data.

There is **no YourBot codebase** in this repository. “YourBot” appears only as a Phase 3/4 “do not connect” note. The only bot implementation is `discord_bot/bot.py` (UFL outbox publisher).

---

## 1. Current Architecture

UFL is a Django website. Official football state lives in PostgreSQL/SQLite. Discord is a **notification layer after commit**.

```
Website service (create_news / notify_user / emit_official_event)
        ↓
DiscordEvent row  (PENDING)
        ↓
Separate process  run_mgl_bot.py → discord_bot/bot.py
        ↓
Discord channel text  or  DM (if User.discord_id is numeric)
```

| Piece | File | Function/class | What it currently does | Reuse? | Change? | Why |
|---|---|---|---|---|---|---|
| Official news + outbox side effect | `mgl/services.py` | `create_news` | Writes `NewsPost`, then calls `queue_from_news`. Exceptions from the queue are swallowed so Discord cannot roll back the news row. | **Reuse** | Minor | Correct “DB first” shape. Some callers bypass it (see TOTW). |
| Official event wrapper | `mgl/events.py` | `emit_official_event` | Calls `create_news` then `queue_from_news` again. Second call is a no-op because `queue_from_news` skips if a `DiscordEvent` already exists for that news row. | **Reuse** | Optional cleanup | Only starting-squad approve uses it today. Double-queue is harmless. |
| Outbox writer | `mgl/discord_queue.py` | `queue_discord_event` | Inserts `DiscordEvent` PENDING with `event_type`, `channel_key`, JSON `payload`, optional `news_post`. | **Reuse** | Yes later | Needs richer event types and idempotency keys for Phase 5. |
| News → outbox | `mgl/discord_queue.py` | `queue_from_news` | Builds plain-text payload from title/body (press has a dedicated formatter). Skips unpublished posts and posts that already have any `DiscordEvent`. | **Reuse** | Yes | Text-only; category→channel map is incomplete vs desired Phase 5 events. |
| Personal DM queue | `mgl/discord_queue.py` | `queue_personal_discord` | Queues `channel_key=DM` only if `User.discord_id` is set and the inbox type matches `PERSONAL_TYPES`. | **Reuse** | Yes | Type allow-list drops REWARD / AWARD / RECRUITMENT. |
| Consumer | `discord_bot/bot.py` | `publish_queue` | Every 10s: take 10 PENDING rows; `channel.send(text)` or `member.send(text)`; mark SENT/FAILED. | **Reuse** | Yes | No embeds, no slash/buttons, no backoff. |
| News flag reconcile | `discord_bot/bot.py` | `reconcile_news` | Every 20s: if `NewsPost.discord_sent=False` but a related event is SENT, set the flag. Does **not** enqueue missing events. | **Reuse** | Yes | Does not heal TOTW rows created without `create_news`. |
| Process entry | `run_mgl_bot.py` | module | Starts the Client if `DISCORD_TOKEN` is set. | **Reuse** | Keep separate from Gunicorn | Matches DEC-010. |
| Website Discord ID link | `mgl/views.py` | `manager_profile` | Career POST `action=link_discord` stores numeric `User.discord_id`. | **Reuse** | Yes | Website form, not a Discord command. Required for DMs. |

Django / Gunicorn does **not** start the bot. `railway.toml` only sets `releaseCommand = "true"`. There is no Celery, cron, or management command that publishes Discord.

---

## 2. Existing Discord Integration

### Connection / configuration

| Item | Location | Current behaviour |
|---|---|---|
| Bot token | Env `DISCORD_TOKEN` | Read in `discord_bot/bot.py`. Empty → process exits. **Not hardcoded.** |
| Channel map | Env `UFL_CHANNELS` or legacy `MGL_CHANNELS` | `CATEGORY:CHANNEL_ID` CSV parsed at import time into `CHANNEL_MAP`. |
| Public invite | Env `DISCORD_INVITE_URL` + Site Management `settings.discord_invite_url` | `mgl/site_cms.py` `resolved_discord_invite()`. Empty hides JOIN DISCORD on the public site. |
| Job Centre invite | `mgl/job_applications.py` `JOBS_DISCORD_INVITE` | **Hardcoded** `https://discord.gg/Jmf29wBafP`. Independent of CMS/env. |
| Dependency | `requirements-mgl.txt` | `discord.py>=2.6` (optional comment; still listed). |
| Settings | `config/settings.py` | Only `DISCORD_INVITE_URL`. Token/channels are **not** Django settings. |

### Bot implementation

- **File:** `discord_bot/bot.py`
- **Class:** `discord.Client` (not `commands.Bot`, not `discord.app_commands`).
- **Intents:** `discord.Intents.default()` only. No message-content, members, or guild-member privileged intents.
- **On ready:** starts `publish_queue` and `reconcile_news`.
- **Send path:** plain `channel.send(text)` / `member.send(text)`. **No embeds. No attachments. No components.**
- **Writes:** only `DiscordEvent` status fields and `NewsPost.discord_sent`. The bot does **not** write players, tokens, clubs, managers, fixtures, or `StartingSquadLock`.

### Webhooks

**None.** No `webhook_url`, incoming webhook views, or outgoing webhook client.

### Control Centre Discord

**None.** `mgl/control_views.py` has no Discord page. Control Managers **displays** Job Application Discord username (`mgl/templates/mgl/control_managers.html`). That is website data, not a bot control.

Django admin does **not** register `DiscordEvent`. There is no Control UI to retry FAILED rows.

### Channel configuration (expected keys)

From `mgl/discord_queue.py` `CHANNEL_FOR_CATEGORY` and `discord_bot/bot.py` `_channel_id` aliases:

| Channel key | Used for |
|---|---|
| `NEWS` | Default fallback; RESULTS, MANAGER, SIGNING, SCOUTING, REWARD |
| `TRANSFER MARKET` / `TRANSFER` / `TRANSFER_MARKET` | Transfer listings and completed transfers |
| `AUCTIONS` | Manager/admin auction news |
| `FREE_AGENTS` / `FREE AGENTS` | Genuine FA news |
| `PRESS` | Approved press conferences |
| `DM` | Personal inbox mirror |

`.env.example` documents `UFL_CHANNELS=NEWS:123,PRESS:456,TRANSFER MARKET:789,AUCTIONS:111,FREE_AGENTS:222`.  
`discord_bot/README.md` still shows the older `MGL_CHANNELS` example (`RESULTS`, `TRANSFER`, `AUCTION`, `FREE_AGENT`, `REWARD`). Those keys only work via alias or NEWS fallback.

### Role / permission handling on Discord

**None.** The bot never reads Discord roles, guilds, or slash permissions. UFL roles (OWNER / ADMIN / MANAGER / capability MEMBER) are enforced only on the website.

---

## 3. Existing Commands

| Kind | Exists? | Detail |
|---|---|---|
| Prefix commands | **No** | No `commands.Bot`, no `on_message` command parser |
| Slash commands | **No** | No `app_commands`, no `tree.sync` |
| Buttons / select menus / modals | **No** | No `discord.ui` |
| Context menus | **No** | |
| Scheduled Discord commands | **No** | Only the two poll loops |

There is therefore **no** Discord command that can change tokens, ownership, Free Agent status, Job Applications, StartingSquadLock, or Season 1.

The only “Discord-related command” on the website is `manager_profile` POST `link_discord` (numeric ID). That writes `User.discord_id` only.

---

## 4. Existing Permissions

| Surface | Who | What |
|---|---|---|
| Website Career pages | `career_required` (approved manager identity or Owner/Admin) | Link/unlink Discord ID |
| Job Application | Logged-in member without a club | Stores Discord **username**; optional numeric ID onto `User` |
| Control Job Applications | Owner/Admin | Reads Discord username; cannot send Discord from Control |
| Bot process | Whoever holds `DISCORD_TOKEN` | Can send to mapped channels and DM any stored `discord_id` |
| Discord guild roles | — | Unused |

`queue_personal_discord` allow-list (`PERSONAL_TYPES`): TRANSFER, AUCTION, PRESS, MATCH, RESULT, ADMIN, SCOUTING, CLUB.

**Not** mirrored to Discord DMs even if `discord_id` is linked:

- `REWARD` / `AWARD` (weekly awards inbox)
- `RECRUITMENT` (pack-ready inbox)

Release inbox type is `CLUB`, so a linked manager **does** get a DM on official release.

---

## 5. Existing Outbox / Queue

**Model:** `mgl.models.DiscordEvent` (migration `mgl.0021_ufl_foundation`)

| Field | Purpose |
|---|---|
| `event_type` | News category or notification type string |
| `channel_key` | NEWS / TRANSFER MARKET / AUCTIONS / FREE_AGENTS / PRESS / DM |
| `payload` | JSON: typically `text`, `title`, `body`, `news_id`; DMs also `discord_id` |
| `status` | PENDING / SENT / FAILED |
| `attempt_count` | Incremented on send or fail |
| `last_attempt_at` | Last try |
| `error` | Last error, truncated to 2000 chars |
| `sent_at` | Set on SENT |
| `news_post` | Optional FK; SET_NULL |
| `created_at` | Queue order |

**Statuses**

- PENDING — eligible for the 10s poll
- SENT — delivered; related `NewsPost.discord_sent` set true
- FAILED — `attempt_count >= 20`

**Retry**

- `mark_discord_failed` (`mgl/discord_queue.py`) keeps status PENDING until 20 failures, then FAILED.
- No backoff. The same row is retried every 10 seconds while PENDING.
- Unconfigured channel → immediate fail increment (“No Discord channel configured”).
- Missing `discord_id` on a DM row → fail increment.

**Failure**

- FAILED rows stay in the table. Nothing resends them. No Control “retry” action.

**Duplicate protection / idempotency**

- `queue_from_news`: one event per `news_post` (exists check, **not** a unique constraint).
- `queue_discord_event`: always inserts. Personal DMs have no idempotency key.
- `notify_user` uses `get_or_create(source_key=...)` so a new inbox row is required before a DM is queued.

**Who creates events**

- `create_news` after most official news writes
- `emit_official_event` (starting-squad approve)
- `notify_user` → `queue_personal_discord` for allow-listed types when `discord_id` is set

**Who consumes**

- `discord_bot.bot.publish_queue` only

**Tied to UFL transactions?**

- Queue insert usually happens in the same request as the official write, after the state change.
- `create_news` / `emit_official_event` catch queue exceptions so Discord cannot undo football state.
- If the request transaction rolls back after `create_news`, the event rolls back with it (same atomic request). The bot never participates in that transaction.

**Payload richness**

- Enough to post a title + body string.
- Not enough for structured embeds (no player FC26 id, token amount, auction id, deep-link contract, listing kind).
- Press formatter (`format_press_discord`) is the only richer template.

**Suitable for Phase 5?**

**Yes as the spine.** Reuse `DiscordEvent` + separate consumer. Do not replace it with Discord-as-database. Extend event types, embeds, Control retry, and idempotency. Do not give the bot write access to UFL domain tables.

---

## 6. Website → Discord Flow

1. Website service commits official state (club, player, tokens, approval).
2. Same request creates `NewsPost` via `create_news` **or** `ManagerNotification` via `notify_user`.
3. Outbox row is inserted PENDING.
4. If `run_mgl_bot.py` is running **and** `DISCORD_TOKEN` + channel map are set, the bot posts within ~10 seconds.
5. If the bot is not running (current documented production state: **not connected**), rows remain PENDING forever.

Public JOIN DISCORD buttons use CMS/env invite. Job Offers after apply opens/hardcodes `JOBS_DISCORD_INVITE`.

---

## 7. Discord → Website Flow

**No Discord-originated UFL writes exist.**

The bot never:

- creates Job Applications
- approves/rejects anything
- moves players
- changes tokens
- lists auctions
- opens packs
- signs Free Agents
- submits matches
- touches `StartingSquadLock` or Season 1

Website-only Discord-adjacent writes:

| File | Function | What | Safe? |
|---|---|---|---|
| `mgl/views.py` | `manager_profile` | Stores numeric `User.discord_id` | Safe: login + `career_required` + unique ID. Does not grant Discord power over UFL. |
| `mgl/job_applications.py` | `submit_job_application` | Stores Discord username; optional numeric ID | Safe: official Job Application fields. |

If a future Discord command changes UFL data, it **must** call the same Python services (`approve_job_application`, `request_player_release`, `sign_free_agent`, `create_manager_auction`, etc.) with the same permission checks. Do not let the bot ORM-write domain tables.

---

## 8. UFL Events Already Supported

“Supported” here means a `DiscordEvent` **can** be created by current website code. Delivery still requires a running bot + channel map.

### Channel posts (via `create_news` / `queue_from_news`)

| Desired event | Supported? | How |
|---|---|---|
| Job Application approved / manager appointed | **Yes** | `mgl/job_applications.py` `approve_job_application` → `NewsPost.MANAGER` |
| Player released (genuine FA) | **Yes** | `mgl/services.py` `release_player` → `NewsPost.FREE_AGENT` |
| Player listed for auction (manager) | **Yes** | `mgl/market.py` `create_manager_auction` → `NewsPost.AUCTION` |
| Admin unsigned player listed for auction | **Yes** | `mgl/market.py` `create_free_agent_auction` → `NewsPost.AUCTION` |
| Auction won / sold | **Yes** | `mgl/market.py` settle path → `NewsPost.AUCTION` |
| Admin unsigned auction no-bid → genuine FA | **Yes** | `mgl/market.py` `_restore_unsold_player` → `NewsPost.FREE_AGENT` |
| Transfer listing went live | **Yes** | `list_player_for_sale` / legacy `approve_listing` → `NewsPost.TRANSFER` |
| Transfer completed | **Yes** | `_complete_listing_sale` → `NewsPost.TRANSFER` |
| Recruitment pack opened | **Partial** | `mgl/recruitment.py` `open_recruitment_pack` → `NewsPost.SIGNING` (wrong category for a dedicated RECRUITMENT channel) |
| Recruitment player selected | **Partial** | `choose_recruitment_player` → `NewsPost.SIGNING` |
| Scout player selected | **Yes** | `mgl/scouting.py` `choose_scout_player` → `NewsPost.SCOUTING` |
| Scout exception assigned by Control | **Yes** | `resolve_scout_exception` → `NewsPost.SCOUTING` |
| Free Agent signed | **Yes** | `mgl/services.py` `sign_free_agent` → `NewsPost.SIGNING` |
| Match result published | **Yes** | `mgl/match_official.py` after Admin approve → `NewsPost.RESULTS` |
| Press conference published | **Yes** | `mgl/press.py` after Admin approve → `NewsPost.PRESS` |
| Manager of the Week (Django admin approve) | **Yes** | `mgl/admin.py` `approve_selected_motw` → `create_news(REWARD)` |
| Manager left / resigned | **Yes** | `mgl/activity.py` `record_manager_departure` → `NewsPost.MANAGER` |
| Starting squads allocated (Owner approve only) | **Yes** | `mgl/ufl_starting.py` `emit_official_event(MANAGER)` — production approve is still blocked |
| Generic published UFL news | **Yes** | Any `create_news(..., publish=True)` |

### Personal DMs (linked `discord_id` only)

Queued when `notify_user` creates a **new** inbox row and the type matches `PERSONAL_TYPES`. Examples that can DM: transfer offer/sale, auction sold, press published/rejected, match/result inbox, admin job appointment/rejection, scouting choose, club release.

---

## 9. UFL Events Missing

| Desired event | Current gap |
|---|---|
| Job Application submitted | No `create_news`. Admin sees website inbox only (`notifications.py` generator). No outbox row. |
| Job Application rejected | `notify_user` ADMIN can DM the applicant if linked; **no channel announcement**. |
| Transfer request submitted (offer, not listing) | Inbox/DM possible; **no dedicated channel “request submitted” news** until listing/completion news exists. |
| Manager auction no-bid (return home) | `_restore_unsold_player` club path writes **no** news. Player returns to origin club (correct UFL rule) but Discord is silent. |
| Scouting mission started | `dispatch_scout` does not call `create_news`. |
| Scouting mission completed / ready to choose | Inbox type SCOUTING can DM; **no channel post**. |
| Match submitted (pending Admin) | Inbox for Control; **no public Discord**. Correct until official — should stay unpublished. |
| League table updated | No event. Tables are derived from approved results. |
| Player statistics updated | No event. |
| Team of the Week announced | Django admin `approve_selected_totw` uses `NewsPost.objects.create` **bypassing** `create_news` → **no `DiscordEvent`**. Control weekly-award approve uses `notify_user(REWARD)` which is **not** in `PERSONAL_TYPES` and creates **no** news. |
| Top Scorer / Top Assist reward | Website inbox REWARD only; no outbox; no DM. |
| Press Conference **reward** (token credit) | Press **publication** is queued; the +0.5 TKN credit is not a separate Discord event. |
| Cup results | Cups are Coming soon. No news path. |
| Owner/Admin announcements | Site changelog / Control messages are not queued. |
| Dedicated Job / Recruitment / Awards channels | All collapse to NEWS or SIGNING. |
| Structured embeds | All posts are plain text. |

---

## 10. Security Findings

**Do not fix in this pass. Document only.**

| Finding | File | Severity | Notes |
|---|---|---|---|
| Hardcoded Discord invite | `mgl/job_applications.py` `JOBS_DISCORD_INVITE` | Medium | Public invite, not a bot token. Rotation requires a code change. Independent of `DISCORD_INVITE_URL`. Already listed in `UFL_SECURITY_RULES.md`. |
| Hardcoded bot token | — | **None found** | Token is env-only. |
| Hardcoded channel IDs | — | **None found** | IDs come from `UFL_CHANNELS` / `MGL_CHANNELS`. |
| Hardcoded guild/server ID | — | **None found** | |
| Production bot credentials in source | — | **None found** | `.env.example` comments only. |
| Permission bypass via Discord command | — | **None** | No commands exist. |
| Member Discord commands | — | None | |
| Manager Discord commands | — | None | |
| Admin/Owner Discord commands | — | None | |
| Command that edits another club | — | None | |
| Command that changes tokens | — | None | |
| Command that changes player ownership | — | None | |
| Command that bypasses approval | — | None | |
| Command that creates a Free Agent | — | None | |
| Command that changes StartingSquadLock | — | None | |
| Command that starts Season 1 | — | None | |
| Command that runs `mgl_reset` / bootstrap | — | None | |
| Bot process DB access | `discord_bot/bot.py` | Low (current) / High (if expanded badly) | Process loads full Django ORM. Today it only updates outbox/news flags. A future change could accidentally write domain tables. |
| DM to any stored `discord_id` | `publish_queue` | Medium if IDs are wrong | No Discord-side role check. Safety is “website linked this numeric ID”. Stolen/wrong ID = leaked inbox copy. |
| Invite opened automatically after job apply | `job_centre.html` + `window.open` | Low | UX, not a secret. |
| Older workspace copy of `discord_bot/bot.py` | `/workspace/discord_bot/bot.py` | Info | Polls `NewsPost.discord_sent` directly. **Live app is `/tmp/MGL_LIVE` / GitHub `MGL_OCM_FULL`.** Do not treat the older poller as production. |

---

## 11. Production / Deployment Findings

| Question | Finding |
|---|---|
| Does Discord run inside Django/Gunicorn? | **No.** Separate process. |
| Is the bot started on Railway with the site? | **No evidence.** `railway.toml` has no bot worker. README says do not start it from install/Gunicorn. |
| Is a Discord bot already deployed? | **Not confirmed in this repo.** Phase 3/4 docs and `UFL_PROGRESS.md` say **Discord/YourBot not connected**. Queue rows would sit PENDING. |
| Scheduled/background tasks | Bot loops only (10s / 20s). No Celery. No Django-Q. |
| Retry / error handling | 20 attempts, then FAILED. No backoff. No admin retry. |
| Production channel map | **UNKNOWN** — env only; not in source. Owner still needs to confirm the live map (`UFL_PROGRESS.md` item 4). |
| This audit | Read-only. Did not run `run_mgl_bot.py`. Did not set `DISCORD_TOKEN`. Did not call Discord APIs. Did not apply migrations. Did not touch production. |

---

## 12. What Should Be Reused

1. **`DiscordEvent` outbox** — correct model for Phase 5.
2. **`create_news` → `queue_from_news`** — official public events.
3. **`notify_user` → `queue_personal_discord`** — personal copies, after website inbox.
4. **Separate bot process** — DEC-010. Keep it out of Gunicorn workers.
5. **`mark_discord_sent` / `mark_discord_failed`** — status machine.
6. **`User.discord_id` unique numeric link** — required for DMs; already validated in `manager_profile`.
7. **Job Application Discord username field** — official DEC-041 field; do not replace with numeric ID.
8. **Swallow Discord errors after commit** — never roll back football state.
9. **Channel key aliases** in `_channel_id` — keep while env names migrate from MGL → UFL.
10. **Press text formatter** — starting point for embed templates.

---

## 13. What Needs To Be Built

1. **Explicit connect decision** — Owner supplies `DISCORD_TOKEN` + `UFL_CHANNELS` and a bot worker. Do not silently start it.
2. **YourBot** — does not exist. Either define it as this outbox bot, or specify a second product. Do not invent a second database.
3. **Event catalogue** — one official event name per UFL action (job.submit, job.approve, release, auction.nobid.club, etc.).
4. **Missing `create_news` / queue calls** for events in section 9 that should be public.
5. **Fix TOTW** so it uses `create_news` (or `queue_from_news`) instead of raw `NewsPost.objects.create`.
6. **Embeds** — structured UFL cards; still rendered from website-committed payload.
7. **Control outbox page** — list PENDING/SENT/FAILED, retry FAILED, never edit football state.
8. **Idempotency keys** — unique `(source, object_id)` so double POSTs do not double-post Discord.
9. **Backoff** — stop hammering Discord every 10s on missing channels.
10. **Invite unification** — Job Centre should use `DISCORD_INVITE_URL` / CMS, not a hardcoded URL (fix later).
11. **If Discord actions are wanted** — slash/buttons that call **existing UFL services** with website auth mapping (discord_id → User). No ORM shortcuts.
12. **DM type allow-list review** — decide whether REWARD / RECRUITMENT should DM.
13. **Do not** let Discord start Season 1, generate squads, or write `StartingSquadLock`.

---

## 14. Recommended Phase 5 Implementation Order

1. **Owner connect pack (no football writes)**  
   Confirm guild, channel map, whether the current bot application is “YourBot”, and whether DMs are wanted. Document env on the host. Still do not start Season 1.

2. **Harden the outbox (still notification-only)**  
   Control retry UI; unique constraint / idempotency; backoff; route TOTW/MOTW/weekly rewards through `create_news`; unify invite; add event_type constants.

3. **Complete website → Discord coverage**  
   Add queue points for the missing events that should be public (job submitted/rejected channel policy, scout started/ready, manager no-bid return, awards). Keep match-submitted and unsigned pool **off** public Discord.

4. **Embeds + channel taxonomy**  
   NEWS / JOBS / TRANSFER MARKET / AUCTIONS / FREE AGENTS / PRESS / AWARDS. Payloads must include enough ids to rebuild an embed without querying stale copies.

5. **Optional Discord → website actions (last)**  
   Only after 1–4. Map `discord_id` → User. Call existing services. Enforce the same role/club/token/approval rules. No Season 1, no reset, no lock, no mass FA.

---

## 15. Risks

- Connecting the bot with a wrong `UFL_CHANNELS` map posts official news to the wrong Discord channel.
- Starting the bot against production while PENDING historical rows exist could dump a backlog of old news.
- Treating Discord as a second squad/transfer database would violate DEC-010/035.
- Giving the bot ORM write helpers “for convenience” would bypass approval, tokens, and DEC-042.
- Hardcoded Job Centre invite can drift from the real server.
- TOTW already creates website news that never enters the outbox — easy to assume Discord is “broken” after awards.
- 10-second retry with no backoff can rate-limit the bot if channels are misconfigured.
- Linking a numeric Discord ID is powerful (inbox DMs) and is not the official Job Application identity (username is).
- Workspace vs live-app bot files differ; implementing against the wrong tree would ship the old NewsPost poller.

---

## 16. Exact Next-Step Implementation Plan

Do **not** execute these steps in this audit.

1. Owner confirms: guild, five+ channel IDs, bot token storage, DM policy, and that Season 1 remains blocked.
2. Add `docs/ufl` channel map once Owner supplies IDs (docs only until implementation is authorised).
3. Implementation task (separate): outbox hardening + Control retry + TOTW queue fix. No Season 1. No production apply.
4. Implementation task: missing event coverage + embeds. Still outbox-only.
5. Only if Owner asks: Discord interactions that wrap existing UFL services.
6. Never: `mgl_reset`, Season 1 bootstrap `--apply`, squad generate/approve on production, FC26 mass `is_free_agent` edit, deleting the 14 test clubs.

**STOP after this document. Phase 5 is not implemented.**
