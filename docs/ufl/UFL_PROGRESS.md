# UFL Progress

Checklist of the **current** project, not a future roadmap disguised as done work.

Last documentation audit: 1 September 2026.

---

## COMPLETE

- Django Career Mode site (templates, not SPA)
- Auth: register, login, logout
- Custom user roles OWNER / ADMIN / MANAGER
- Manager applications + token grant on register
- Job Centre + club applications + Control appoint
- Clubs, leagues, public club pages
- Premier League official 14-club seed path
- FC26 player import / identity / face proxy
- Player states (unassigned, assigned, listed, auction, free agent)
- Personal token ledger (`RewardTransaction`)
- Transfer list / offer / seller respond / Control complete sale
- Listing caps 5 and 3/24h
- Manager auctions + bid reserve/refund
- Free-agent sign 0 TKN
- Release **requests** + Control approve
- Scouting HQ + recruit + full-squad exceptions
- Recruitment Drive packs
- Manager hub dashboard (layout locked)
- Team management
- Fixture list, submit, opponent inbox, Control approve, rollback
- Official tables and per-division stats (approved only)
- Press questions, answers, Control approve
- Live Activity + Pressroom + news posts
- Notifications inbox + header bell
- Control Centre queues (scores, transfers, press, managers, jobs, releases, awards, tokens, scouting, auctions, clubs, logs)
- Site Management CMS (display)
- LeagueSettings singleton
- UFL 25 starting-squad proposal + Owner lock
- Discord event queue + separate bot
- Public Home isolated compact page
- Shared inner UFL header + LIVE ACTIVITY bar + page header
- Youth Academy Coming Soon route
- Cup catalogue Coming Soon pages
- Hall of Fame / manager search / public manager profile
- Railway / Gunicorn / WhiteNoise / Postgres production shape
- Django test suite (last noted run: 467 OK — **re-run before citing as current**)
- This documentation set (`/docs/ufl/`)

---

## IN PROGRESS

- None from this audit as an active code change. Documentation is the current task and is complete once committed.

---

## NOT STARTED / PLACEHOLDER

- Youth Academy gameplay
- Live cup competitions (Phantom Cup, UFL CL, Europa, Conference)
- Transfer window **close** behaviour
- Loans
- Player compare / Waiting Room (removed, not to be rebuilt unless asked)
- Password reset / email verification
- REST API
- Stored MEMBER role

---

## NEEDS DECISION (Owner)

1. Should the transfer window ever close, and who toggles it?
2. Should `LeagueSettings.scout_can_recruit` actually disable recruit? (code helper is hard-coded True)
3. Should new listings require Control approval before LIVE? (code: no; old README: yes)
4. Reconcile `Team.roster_limit` default 30 vs league 28?
5. Is `Team.tokens` still a live club treasury?
6. What to do with leftover `core.Club` and `auctions.TokenTransaction`?
7. Championship / League One: when are they “live”?
8. Cups / Youth Academy go-live criteria?
9. Should pending registrants apply for clubs before manager-application approval? (code: no)
10. Is the logged-in header crop fully accepted after the CSS scale pass?
11. Production canonical domain and Discord channel map
12. Whether Django `/admin/` stays enabled for Owner

---

## NEEDS TESTING

- Full role matrix (Public / Member / Manager / Admin / Owner) on every Control POST
- Starting-squad approve on a copy of production data (never first on live)
- Token idempotency (double-submit buy, double-approve result)
- Face proxy failure / silhouette fallback
- Mobile + desktop header on Public Home vs inner pages vs hub
- Discord outbox retry (`FAILED` → resend)
- Season lock vs result approve
- Swap-transfer roster math
- Site Management 403 for managers
- See `UFL_TEST_PLAN.md`

---

## KNOWN ISSUE

- Logged-in header previously appeared zoomed/cropped vs Public Home. CSS aligned compact scale. Residual crop **NEEDS CONFIRMATION**.
- README still contains stale lines (public nav “HOME/LEAGUE/JOB OFFERS only”; scouting “30 players”; “sales need approval before live”). Code wins; README pointer added to `/docs/ufl/`.
- `scout_can_recruit()` ignores `LeagueSettings.scout_can_recruit`.
- Transfer window hook cannot close.
- Hardcoded Job Centre Discord invite.
- Default DEBUG + insecure secret if production env is wrong.
- Dual token tables historically.
- `assertNotContains(..., "Academy")` style tests are substring-dangerous because the header contains “Youth Academy”.

---

## Coverage by area

| Area | State |
|---|---|
| Public Home | COMPLETE (locked) |
| Manager Dashboard | COMPLETE (locked) |
| Global nav / header | COMPLETE |
| Auth | COMPLETE (no reset) |
| Career Mode core | COMPLETE |
| Transfers | COMPLETE (window always open) |
| Tokens | COMPLETE |
| Fixtures / results | COMPLETE |
| Stats / tables | COMPLETE |
| Jobs | COMPLETE |
| News / Live Activity / Press | COMPLETE |
| Admin / Owner Control | COMPLETE |
| Starting squads UFL 25 | COMPLETE (Owner gate) |
| Youth Academy | NOT STARTED (page only) |
| Cups | NOT STARTED (pages only) |
| Loans | NOT STARTED |
| Documentation source of truth | COMPLETE (this pass) |
