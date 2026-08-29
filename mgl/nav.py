"""Header dropdown definitions for the MGL nav."""

from django.urls import NoReverseMatch, reverse

from mgl.club_urls import club_page_url
from mgl.market import club_for_user


NAV_DROPDOWNS = (
    {
        "id": "my-team",
        "label": "MY TEAM",
        "current": {
            "team_management",
            "fixture_list",
            "submit_match",
            "press_conference",
            "manager_hub",
            "pressroom",
            "answer_press",
        },
        "items": (
            {"label": "Manager Hub", "url_name": "manager_hub"},
            {"label": "Team Management", "url_name": "team_management", "divider": True},
            {"label": "Fixtures", "url_name": "fixture_list", "divider": True},
        ),
    },
    {
        "id": "market",
        "label": "TRANSFERS",
        "current": {
            "transfer_history",
            "transfer_market",
            "free_agents",
            "unassigned_players",
            "job_centre",
            "scouting",
            "youth_academy",
            "live_auctions",
            "place_bid",
            "player_database",
            "player_profile",
            "club_page",
            "clubs_index",
        },
        "items": (
            {"label": "Transfers", "url_name": "transfer_history"},
            {"label": "Transfer Market", "url_name": "transfer_market", "divider": True},
            {"label": "Free Agents", "url_name": "free_agents", "divider": True},
            {
                "label": "Unassigned Players",
                "url_name": "unassigned_players",
                "divider": True,
                "control_only": True,
            },
            {"label": "Recruitment Drive", "url_name": "job_centre", "divider": True},
            {"label": "Scouting", "url_name": "scouting", "divider": True},
            {
                "label": "Youth Academy",
                "url_name": "youth_academy",
                "divider": True,
                "badge": "NEW",
            },
            {"label": "Auctions", "url_name": "live_auctions", "divider": True},
            {"label": "All Players", "url_name": "player_database", "divider": True},
        ),
    },
    {
        "id": "leagues",
        "label": "TABLES",
        "current": {"leagues_page", "competition_page", "clubs_index", "club_page"},
        "items": (
            {"label": "All Leagues", "url_name": "leagues_page"},
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
            {
                "label": "Cups",
                "url_name": "competition_page",
                "url_kwargs": {"slug": "cups"},
                "divider": True,
            },
        ),
    },
    {
        "id": "stats",
        "label": "STATISTICS",
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
    },
)

MANAGER_NAV_DROPDOWNS = (
    {
        "id": "my-club",
        "label": "MY CLUB",
        "current": {
            "manager_hub",
            "team_management",
            "fixture_list",
            "submit_match",
            "leagues_page",
            "competition_page",
            "club_page",
            "manager_profile",
        },
        "items": (
            {"label": "Manager Hub", "url_name": "manager_hub"},
            {"label": "My Team", "url_name": "team_management", "divider": True},
            {"label": "Fixtures", "url_name": "fixture_list", "divider": True},
            {"label": "Tables", "url_name": "leagues_page", "divider": True},
        ),
    },
    {
        "id": "transfers",
        "label": "TRANSFERS",
        "current": {
            "transfer_history",
            "transfer_market",
            "free_agents",
            "team_management",
        },
        "items": (
            {"label": "Propose Transfer", "url_name": "team_management"},
            {"label": "My Offers", "url_name": "team_management", "divider": True},
            {"label": "Transfer Market", "url_name": "transfer_market", "divider": True},
            {"label": "Free Agents", "url_name": "free_agents", "divider": True},
        ),
    },
    {
        "id": "recruitment",
        "label": "RECRUITMENT",
        "current": {
            "scouting",
            "live_auctions",
            "place_bid",
            "player_database",
            "player_profile",
            "youth_academy",
        },
        "items": (
            {"label": "Recruitment Drive", "url_name": "scouting"},
            {"label": "Auctions", "url_name": "live_auctions", "divider": True},
            {"label": "Player Database", "url_name": "player_database", "divider": True},
            {
                "label": "Academy",
                "url_name": "youth_academy",
                "divider": True,
                "badge": "NEW",
            },
        ),
    },
    {
        "id": "community",
        "label": "COMMUNITY",
        "current": {
            "head_to_head",
            "historical_tables",
            "live_activity",
            "pressroom",
            "answer_press",
            "news_centre",
        },
        "items": (
            {"label": "Head to Head", "url_name": "head_to_head"},
            {"label": "History", "url_name": "historical_tables", "divider": True},
            {"label": "Live Activity", "url_name": "live_activity", "divider": True},
            {"label": "Pressroom", "url_name": "pressroom", "divider": True},
        ),
    },
    {
        "id": "stats",
        "label": "STATISTICS",
        "current": {"stats_page", "league_stats"},
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
    },
)

COMPETITIONS = {
    "premier-league": "Premier League",
    "championship": "Championship",
    "league-one": "League One",
    "cups": "Cups",
}

LIVE_COMPETITION_SLUGS = {
    "premier-league": "PL",
    "championship": "CH",
    "league-one": "L1",
}


def _item_url(item):
    if item.get("href"):
        return item["href"]
    kwargs = item.get("url_kwargs") or None
    try:
        return reverse(item["url_name"], kwargs=kwargs)
    except NoReverseMatch:
        return "#"


def _item_is_current(item, url_name, kwargs):
    if item.get("href"):
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
        items = []
        for item in menu["items"]:
            if item.get("control_only") and not is_control:
                continue
            items.append(
                {
                    "label": item["label"],
                    "url": _item_url(item),
                    "divider": bool(item.get("divider")),
                    "style": item.get("style") or "",
                    "badge": item.get("badge") or "",
                    "is_current": _item_is_current(item, url_name, kwargs),
                }
            )
        for extra in extra_by_id.get(menu["id"], ()):
            items.append(extra)
        menus.append(
            {
                "id": menu["id"],
                "label": menu["label"],
                "is_current": url_name in menu["current"],
                "items": items,
            }
        )
    return menus


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
    team = club_for_user(user) if user is not None else None
    if team is not None:
        extra = {
            "my-club": [
                {
                    "label": "Club Profile",
                    "url": club_page_url(team),
                    "divider": True,
                    "style": "",
                    "badge": "",
                    "is_current": url_name == "club_page",
                }
            ]
        }
        return _build_menus(MANAGER_NAV_DROPDOWNS, url_name, kwargs, is_control, extra)
    return _build_menus(NAV_DROPDOWNS, url_name, kwargs, is_control)
