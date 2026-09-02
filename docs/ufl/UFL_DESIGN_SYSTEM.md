# UFL Design System

**Status:** Current visual system only. Do not redesign from this document.

Sources: `core/static/core/css/ufl.css` (single Canva design system), `mgl.css` (layout), page layout sheets, `core/templates/core/base.html`. Retired overlays: `mgl-theme.css`, `ufl-system.css`, `ufl-pages.css`, `ufl-finish.css`.

---

## Established decisions (already built)

- **One unified UFL identity.**
- Global structure: **UFL Header → UFL Live Activity → Page Header → Page Content.**
- **One global UFL Header** on every page (`base.html` → `.mgl-header.ufl-header`). Public Home uses the same chrome.
- **One UFL visual identity:** black + deep teal + cyan, Barlow Condensed + Manrope. Gold is only for the UFL Coin and Europa League identity.
- **Player OVR colours:** 99–80 blue / HIGH, 79–65 green / MID, 64–0 red / LOW. Accent the badge only. Stored ratings are never changed.
- **Global LIVE ACTIVITY bar** on Public Home and inner chrome (`live_activity_bar.html`, `.ufl-livebar`).
- **Common Page Header** include: `core/includes/mgl_page_header.html`.
- **Site-wide styling** via `ufl.css`. Page sheets inherit Canva tokens.
- Public and logged-in pages share the same colour/type language; Public Home uses a tighter header implementation.

---

## Colour tokens (`:root` in `ufl.css`)

| Token | Value |
|---|---|
| `--ufl-bg` | `#0d0d0d` |
| `--ufl-bg-mid` | `#121212` |
| `--ufl-surface` | `#121212` |
| `--ufl-surface-2` | `#1a1a1a` |
| `--ufl-cyan` | `#00e5ff` |
| `--ufl-graphite` | `#16252b` |
| `--ufl-gold` | remapped to cyan globally; gold kept only for the coin and Europa League |
| `--ufl-cyan` | `#16d9d2` (primary accent) |
| `--ufl-text` | `#f5f7f8` |
| `--ufl-text-soft` | `#c5d0d3` |
| `--ufl-muted` | `#98a5aa` |
| `--ufl-line` | `rgba(22, 217, 210, 0.12)` |
| `--ufl-success` | `#32d47c` |
| `--ufl-danger` | `#ef5350` |
| `--ufl-rating-high` | `#3298ff` (OVR 80–99) |
| `--ufl-rating-mid` | `#32d47c` (OVR 65–79) |
| `--ufl-rating-low` | `#ef5350` (OVR 0–64) |
| `--ufl-coin-gold` | `#c9a74a` (currency icon only) |
| `--ufl-warning` | `#e8a23a` |
| `--ufl-radius` | `10px` / `--ufl-radius-sm` `8px` |
| `--header-h` | `52px` |
| `--container` | `1180px` |

Legacy `--mgl-*` aliases map onto the UFL tokens. Do not introduce a second palette.

---

## Typography

- Display: `"Barlow Condensed", "Arial Narrow", sans-serif` (`--font-display`)
- Body: `"Manrope", "Segoe UI", sans-serif` (`--font-body`)
- Loaded from Google Fonts in `base.html` (weights 600–900 condensed; 400–800 Manrope)
- Scale: `--ufl-hero`, `--ufl-page`, `--ufl-section`, `--ufl-card-title`, `--ufl-body` `1rem`, `--ufl-meta`, `--ufl-label`
- Base `html, body`: 16px, line-height 1.55, `overflow-x: hidden`

---

## Header

### Public Home (source of truth for compact chrome)

- Bar class `.uh-header` / `.uh-header-bar`
- Logo `ufl-logo-chrome.png`
- Nav: HOME · LEAGUES · CLUBS · FIXTURES · TABLES · STATISTICS · JOBS
- CTA: gold **JOIN UFL / LOGIN** (or PROFILE if authenticated on that template)
- Must **not** show MY TEAM, MARKET, Youth Academy, `data-notify-dropdown`

### Inner pages

- `.mgl-header` overlay compact rules in `ufl-pages.css`: 44px logo, 11px nav, 30px actions/bell, 28px avatar
- Username copy hidden at ≤1280px
- Signed-in: notification bell, avatar, PROFILE / LOGOUT
- Burger + checkbox nav for mobile
- Control Centre dropdown only for Owner/Admin

### LIVE ACTIVITY bar

- Height **34px**, ~10px type, compact padding (`ufl-system.css`)
- Label **UFL LIVE ACTIVITY**; empty state “No recent league activity.”
- Link ALL ACTIVITY → `/news/activity/`

---

## Known login visual issue (header scale / crop)

**CONFIRMED problem that existed:** logged-in inner header used a larger `--header-h` (64px) and larger logo/nav/bell than Public Home, so the logged-in view looked zoomed or cropped compared with the logged-out framing.

**CONFIRMED CSS pass:** inner header scale was aligned to Public Home (52px bar, 44px logo, 11px nav, 34px livebar) **without** `transform: scale` on the page body. That pass is already in the application. **Do not change the application as part of a documentation task.**

**STATUS: NEEDS OWNER VISUAL CONFIRMATION**

This remains a visual check, not a new functional rule. Do not claim the issue is permanently gone until the Owner confirms the current appearance.

---

## Cards, buttons, tables, forms, modals

**CONFIRMED language (do not restyle globally)**

- Surfaces: `--ufl-surface` cards, gold hairline, 10px radius, `--ufl-shadow`
- Primary CTA: gold fill, dark ink (`header-button-solid`, `.uh-btn-gold`)
- Ghost/outline buttons on gold line
- Tables: dark rows, gold headers, compact numeric stats
- Forms: dark inputs, gold focus (existing `mgl` form classes)
- Flashes: success/danger tokens
- Modals/dialogs: existing Control and market templates; no separate component library (not React/shadcn)

Hub-specific: `mgl-hub.css` (do not redesign Manager Dashboard).

Public Home: `ufl-public-home.css` + official images `ufl-home-*.jpg`.

---

## Navigation patterns

- Dropdowns from `mgl/nav.py` (`nav_dropdown.html`)
- Active state `.is-active` on current section
- Job Centre is a top-level link after Cups
- Coming Soon items still appear in MARKET / CUPS

---

## Responsive behaviour

**CONFIRMED**

- Viewport meta in `base.html`
- Burger menu for small screens
- `overflow-x: hidden` on html/body
- Header username hidden ≤1280px
- Hub outstanding fixtures: slice to 8 + scroll
- Public Home and inner pages are expected to work on desktop and mobile

**NEEDS CONFIRMATION:** a full breakpoint matrix (exact pixel steps beyond header rules) was not exhaustively tabulated in this audit. Use existing CSS media queries; do not invent new breakpoints.

---

## Logos and imagery

- Chrome logo: `core/static/core/img/ufl-logo-chrome.png`
- Public Home photography: `ufl-home-*.jpg`
- Club crests: `Team.logo` / `badge_code`. **Phase 1:** Admin can change name/logo/branding. CURRENT CODE: Site Management display edits; `badge_code` is not rewritten when the short name changes.
- Player faces: proxy + silhouette fallback

---

## What this file is not

It is not a redesign brief. Future UI work must match these tokens and the two-header split (Public Home vs inner).
