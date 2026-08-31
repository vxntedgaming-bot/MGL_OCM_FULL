from django.urls import include, path

from mgl.market_views import job_centre, league_stats_page, leagues_page, stats_page, transfer_market
from mgl.site_views import (
    answer_press,
    club_page,
    clubs_index,
    live_activity,
    news_centre,
    pressroom,
)
from mgl.views import (
    compare_players,
    competition_page,
    historical_tables,
    home,
    manager_search,
    scouting,
    transfer_history,
)


urlpatterns = [
    path("", home, name="home"),
    path("leagues/", leagues_page, name="leagues_page"),
    path("leagues/<slug:slug>/", competition_page, name="competition_page"),
    path("clubs/", clubs_index, name="clubs_index"),
    path("clubs/<str:slug>/", club_page, name="club_page"),
    path("news/", news_centre, name="news_centre"),
    path("news/activity/", live_activity, name="live_activity"),
    path("news/pressroom/", pressroom, name="pressroom"),
    path("news/pressroom/<int:press_id>/answer/", answer_press, name="answer_press"),
    path("stats/", stats_page, name="stats_page"),
    path("stats/history/", historical_tables, name="historical_tables"),
    path("stats/compare/", compare_players, name="compare_players"),
    path("stats/managers/", manager_search, name="manager_search"),
    path("stats/<slug:slug>/", league_stats_page, name="league_stats"),
    path("jobs/", job_centre, name="job_centre"),
    path("market/", transfer_market, name="transfer_market"),
    path("market/transfers/", transfer_history, name="transfer_history"),
    path("transfers/", transfer_history, name="public_transfers"),
    path("market/scouting/", scouting, name="scouting"),
    path("mgl/", include("mgl.urls")),
]
