# UFL Progress

Checklist of the **current** project, not a future roadmap disguised as done work.

Last documentation update: 1 September 2026 — **Phase 1 rules lock** (documentation only).

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
- Django `/admin/` remains
- Scout setting must enforce (locked as intent; code still hard-codes True)

Still in Phase 1 as confirmation, not as missing Owner rules:

- Logged-in header appearance: **NEEDS OWNER VISUAL CONFIRMATION**
- Time zone for Sunday 10:00 AM: **NEEDS OWNER DECISION**
- Whether manager-application approval stays in addition to job-application approval: **NEEDS OWNER DECISION**

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
- Starting-squad **proposal/lock mechanism** (generator still 25; locked product shape is 30)
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

- None as application work. Phase 1 documentation lock is done.

---

## NOT STARTED / PLACEHOLDER (product)

- Youth Academy gameplay
- Live cup competitions (token amounts for winner/runner-up are locked for when cups exist)
- Loans
- Player compare / Waiting Room (removed, not to be rebuilt unless asked)
- Password reset / email verification
- REST API
- Stored MEMBER role
- **Implement Phase 1 gaps** (30-player squads, 38-club structure, release without Control, scout setting enforcement, per-pack opening limits, 0.5 validators, job form fields) — **not started; do not start without an explicit implementation task**

---

## NEEDS OWNER CONFIRMATION / DECISION

1. Logged-in header vs Public Home: **NEEDS OWNER VISUAL CONFIRMATION**
2. Time zone for Sunday 10:00 AM weekly rewards
3. Does manager-application approval remain in addition to job-application approval?
4. Do code listing/auction caps (5 / 3 / 3) stay?
5. Production canonical domain and Discord channel map
6. Whether `Team.tokens` is still a live club treasury
7. Leftover `core.Club` and `auctions.TokenTransaction`

---

## NEEDS TESTING

Unchanged from the audit. See `UFL_TEST_PLAN.md`. Do not run destructive tests against production.

---

## KNOWN ISSUE / GAP vs Phase 1

- Header crop: CSS aligned; **NEEDS OWNER VISUAL CONFIRMATION**
- Code starting shape 25 / max_squad 28 vs locked 30
- Code/data 14 PL test clubs vs locked 16/14/8
- Releases still require Control vs locked no-approval
- `scout_can_recruit()` ignores LeagueSettings
- Pack per-opening limits not confirmed in the Pack model
- Token 0.5 increments not validated
- Job form: games-per-week and Discord ID vs Phase 1 username + 1–3 / 3–5 / 6+
- Extra manager-application step vs MEMBER → job → accept
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
| Jobs | COMPLETE in code; form/flow GAP vs Phase 1 |
| News / Live Activity / Press | COMPLETE |
| Admin / Owner Control | COMPLETE; Django admin retained |
| Starting squads | Mechanism complete; official 30s not applied |
| League structure | Test 14 PL; official 38 not applied |
| Youth Academy | NOT STARTED (page only) |
| Cups | NOT STARTED (pages only; winner/runner-up amounts locked) |
| Loans | NOT STARTED |
