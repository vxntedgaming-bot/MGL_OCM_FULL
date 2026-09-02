from django.urls import include, path
from django.views.generic import RedirectView

from mgl.market_views import job_centre, league_stats_page, leagues_page, stats_page, transfer_market
from mgl.site_views import (
    answer_press,
    club_page,
    clubs_index,
    live_activity,
    news_centre,
    pressroom,
    ufl_rules,
)
from mgl.views import (
    choose_recruitment_player,
    compare_players,
    competition_page,
    historical_tables,
    hall_of_fame,
    home,
    manager_search,
    manager_public_profile,
    open_recruitment_pack,
    public_completed_transfers,
    recruitment_drive,
    scouting,
    transfer_history,
    youth_academy,
)


urlpatterns = [
    path("", home, name="home"),
    path("leagues/", leagues_page, name="leagues_page"),
    path(
        "leagues/all/",
        RedirectView.as_view(pattern_name="leagues_page", permanent=False),
        name="leagues_all",
    ),
    path("leagues/<slug:slug>/", competition_page, name="competition_page"),
    path(
        "cups/",
        RedirectView.as_view(url="/leagues/cups/", permanent=False),
        name="cups_hub",
    ),
    path(
        "cups/<slug:slug>/",
        RedirectView.as_view(url="/leagues/%(slug)s/", permanent=False),
        name="cups_detail",
    ),
    path("clubs/", clubs_index, name="clubs_index"),
    path("clubs/<str:slug>/", club_page, name="club_page"),
    path(
        "teams/<str:slug>/",
        RedirectView.as_view(pattern_name="club_page", permanent=False),
        name="public_team_alias",
    ),
    path(
        "players/<int:player_id>/",
        RedirectView.as_view(pattern_name="player_profile", permanent=False),
        name="public_player_alias",
    ),
    path("news/", news_centre, name="news_centre"),
    path("news/activity/", live_activity, name="live_activity"),
    path("news/pressroom/", pressroom, name="pressroom"),
    path("news/pressroom/<int:press_id>/answer/", answer_press, name="answer_press"),
    path("stats/", stats_page, name="stats_page"),
    path("stats/history/", historical_tables, name="historical_tables"),
    path("history/", hall_of_fame, name="hall_of_fame"),
    path("managers/<str:username>/", manager_public_profile, name="manager_public_profile"),
    path("stats/compare/", compare_players, name="compare_players"),
    path("stats/managers/", manager_search, name="manager_search"),
    path("stats/<slug:slug>/", league_stats_page, name="league_stats"),
    path("jobs/", job_centre, name="job_centre"),
    path("job-offers/", job_centre, name="job_offers"),
    path("job-centre/", RedirectView.as_view(pattern_name="job_centre", permanent=False)),
    path("rules/", ufl_rules, name="ufl_rules"),
    path("market/", transfer_market, name="transfer_market"),
    path("market/transfers/", transfer_history, name="transfer_history"),
    path("transfers/", public_completed_transfers, name="public_transfers"),
    path("market/scouting/", scouting, name="scouting"),
    path("market/youth-academy/", youth_academy, name="youth_academy"),
    path("market/recruitment/", recruitment_drive, name="recruitment_drive"),
    path("market/recruitment/open/", open_recruitment_pack, name="open_recruitment_pack"),
    path(
        "market/recruitment/<int:opening_id>/choose/",
        choose_recruitment_player,
        name="choose_recruitment_player",
    ),
    path(
        "market/players/",
        RedirectView.as_view(pattern_name="player_database", permanent=False),
        name="market_players_alias",
    ),
    path(
        "market/free-agents/",
        RedirectView.as_view(pattern_name="free_agents", permanent=False),
        name="market_free_agents_alias",
    ),
    path(
        "market/auctions/",
        RedirectView.as_view(pattern_name="live_auctions", permanent=False),
        name="market_auctions_alias",
    ),
    path("matches/", RedirectView.as_view(pattern_name="fixture_list", permanent=False)),
    path("auctions/history/", RedirectView.as_view(url="/auctions/?tab=history", permanent=False)),
    path("mgl/", include("mgl.urls")),
]
