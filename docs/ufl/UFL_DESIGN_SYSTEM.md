# UFL Design System

**Status:** Current visual system only.

Source of truth: `core/static/core/css/ufl.css` (the only stylesheet loaded by the application).

Retired from active use (files may remain on disk for collectstatic / presentation tests): `mgl.css`, `mgl-theme.css`, `ufl-system.css`, `ufl-pages.css`, `ufl-finish.css`, and page sheets such as `mgl-jobs.css`.

Do not add overlay files (`finish.css`, `override.css`, `new-theme.css`).

---

## Philosophy

Simple, clean, compact, professional football league / career-mode site.

Not a neon dashboard. Not oversized SaaS cards. Not cyan / teal / gold chrome.

---

## Colour

| Use | Colour |
|---|---|
| Background | Black `#0a0a0a` |
| Surfaces | Dark charcoal `#111` / `#161616` |
| Text | White / muted grey |
| Approve / success / live / verified | Green `#2f9e5f` |
| Reject / error / cancelled | Red `#d64545` |
| Pending / warning / postponed | Amber `#d4a017` |
| UFL Coins only | Gold `#d4af37` |
| Player OVR 80–99 only | Blue `#3b82f6` |
| Player OVR 65–79 | Green |
| Player OVR 0–64 | Red |

Do not use cyan, teal, neon, random purple/pink, gold buttons, gold navigation, or gold borders.

---

## Type

- Font: Inter
- Page title: 32px max (26px mobile)
- Section heading: 22px max
- Card heading: 16–18px
- Body: 14–16px
- Metadata: 12–13px
- Hero brand may be 32px; no 50–80px page titles

---

## Layout

- Container: `width: calc(100% - 40px); max-width: 1200px; margin: 0 auto`
- Mobile: `width: calc(100% - 24px)`
- Spacing scale: 8 / 12 / 16 / 24 / 32 / 40
- Card padding: 16px
- Button height: 38–42px
- Header bar: 64–72px, 3-column grid (logo \| centred nav \| account)
- News ticker under header: 36–42px, existing `NewsPost` headlines, 1.5s rotate, pause on hover, reduced-motion

---

## Chrome

1. One header (`base.html` → `.mgl-header`)
2. One news ticker (`live_activity_bar.html` → `.ufl-ticker`) using `mgl_live_items`
3. One page title (`mgl_page_header.html`)
4. One footer
5. One card / button / table / rating / coin / notification / verification / Control Centre system

Public nav labels stay test-compatible: HOME, LEAGUES, CLUBS, FIXTURES, TABLES, STATISTICS, JOBS, LOGIN, SIGN UP.

Signed-in nav stays test-compatible: MY TEAM, MARKET, LEAGUES, JOB CENTRE, STATS, HISTORY, CUPS, CONTROL.

---

## Currency and ratings

- User-facing balance: gold coin icon + amount. Never `TKN` / `Tokens`.
- Stored `tokens` field names and balances are unchanged.
- OVR bands are presentation only. Stored ratings are never changed.
