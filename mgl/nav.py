"""Canonical UFL information architecture."""

from django.urls import NoReverseMatch, reverse

from accounts.models import User
from mgl.permissions import approved_manager


LEAGUE_MENU = {
    "id": "leagues",
    "label": "LEAGUES",
    "current": {
        "leagues_page",
        "leagues_all",
        "competition_page",
    },
    "current_slugs": {"premier-league", "championship", "league-one"},
    "items": (
        {
            "label": "Premier League",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "premier-league"},
            "style": "sub",
        },
        {
            "label": "Championship",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "championship"},
            "style": "sub",
        },
        {
            "label": "League One",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "league-one"},
            "style": "sub",
        },
        {"label": "All Leagues", "url_name": "leagues_page", "divider": True},
    ),
}

CUPS_MENU = {
    "id": "cups",
    "label": "CUPS",
    "current": {"competition_page", "cups_hub", "cups_detail"},
    "current_slugs": {
        "cups",
        "phantom-cup",
        "champions-league",
        "europa-league",
        "conference-league",
    },
    "items": (
        {
            "label": "UFL Champions League",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "champions-league"},
            "style": "sub",
        },
        {
            "label": "UFL Europa League",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "europa-league"},
            "style": "sub",
        },
        {
            "label": "UFL Conference League",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "conference-league"},
            "style": "sub",
        },
        {
            "label": "UFL Phantom Cup",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "phantom-cup"},
            "style": "sub",
        },
    ),
}

MARKET_MENU = {
    "id": "market",
    "label": "MARKET",
    "current": {
        "transfer_market",
        "transfer_history",
        "public_transfers",
        "transfer_requests",
        "respond_transfer_request",
        "request_player_transfer",
        "purchase_listing",
        "free_agents",
        "player_profile",
        "player_profile_mgl",
        "player_database",
        "market_players_alias",
        "market_free_agents_alias",
        "market_auctions_alias",
        "recruitment_drive",
        "open_recruitment_pack",
        "choose_recruitment_player",
        "live_auctions",
        "place_bid",
        "scouting",
        "youth_academy",
    },
    "items": (
        {"label": "Transfers", "url_name": "public_transfers"},
        {"label": "Transfer Market", "url_name": "transfer_market", "divider": True},
        {"label": "Transfer Requests", "url_name": "transfer_requests"},
        {"label": "Free Agents", "url_name": "free_agents", "divider": True},
        {"label": "Recruitment Drive", "url_name": "recruitment_drive", "divider": True},
        {"label": "Scouting", "url_name": "scouting", "divider": True},
        {"label": "Youth Academy", "url_name": "youth_academy", "divider": True},
        {"label": "Auctions", "url_name": "live_auctions", "divider": True},
        {"label": "All Players", "url_name": "player_database", "divider": True},
        {"label": "Player Database", "url_name": "player_database"},
    ),
}

STATS_MENU = {
    "id": "stats",
    "label": "STATS",
    "current": {
        "stats_page",
        "league_stats",
    },
    "items": (
        {
            "label": "Premier League Stats",
            "url_name": "league_stats",
            "url_kwargs": {"slug": "premier-league"},
            "style": "sub",
        },
        {
            "label": "Championship Stats",
            "url_name": "league_stats",
            "url_kwargs": {"slug": "championship"},
            "style": "sub",
        },
        {
            "label": "League One Stats",
            "url_name": "league_stats",
            "url_kwargs": {"slug": "league-one"},
            "style": "sub",
        },
    ),
}

HISTORY_MENU = {
    "id": "history",
    "label": "HISTORY",
    "current": {
        "historical_tables",
        "hall_of_fame",
        "manager_search",
        "manager_public_profile",
        "news_centre",
        "live_activity",
        "pressroom",
        "answer_press",
        "clubs_index",
        "club_page",
        "club_page_clubs",
    },
    "items": (
        {"label": "Hall of Fame", "url_name": "hall_of_fame"},
        {"label": "Clubs", "url_name": "clubs_index", "divider": True},
        {"label": "Club Profiles", "url_name": "clubs_index"},
        {"label": "Manager Search", "url_name": "manager_search", "divider": True},
        {"label": "UFL Newsroom", "url_name": "live_activity", "divider": True},
        {"label": "UFL Press Conference", "url_name": "pressroom"},
    ),
}

CAREER_MENU = {
    "id": "career",
    "label": "MY TEAM",
    "current": {
        "manager_hub",
        "team_management",
        "fixture_list",
        "submit_match",
        "fixture_stats",
        "fixture_detail",
    },
    "items": (
        {"label": "Dashboard", "url_name": "manager_hub"},
        {"label": "Team Management", "url_name": "team_management", "divider": True},
        {"label": "Fixtures", "url_name": "fixture_list", "divider": True},
    ),
}

PROFILE_MENU = {
    "id": "profile",
    "label": "PROFILE",
    "current": {
        "manager_profile",
        "manager_rewards",
    },
    "items": (
        {"label": "Career Profile", "url_name": "manager_profile"},
        {"label": "Token History", "url_name": "manager_rewards", "divider": True},
    ),
}

CONTROL_MENU = {
    "id": "control",
    "label": "CONTROL CENTRE",
    "control_only": True,
    "current": {
        "control_centre",
        "control_pending",
        "control_approvals",
        "control_scores",
        "control_transfers",
        "control_press",
        "control_managers",
        "control_clubs",
        "control_starting_squads",
        "control_season_controls",
        "control_league",
        "control_logs",
        "control_weekly_awards",
        "control_monthly_awards",
        "control_tokens",
        "site_management",
        "season_management",
    },
    "items": (
        {"label": "Dashboard", "url_name": "control_centre"},
        {"label": "Approvals", "url_name": "control_pending", "divider": True},
        {"label": "Clubs & Managers", "url_name": "control_clubs", "divider": True},
        {"label": "Starting Squads", "url_name": "control_starting_squads", "divider": True},
        {"label": "Season Controls", "url_name": "control_season_controls", "divider": True},
        {"label": "League Controls", "url_name": "control_league", "divider": True},
        {"label": "History / Audit", "url_name": "control_logs", "divider": True},
    ),
}

# Public visitors: the shared UFL sections that do not require a club.
NAV_DROPDOWNS = (
    LEAGUE_MENU,
    CUPS_MENU,
)

# Approved managers / Control.
SIGNED_IN_NAV_DROPDOWNS = (
    CAREER_MENU,
    MARKET_MENU,
    LEAGUE_MENU,
    STATS_MENU,
    HISTORY_MENU,
    CUPS_MENU,
    CONTROL_MENU,
)

# Per-competition public tabs. Empty states only — no invented scores.
CUP_TABS = {
    "champions-league": (
        ("overview", "OVERVIEW"),
        ("groups", "GROUP STAGE"),
        ("bracket", "KNOCKOUT"),
        ("stats", "STATS"),
        ("history", "HISTORY"),
    ),
    "europa-league": (
        ("overview", "OVERVIEW"),
        ("groups", "GROUP STAGE"),
        ("bracket", "KNOCKOUT"),
        ("stats", "STATS"),
        ("history", "HISTORY"),
    ),
    "conference-league": (
        ("overview", "OVERVIEW"),
        ("fixtures", "FIXTURES"),
        ("table", "TABLE"),
        ("stats", "STATS"),
        ("clubs", "CLUBS"),
        ("history", "HISTORY"),
    ),
    "phantom-cup": (
        ("overview", "OVERVIEW"),
        ("fixtures", "FIXTURES"),
        ("bracket", "BRACKET"),
        ("stats", "STATS"),
        ("history", "HISTORY"),
    ),
}

COMPETITIONS = {
    "premier-league": "Premier League",
    "championship": "Championship",
    "league-one": "League One",
    "cups": "UFL Cups",
    "phantom-cup": "UFL Phantom Cup",
    "champions-league": "UFL Champions League",
    "europa-league": "UFL Europa League",
    "conference-league": "UFL Conference League",
}

LIVE_COMPETITION_SLUGS = {
    "premier-league": "PL",
    "championship": "CH",
    "league-one": "L1",
}


def live_competition_choices():
    return [
        {
            "slug": slug,
            "label": COMPETITIONS[slug],
            "short": short,
        }
        for slug, short in LIVE_COMPETITION_SLUGS.items()
        if slug in COMPETITIONS
    ]


def _item_url(item):
    if item.get("heading"):
        return ""
    if item.get("href"):
        return item["href"]
    kwargs = item.get("url_kwargs") or None
    try:
        return reverse(item["url_name"], kwargs=kwargs)
    except NoReverseMatch:
        return "#"


def _item_is_current(item, url_name, kwargs):
    if item.get("heading") or item.get("href"):
        return False
    if item.get("url_name") != url_name:
        return False
    expected = item.get("url_kwargs") or {}
    if not expected:
        return True
    return all(kwargs.get(key) == value for key, value in expected.items())


def _build_menus(source, url_name, kwargs, is_control, extra_by_id=None):
    extra_by_id = extra_by_id or {}
    menus = []
    for menu in source:
        if menu.get("control_only") and not is_control:
            continue
        items = []
        for item in menu["items"]:
            if item.get("control_only") and not is_control:
                continue
            items.append(
                {
                    "label": item["label"],
                    "url": _item_url(item),
                    "heading": bool(item.get("heading")),
                    "divider": bool(item.get("divider")),
                    "style": item.get("style") or "",
                    "badge": item.get("badge") or "",
                    "badge_class": item.get("badge_class") or "",
                    "is_current": _item_is_current(item, url_name, kwargs),
                }
            )
        for extra in extra_by_id.get(menu["id"], ()):
            items.append(extra)
        slugs = menu.get("current_slugs")
        menu_current = url_name in menu["current"]
        if menu_current and slugs and kwargs.get("slug"):
            menu_current = kwargs.get("slug") in slugs
        menus.append(
            {
                "id": menu["id"],
                "label": menu["label"],
                "is_current": menu_current,
                "badge": "",
                "items": items,
            }
        )
    return menus


def uses_signed_in_nav(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) in (User.OWNER, User.ADMIN):
        return True
    return approved_manager(user) is not None


def nav_dropdowns_for_request(request):
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", "") or ""
    kwargs = getattr(match, "kwargs", None) or {}
    user = getattr(request, "user", None)
    is_control = bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "role", None) in ("OWNER", "ADMIN")
    )
    if uses_signed_in_nav(user):
        menus = _build_menus(SIGNED_IN_NAV_DROPDOWNS, url_name, kwargs, is_control)
        from mgl.transfer_requests import incoming_offer_count_for_user

        count = incoming_offer_count_for_user(user)
        if count:
            try:
                requests_url = reverse("transfer_requests")
            except NoReverseMatch:
                requests_url = ""
            for menu in menus:
                if menu["id"] != "market":
                    continue
                menu["badge"] = str(count)
                for item in menu["items"]:
                    if item["url"] == requests_url:
                        item["badge"] = str(count)
                        item["badge_class"] = "is-count"
        return menus
    return _build_menus(NAV_DROPDOWNS, url_name, kwargs, is_control)
