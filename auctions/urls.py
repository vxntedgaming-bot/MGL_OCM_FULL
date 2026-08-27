from django.urls import path

from . import views


urlpatterns = [
    path(
        "",
        views.live_auctions,
        name="live_auctions",
    ),
    path(
        "<int:auction_id>/bid/",
        views.place_bid,
        name="place_bid",
    ),
]
