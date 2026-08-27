from django.urls import path
from . import views
from . import market_views as views_market


urlpatterns = [
    path(
        "",
        views.mgl_index,
        name="mgl_index",
    ),

    path(
        "hub/",
        views.manager_hub,
        name="manager_hub",
    ),

    # --------------------------------------------------------
    # MANAGER
    # --------------------------------------------------------

    path(
        "team/",
        views.team_management,
        name="team_management",
    ),

    path(
        "team/release/<int:player_id>/",
        views.release_my_player,
        name="release_my_player",
    ),

    path(
        "players/",
        views.player_database,
        name="player_database",
    ),

    path(
        "players/<int:player_id>/",
        views.player_profile,
        name="player_profile",
    ),

    path(
        "free-agents/",
        views.free_agents,
        name="free_agents",
    ),

    path(
        "profile/",
        views.manager_profile,
        name="manager_profile",
    ),

    path(
        "rewards/",
        views.rewards,
        name="manager_rewards",
    ),

    # --------------------------------------------------------
    # FIXTURES
    # --------------------------------------------------------

    path(
        "fixtures/",
        views.fixture_list,
        name="fixture_list",
    ),

    path(
        "fixtures/<int:fixture_id>/submit/",
        views.submit_match,
        name="submit_match",
    ),

    path(
        "fixtures/<int:fixture_id>/press/",
        views.press_conference,
        name="press_conference",
    ),

    # --------------------------------------------------------
    # OWNER / ADMIN CLUB MANAGEMENT
    # --------------------------------------------------------

    path(
        "admin/clubs/",
        views.club_management_admin,
        name="club_management_admin",
    ),

    path(
        "admin/clubs/<int:team_id>/edit/",
        views.edit_club_admin,
        name="edit_club_admin",
    ),

    path(
        "admin/clubs/<int:team_id>/manager/",
        views.change_club_manager,
        name="change_club_manager",
    ),

    path(
        "admin/clubs/<int:team_id>/remove-manager/",
        views.remove_club_manager,
        name="remove_club_manager",
    ),

    path(
        "admin/clubs/<int:team_id>/squad/",
        views.club_squad_admin,
        name="club_squad_admin",
    ),

    path("market/listings/<int:listing_id>/buy/", views_market.buy_player, name="buy_player"),
    path(
        "market/listings/<int:listing_id>/cancel/",
        views_market.cancel_player_listing,
        name="cancel_player_listing",
    ),
    path("team/sell/<int:player_id>/", views_market.sell_player, name="sell_player"),
    path("jobs/<int:team_id>/apply/", views_market.apply_for_club, name="apply_for_club"),
    path("control/", views_market.control_centre, name="control_centre"),
    path(
        "control/managers/<int:application_id>/approve/",
        views_market.control_approve_manager,
        name="control_approve_manager",
    ),
    path(
        "control/managers/<int:application_id>/reject/",
        views_market.control_reject_manager,
        name="control_reject_manager",
    ),
    path(
        "control/listings/<int:listing_id>/approve/",
        views_market.control_approve_listing,
        name="control_approve_listing",
    ),
    path(
        "control/listings/<int:listing_id>/reject/",
        views_market.control_reject_listing,
        name="control_reject_listing",
    ),
    path(
        "control/auctions/<int:auction_id>/close/",
        views_market.control_close_auction,
        name="control_close_auction",
    ),
    path(
        "control/jobs/<int:application_id>/approve/",
        views_market.control_approve_job,
        name="control_approve_job",
    ),
    path(
        "control/jobs/<int:application_id>/reject/",
        views_market.control_reject_job,
        name="control_reject_job",
    ),
]
