from django.urls import include, path

from mgl.market_views import job_centre, leagues_page, stats_page, transfer_market
from mgl.views import (
    compare_players,
    competition_page,
    head_to_head,
    historical_tables,
    home,
    manager_search,
    scouting,
    transfer_history,
    youth_academy,
)


urlpatterns = [
    path("", home, name="home"),
    path("leagues/", leagues_page, name="leagues_page"),
    path("leagues/<slug:slug>/", competition_page, name="competition_page"),
    path("stats/", stats_page, name="stats_page"),
    path("stats/history/", historical_tables, name="historical_tables"),
    path("stats/head-to-head/", head_to_head, name="head_to_head"),
    path("stats/compare/", compare_players, name="compare_players"),
    path("stats/managers/", manager_search, name="manager_search"),
    path("jobs/", job_centre, name="job_centre"),
    path("market/", transfer_market, name="transfer_market"),
    path("market/transfers/", transfer_history, name="transfer_history"),
    path("market/scouting/", scouting, name="scouting"),
    path("market/youth-academy/", youth_academy, name="youth_academy"),
    path("mgl/", include("mgl.urls")),
]
