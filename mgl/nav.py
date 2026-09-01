"""Header dropdown definitions for the UFL nav."""

from django.urls import NoReverseMatch, reverse

from accounts.models import User
from mgl.permissions import approved_manager


PUBLIC_LEAGUE_MENU = {
    "id": "leagues",
    "label": "LEAGUE",
    "current": {
        "leagues_page",
        "competition_page",
        "fixture_list",
        "stats_page",
        "league_stats",
        "live_activity",
    },
    "items": (
        {"label": "League Overview", "url_name": "leagues_page"},
        {"label": "League Table", "url_name": "leagues_page", "divider": True},
        {"label": "Fixtures", "url_name": "fixture_list", "divider": True},
        {"label": "Results", "url_name": "fixture_list", "divider": True},
        {
            "label": "Statistics",
            "url_name": "stats_page",
            "divider": True,
        },
        {
            "label": "Player Statistics",
            "url_name": "league_stats",
            "url_kwargs": {"slug": "premier-league"},
            "style": "sub",
        },
        {
            "label": "Club Statistics",
            "url_name": "league_stats",
            "url_kwargs": {"slug": "championship"},
            "style": "sub",
        },
        {"label": "League Activity", "url_name": "live_activity", "divider": True},
        {
            "label": "Premier League",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "premier-league"},
            "style": "sub",
            "divider": True,
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
            "label": "Cups (Coming soon)",
            "url_name": "competition_page",
            "url_kwargs": {"slug": "cups"},
            "divider": True,
        },
    ),
}

PUBLIC_CLUBS_MENU = {
    "id": "clubs",
    "label": "CLUBS",
    "current": {
        "clubs_index",
        "club_page",
        "manager_search",
        "historical_tables",
    },
    "items": (
        {"label": "Clubs", "url_name": "clubs_index"},
        {"label": "Club Profiles", "url_name": "clubs_index", "divider": True},
        {"label": "Managers", "url_name": "manager_search", "divider": True},
        {"label": "Manager History", "url_name": "historical_tables", "divider": True},
    ),
}

PUBLIC_PLAYERS_MENU = {
    "id": "players",
    "label": "PLAYERS",
    "current": {
        "player_database",
        "player_profile",
        "free_agents",
        "unassigned_players",
        "transfer_history",
        "public_transfers",
    },
    "items": (
        {"label": "FC26 Player Database", "url_name": "player_database"},
        {"label": "Player Search", "url_name": "player_database", "divider": True},
        {"label": "Free Agents", "url_name": "free_agents", "divider": True},
        {"label": "Transfer History", "url_name": "transfer_history", "divider": True},
        {
            "label": "Auction History",
            "url_name": "live_auctions",
            "divider": True,
        },
        {
            "label": "Unassigned Players",
            "url_name": "unassigned_players",
            "divider": True,
            "control_only": True,
        },
    ),
}

PUBLIC_TRANSFERS_MENU = {
    "id": "transfers",
    "label": "TRANSFERS",
    "current": {
        "transfer_market",
        "transfer_history",
        "public_transfers",
        "news_centre",
        "transfer_requests",
        "respond_transfer_request",
        "request_player_transfer",
        "purchase_listing",
    },
    "items": (
        {"label": "Transfer Market", "url_name": "transfer_market"},
        {"label": "Transfer News", "url_name": "news_centre", "divider": True},
        {"label": "Completed Transfers", "url_name": "public_transfers", "divider": True},
        {"label": "Negotiations", "url_name": "transfer_requests", "divider": True},
    ),
}

PUBLIC_NEWS_MENU = {
    "id": "news",
    "label": "NEWS",
    "current": {
        "news_centre",
        "live_activity",
        "pressroom",
        "answer_press",
    },
    "items": (
        {"label": "News", "url_name": "news_centre"},
        {"label": "Pressroom", "url_name": "pressroom", "divider": True},
        {"label": "Live Activity", "url_name": "live_activity", "divider": True},
    ),
}

CAREER_MENU = {
    "id": "career",
    "label": "MY CAREER",
    "current": {
        "manager_hub",
        "team_management",
        "club_page",
        "transfer_market",
        "transfer_requests",
        "respond_transfer_request",
        "live_auctions",
        "place_bid",
        "scouting",
        "fixture_list",
        "submit_match",
        "fixture_stats",
        "press_conference",
        "pressroom",
        "answer_press",
        "manager_rewards",
        "manager_notifications",
        "manager_notification_respond",
        "manager_profile",
        "historical_tables",
    },
    "items": (
        {"label": "Dashboard", "url_name": "manager_hub"},
        {"label": "My Squad", "url_name": "team_management", "divider": True},
        {"label": "Transfers", "url_name": "transfer_market", "divider": True},
        {"label": "Negotiations", "url_name": "transfer_requests", "divider": True},
        {"label": "My Auctions", "url_name": "live_auctions", "divider": True},
        {"label": "Scouting", "url_name": "scouting", "divider": True},
        {"label": "Matches", "url_name": "fixture_list", "divider": True},
        {"label": "Press", "url_name": "pressroom", "divider": True},
        {"label": "Tokens", "url_name": "manager_rewards", "divider": True},
        {"label": "Notifications", "url_name": "manager_notifications", "divider": True},
        {"label": "Career History", "url_name": "manager_profile", "divider": True},
    ),
}

# Public visitors — Career Mode destinations stay out of the top bar.
NAV_DROPDOWNS = (
    PUBLIC_LEAGUE_MENU,
    PUBLIC_CLUBS_MENU,
    PUBLIC_PLAYERS_MENU,
    PUBLIC_TRANSFERS_MENU,
    PUBLIC_NEWS_MENU,
)

# Approved managers / Control — public IA plus My Career.
SIGNED_IN_NAV_DROPDOWNS = (
    CAREER_MENU,
    PUBLIC_LEAGUE_MENU,
    PUBLIC_CLUBS_MENU,
    PUBLIC_PLAYERS_MENU,
    PUBLIC_TRANSFERS_MENU,
    PUBLIC_NEWS_MENU,
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


def live_competition_choices():
    """Existing live divisions only. Used by Tables and Statistics selectors."""
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
                    "badge_class": item.get("badge_class") or "",
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
                if menu["id"] not in {"career", "transfers"}:
                    continue
                if menu["id"] == "career":
                    menu["badge"] = str(count)
                for item in menu["items"]:
                    if item["url"] == requests_url:
                        item["badge"] = str(count)
                        item["badge_class"] = "is-count"
        return menus
    return _build_menus(NAV_DROPDOWNS, url_name, kwargs, is_control)
