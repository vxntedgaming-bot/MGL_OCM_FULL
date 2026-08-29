from django.urls import path
from django.views.generic import RedirectView
from players.fc26_faces import player_face_image
from . import views
from . import market_views as views_market
from . import site_manage as views_site


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
    path(
        "notifications/",
        views.manager_notifications,
        name="manager_notifications",
    ),
    path(
        "live-activity/",
        RedirectView.as_view(pattern_name="live_activity", permanent=False),
        name="live_activity_alias",
    ),
    path(
        "pressroom/",
        RedirectView.as_view(pattern_name="pressroom", permanent=False),
        name="pressroom_alias",
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
        "team/auction/<int:player_id>/",
        views.list_player_for_auction,
        name="list_player_for_auction",
    ),
    path(
        "free-agents/<int:player_id>/auction/",
        views.auction_free_agent,
        name="auction_free_agent",
    ),

    path(
        "players/",
        views.player_database,
        name="player_database",
    ),

    path(
        "players/<int:player_id>/face/",
        player_face_image,
        name="player_face_image",
    ),

    path(
        "players/<int:player_id>/",
        views.player_profile,
        name="player_profile",
    ),

    path(
        "unassigned/",
        views.unassigned_players_page,
        name="unassigned_players",
    ),
    path(
        "free-agents/",
        views.free_agents,
        name="free_agents",
    ),
    path(
        "free-agents/<int:player_id>/sign/",
        views.sign_free_agent_view,
        name="sign_free_agent",
    ),

    path(
        "profile/",
        views.manager_profile,
        name="manager_profile",
    ),
    path(
        "profile/resign/",
        views.resign_from_club,
        name="resign_from_club",
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
        "control/site/",
        views_site.site_management,
        name="site_management",
    ),
    path(
        "control/site/teams/",
        views_site.site_management_teams,
        name="site_management_teams",
    ),
    path(
        "control/site/teams/<int:team_id>/",
        views_site.site_management_team_edit,
        name="site_management_team_edit",
    ),
    path(
        "control/site/content/",
        views_site.site_management_content,
        name="site_management_content",
    ),
    path(
        "control/site/content/<slug:section>/",
        views_site.site_management_content_section,
        name="site_management_content_section",
    ),
    path(
        "control/site/settings/",
        views_site.site_management_settings,
        name="site_management_settings",
    ),
    path(
        "control/site/leagues/",
        views_site.site_management_leagues,
        name="site_management_leagues",
    ),
    path(
        "control/site/leagues/<int:league_id>/",
        views_site.site_management_league_edit,
        name="site_management_league_edit",
    ),
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
