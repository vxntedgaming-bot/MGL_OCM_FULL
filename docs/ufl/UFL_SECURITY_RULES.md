# UFL Security Rules

**Status:** Audit of current authentication and authorisation.  
**Do not fix issues from this file unless explicitly asked.**

---

## Authentication

**CONFIRMED**

- Django session authentication; `accounts.User` as `AUTH_USER_MODEL`
- Login `/login/`, logout `/logout/`, register `/register/`
- Password validators: similarity, minimum length, common, numeric
- CSRF middleware on all unsafe methods
- Production (`DJANGO_DEBUG=false`): `SECURE_SSL_REDIRECT`, secure session/CSRF cookies, HSTS (defaults 31536000 + subdomains + preload), `SECURE_PROXY_SSL_HEADER` when `DJANGO_USE_X_FORWARDED_PROTO`
- DEBUG default **True** with embedded `django-insecure-` development secret
- No custom auth backend found
- No password-reset URLs in `managers/urls.py`

---

## Authorisation and role checks

**CONFIRMED**

| Mechanism | Use |
|---|---|
| `User.role` | OWNER / ADMIN / MANAGER |
| `ufl_access_role()` | PUBLIC / MEMBER / MANAGER / ADMIN / OWNER (capability) |
| `career_required` | Approved manager or OA |
| `owner_admin_required` | OA; others → hub |
| `site_manage_required` | OA; others → 403 |
| `approved_manager()` | Application status APPROVED |
| `is_owner()` | Starting squads; match override |
| Service-layer club checks | Sell, release, submit, respond |

Django `is_staff` / `is_superuser` gate `/admin/` only.

---

## Manager-to-club restrictions

Enforced in services (`list_player_for_sale`, `respond_to_transfer_offer`, `submit_match`, `release_my_player`, `sign_free_agent`, `dispatch_scout`). UI hiding is not sufficient; these checks are server-side.

---

## Protected routes

See `UFL_ROUTES.md`. Summary:

- Career GET/POST: `career_required` **or** login + `approved_manager`
- Control: `owner_admin_required`
- Site Management: `site_manage_required`
- Public league/news/jobs/rules: no login
- Fixture detail: released fixtures only
- Face proxy: **no auth**

There is **no** custom middleware for roles.

---

## API protection

There is no DRF/REST API. HTML POSTs + notification panel + face proxy. CSRF applies to session POSTs. The face proxy fetches remote Sofifa URLs and writes under `media/player_faces/`.

---

## Database protection

- No row-level security in Postgres was found in repo config.
- Integrity relies on Django ORM, `select_for_update` on token and listing paths, and unique constraints (pending release, notification source_key, etc.).
- Anyone with Django staff or a database URL can mutate data. Production `DATABASE_URL` must stay secret.

---

## Admin and Owner protection

- Control URLs check `role in [OWNER, ADMIN]`.
- Starting-squad **approve** additionally requires Owner.
- Site Management 403 for managers (does not leak a hub redirect that some clients treat as success).
- Django admin is a second, staff-based surface that can approve matches.

---

## SECURITY ISSUES TO REVIEW

Documented only. **Do not fix in this audit.**

1. **Default DEBUG=True** and shipped `django-insecure-` secret in `config/settings.py`. Safe only if production always sets `DJANGO_DEBUG=false` and a real secret. Misconfiguration would expose debug pages and the fallback key.

2. **Hardcoded Discord invite** `JOBS_DISCORD_INVITE` in `mgl/job_applications.py`, independent of `DISCORD_INVITE_URL`. Invite rotation requires a code change.

3. **Transfer window always open.** Hook cannot currently close the market.

4. **Market POSTs use `@login_required` not `@career_required`.** In-view `approved_manager()` blocks pending members, but an approved manager **without** a club hits service ValueErrors rather than a single gate. Confirm this is intended.

5. **Django `/admin/`** is enabled. Confirm production staff list is minimal and 2FA is handled at host/IdP level (not in this app).

6. **`DJANGO_SERVE_MEDIA`** can serve user uploads from the app process. Treat uploaded logos as untrusted files.

7. **Player face proxy** (`/mgl/players/<id>/face/`) is unauthenticated and fetches remote images. Review SSRF/cache growth if IDs or stored URLs can be influenced.

8. **Two token writers historically** (`RewardTransaction` vs `auctions.TokenTransaction`). Current services say RewardTransaction is authoritative; leftover writers would desync balances.

9. **`Team.roster_limit` default 30 vs league 28** can confuse enforcement if a row is edited.

10. **No MEMBER stored role** — easy to mis-check `user.role == MANAGER` and treat pending applicants as appointed managers. Some views correctly use `approved_manager()`.

11. **CSRF/session security depends on DEBUG.** Local defaults are insecure by design.

12. **Registration is open** (`is_active=True` immediately). Career is gated, but accounts can be created without approval.

13. **Notification / face / media** endpoints should stay recipient- or object-scoped; re-check if new JSON endpoints are added.

14. **Gunicorn 2 workers** + SQLite is unsafe if someone runs production on SQLite (README already warns).

15. **`scout_can_recruit()` hard-coded True** — a Control setting that looks like a safety switch does not actually disable recruit.

---

## What is working as designed

- Owner/Admin Control is not available to managers.
- Site Management returns 403 rather than a silent skip.
- Listing completion and token debit/credit are atomic with row locks.
- Managers cannot auction the unassigned pool (403).
- Official stats apply once (`stats_applied` / approve-once).
- Starting-squad approve is Owner-only and confirm-gated.
