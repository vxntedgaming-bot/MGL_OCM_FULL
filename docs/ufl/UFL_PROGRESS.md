# UFL Progress

Checklist of the **current** project, not a future roadmap disguised as done work.

Last documentation update: 1 September 2026 — **DEC-042 player-status lock + Season 1 pool feasibility (read-only)**.

---

## PHASE 1 — LOCK UFL RULES

**Status: SUBSTANTIALLY COMPLETE**

Owner Phase 1 decisions are recorded in `/docs/ufl/` as **LOCKED**. No application or database changes were made to implement them.

Locked:

- Transfer window never closes
- Listings / release listings do not require approval
- Transfer requests require approval before official/live
- Admin/Owner control pack availability
- Per-pack opening limits (configurable; enforcement is a future implementation task)
- Pack/token 0.5 increments
- Starting squad 30 + locked positional structure
- Starter league 16 / 14 / 8
- Admin can change club names/logos
- Current 14 PL clubs are test data
- Virtual game + website as official record; DB source of truth; Discord sync
- Weekly rewards Sunday 10:00 AM → Sunday 10:00 AM and the locked token table
- Job applications require Admin acceptance
- **Job Application is the single application process (DEC-041) — LOCKED**
- Django `/admin/` remains
- Scout setting must enforce (locked as intent; code still hard-codes True)

Still in Phase 1 as confirmation, not as missing Owner rules:

- Logged-in header appearance: **NEEDS OWNER VISUAL CONFIRMATION**
- Time zone for Sunday 10:00 AM: **NEEDS OWNER DECISION**

Job Application implementation (remove extra manager-application gate; Discord username; 1–3 / 3–5 / 6+): **NEEDS IMPLEMENTATION** — documentation only; do not start without an explicit implementation task.

Implementation of gaps is **not** Phase 1. That is a later, explicit task.

---

## COMPLETE

- Django Career Mode site (templates, not SPA)
- Auth: register, login, logout
- Custom user roles OWNER / ADMIN / MANAGER
- Manager applications + token grant on register
- Job Centre + club applications + Control appoint
- Clubs, leagues, public club pages
- Premier League official 14-club **test** seed path (not the final 38)
- FC26 player import / identity / face proxy
- Player states (unassigned, assigned, listed, auction, free agent)
- Personal token ledger (`RewardTransaction`)
- Transfer list / offer / seller respond / Control complete sale
- Listing caps 5 and 3/24h (code defaults)
- Manager auctions + bid reserve/refund
- Free-agent sign 0 TKN
- Release **requests** + Control approve (**code**; Phase 1 says releases should not need this)
- Scouting HQ + recruit + full-squad exceptions
- Recruitment Drive packs
- Manager hub dashboard (layout locked)
- Team management
- Fixture list, submit, opponent inbox, Control approve, rollback
- Official tables and per-division stats (approved only)
- Press questions, answers, Control approve
- Live Activity + Pressroom + news posts
- Notifications inbox + header bell
- Control Centre queues
- Site Management CMS (display; club name/logo)
- LeagueSettings singleton
- Starting-squad **30-player** Control generate / Owner approve / lock (production squads not applied)
- Season 1 **38-club** bootstrap with dry-run (production apply blocked)
- Discord event queue + separate bot
- Public Home isolated compact page
- Shared inner UFL header + LIVE ACTIVITY bar + page header
- Youth Academy Coming Soon route
- Cup catalogue Coming Soon pages
- Hall of Fame / manager search / public manager profile
- Railway / Gunicorn / WhiteNoise / Postgres production shape
- Django `/admin/` retained
- Documentation set (`/docs/ufl/`) including Phase 1 lock

---

## IN PROGRESS

- Season 1 production bootstrap: **WAITING ON OWNER APPROVAL**. Mechanism implemented; apply blocked.
- Generator still uses exact position + stored `is_free_agent` exclusion. **DEC-042 Season 1 eligibility is documented; not applied in code yet.**

---

## NOT STARTED / PLACEHOLDER (product)

- Youth Academy gameplay
- Live cup competitions (token amounts for winner/runner-up are locked for when cups exist)
- Loans
- Player compare / Waiting Room (removed, not to be rebuilt unless asked)
- Password reset / email verification
- REST API
- Stored MEMBER role
- **Apply DEC-042 Season 1 eligibility in the generator** (unsigned, ignore FA flag, RB/LB wing-back mapping) — **NEEDS IMPLEMENTATION**
- **Apply Season 1 bootstrap + generate/approve 30-player squads on production** — Owner must authorise later
- Remaining Phase 1 gaps: release without Control, scout setting enforcement, per-pack opening limits, 0.5 validators, **DEC-041 single Job Application**
- Free Agents page still driven by `is_free_agent` (many unused FC26 rows flagged true) — GAP vs DEC-042

---

## NEEDS OWNER CONFIRMATION / DECISION

1. Logged-in header vs Public Home: **NEEDS OWNER VISUAL CONFIRMATION**
2. Time zone for Sunday 10:00 AM weekly rewards
3. Do code listing/auction caps (5 / 3 / 3) stay?
4. Production canonical domain and Discord channel map
5. Whether `Team.tokens` is still a live club treasury
6. Leftover `core.Club` and `auctions.TokenTransaction`

---

## NEEDS TESTING

Unchanged from the audit. See `UFL_TEST_PLAN.md`. Do not run destructive tests against production.

---

## KNOWN ISSUE / GAP vs Phase 1

- Header crop: CSS aligned; **NEEDS OWNER VISUAL CONFIRMATION**
- Production still has 14 PL test clubs / mixed squads; 38-club + 30-player apply not executed
- Code starting shape and roster limit are 30; production data is not yet that structure
- Releases still require Control vs locked no-approval
- `scout_can_recruit()` ignores LeagueSettings
- Pack per-opening limits not confirmed in the Pack model
- Token 0.5 increments not validated
- Job form: games-per-week and Discord ID vs Phase 1 username + 1–3 / 3–5 / 6+
- Extra manager-application step vs DEC-041 single Job Application — **NEEDS IMPLEMENTATION**
- Weekly/cup reward table not confirmed as implemented
- Hardcoded Job Centre Discord invite
- Default DEBUG + insecure secret if production env is wrong

---

## Coverage by area

| Area | State |
|---|---|
| Phase 1 rules documentation | SUBSTANTIALLY COMPLETE |
| Public Home | COMPLETE (locked layout) |
| Manager Dashboard | COMPLETE (locked layout) |
| Global nav / header | COMPLETE; visual check open |
| Auth | COMPLETE (no reset) |
| Career Mode core | COMPLETE (data protected) |
| Transfers | COMPLETE in code; Phase 1 listings match; releases GAP |
| Tokens | COMPLETE ledger; 0.5 rule locked, not enforced |
| Fixtures / results | COMPLETE |
| Stats / tables | COMPLETE |
| Jobs | Rule **LOCKED** (DEC-041). Code **NEEDS IMPLEMENTATION** |
| News / Live Activity / Press | COMPLETE |
| Admin / Owner Control | COMPLETE; Django admin retained |
| Starting squads | 30-player generator live; production allocation not applied |
| League structure | 38-club bootstrap implemented; production still 14 PL test clubs |
| Youth Academy | NOT STARTED (page only) |
| Cups | NOT STARTED (pages only; winner/runner-up amounts locked) |
| Loans | NOT STARTED |
