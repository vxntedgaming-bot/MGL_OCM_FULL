"""Header dropdown definitions for the MGL nav."""

from django.urls import NoReverseMatch, reverse


NAV_DROPDOWNS = (
    {
        "id": "my-team",
        "label": "MY TEAM",
        "current": {"team_management", "fixture_list", "submit_match", "press_conference"},
        "items": (
            {"label": "TEAM MANAGEMENT", "url_name": "team_management"},
            {"label": "FIXTURES", "url_name": "fixture_list", "divider": True},
        ),
    },
    {
        "id": "market",
        "label": "MARKET",
        "current": {
            "transfer_history",
            "transfer_market",
            "free_agents",
            "job_centre",
            "scouting",
            "youth_academy",
            "live_auctions",
            "place_bid",
            "player_database",
            "player_profile",
        },
        "items": (
            {"label": "TRANSFERS", "url_name": "transfer_history"},
            {"label": "TRANSFER MARKET", "url_name": "transfer_market", "divider": True},
            {"label": "FREE AGENTS", "url_name": "free_agents", "divider": True},
            {"label": "RECRUITMENT DRIVE", "url_name": "job_centre", "divider": True},
            {"label": "SCOUTING", "url_name": "scouting", "divider": True},
            {
                "label": "YOUTH ACADEMY",
                "url_name": "youth_academy",
                "divider": True,
                "badge": "NEW",
            },
            {"label": "AUCTIONS", "url_name": "live_auctions", "divider": True},
            {"label": "ALL PLAYERS", "url_name": "player_database", "divider": True},
        ),
    },
    {
        "id": "leagues",
        "label": "LEAGUES",
        "current": {"leagues_page", "competition_page"},
        "items": (
            {"label": "ALL LEAGUES", "url_name": "leagues_page"},
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
                "label": "MLS",
                "url_name": "competition_page",
                "url_kwargs": {"slug": "mls"},
                "style": "sub",
            },
            {
                "label": "CUPS",
                "url_name": "competition_page",
                "url_kwargs": {"slug": "cups"},
                "divider": True,
            },
            {
                "label": "WAITING ROOM LEAGUE",
                "url_name": "competition_page",
                "url_kwargs": {"slug": "waiting-room"},
                "divider": True,
            },
        ),
    },
    {
        "id": "stats",
        "label": "STATS & HISTORY",
        "current": {
            "historical_tables",
            "stats_page",
            "head_to_head",
            "compare_players",
            "manager_search",
        },
        "items": (
            {"label": "HISTORICAL LEAGUE TABLES", "url_name": "historical_tables"},
            {"label": "STATS HUB", "url_name": "stats_page", "divider": True},
            {"label": "HEAD TO HEAD", "url_name": "head_to_head", "divider": True},
            {"label": "COMPARE", "url_name": "compare_players"},
            {"label": "MANAGER SEARCH", "url_name": "manager_search", "divider": True},
        ),
    },
)

COMPETITIONS = {
    "premier-league": "Premier League",
    "championship": "Championship",
    "league-one": "League One",
    "mls": "MLS",
    "cups": "Cups",
    "waiting-room": "Waiting Room League",
}


def _item_url(item):
    kwargs = item.get("url_kwargs") or None
    try:
        return reverse(item["url_name"], kwargs=kwargs)
    except NoReverseMatch:
        return "#"


def _item_is_current(item, url_name, kwargs):
    if item.get("url_name") != url_name:
        return False
    expected = item.get("url_kwargs") or {}
    if not expected:
        return True
    return all(kwargs.get(key) == value for key, value in expected.items())


def nav_dropdowns_for_request(request):
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", "") or ""
    kwargs = getattr(match, "kwargs", None) or {}
    menus = []
    for menu in NAV_DROPDOWNS:
        items = []
        for item in menu["items"]:
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
        menus.append(
            {
                "id": menu["id"],
                "label": menu["label"],
                "is_current": url_name in menu["current"],
                "items": items,
            }
        )
    return menus
