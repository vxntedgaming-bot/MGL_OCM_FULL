from django.urls import include, path

from mgl.market_views import job_centre, leagues_page, stats_page, transfer_market
from mgl.views import home


urlpatterns = [
    path("", home, name="home"),
    path("leagues/", leagues_page, name="leagues_page"),
    path("stats/", stats_page, name="stats_page"),
    path("jobs/", job_centre, name="job_centre"),
    path("market/", transfer_market, name="transfer_market"),
    path("mgl/", include("mgl.urls")),
]
