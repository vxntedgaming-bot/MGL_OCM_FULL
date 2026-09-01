from django.urls import path
from django.views.generic import RedirectView
from players.fc26_faces import player_face_image
from . import views
from . import market_views as views_market
from . import control_views as views_control
from . import site_manage as views_site
from . import season_views as views_season


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
        "notifications/panel/",
        views.notification_panel,
        name="notification_panel",
    ),
    path(
        "notifications/read-all/",
        views.notification_mark_all_read,
        name="notification_mark_all_read",
    ),
    path(
        "notifications/<int:notification_id>/read/",
        views.notification_mark_read,
        name="notification_mark_read",
    ),
    path(
        "notifications/<int:notification_id>/respond/",
        views.manager_notification_respond,
        name="manager_notification_respond",
    ),
    path(
        "transfer-requests/",
        views.transfer_requests,
        name="transfer_requests",
    ),
    path(
        "transfer-requests/<int:listing_id>/respond/",
        views.respond_transfer_request,
        name="respond_transfer_request",
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
        "fixtures/<int:fixture_id>/stats/",
        views.submit_match,
        name="fixture_stats",
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
        "market/listings/<int:listing_id>/purchase/",
        views_market.purchase_listing,
        name="purchase_listing",
    ),
    path(
        "players/<int:player_id>/request-transfer/",
        views_market.request_player_transfer,
        name="request_player_transfer",
    ),
    path(
        "market/listings/<int:listing_id>/cancel/",
        views_market.cancel_player_listing,
        name="cancel_player_listing",
    ),
    path("team/sell/<int:player_id>/", views_market.sell_player, name="sell_player"),
    path("jobs/<int:team_id>/apply/", views_market.apply_for_club, name="apply_for_club"),
    path("control/", views_control.control_centre, name="control_centre"),
    path("control/pending/", views_control.control_pending, name="control_pending"),
    path("control/approvals/", views_control.control_pending, name="control_approvals"),
    path("control/scores/", views_control.control_scores, name="control_scores"),
    path("control/approvals/scores/", views_control.control_scores, name="control_approvals_scores"),
    path("control/transfers/", views_control.control_transfers, name="control_transfers"),
    path("control/approvals/transfers/", views_control.control_transfers, name="control_approvals_transfers"),
    path("control/press/", views_control.control_press, name="control_press"),
    path("control/approvals/press/", views_control.control_press, name="control_approvals_press"),
    path("control/managers/", views_control.control_managers, name="control_managers"),
    path("control/approvals/managers/", views_control.control_managers, name="control_approvals_managers"),
    path("control/awards/weekly/", views_control.control_weekly_awards, name="control_weekly_awards"),
    path("control/history/weekly-rewards/", views_control.control_weekly_awards, name="control_history_weekly"),
    path("control/awards/monthly/", views_control.control_monthly_awards, name="control_monthly_awards"),
    path("control/history/monthly-rewards/", views_control.control_monthly_awards, name="control_history_monthly"),
    path("control/tokens/", views_control.control_tokens, name="control_tokens"),
    path("control/scouting/", views_control.control_scouting, name="control_scouting"),
    path("control/management/scouting/", views_control.control_scouting, name="control_management_scouting"),
    path("control/auctions/", views_control.control_auctions, name="control_auctions"),
    path("control/management/auctions/", views_control.control_auctions, name="control_management_auctions"),
    path("control/clubs/", views_control.control_clubs, name="control_clubs"),
    path("control/management/clubs/", views_control.control_clubs, name="control_management_clubs"),
    path("control/notifications/", views_control.control_notifications, name="control_notifications"),
    path("control/logs/", views_control.control_logs, name="control_logs"),
    path("control/season/history/", views_control.control_season_history, name="control_season_history"),
    path("control/season/controls/", views_control.control_season_controls, name="control_season_controls"),
    path(
        "control/season/starting-squads/",
        views_control.control_starting_squads,
        name="control_starting_squads",
    ),
    path("control/league/", views_control.control_league, name="control_league"),
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
        "control/site/seasons/",
        views_season.season_management,
        name="season_management",
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
        "control/listings/<int:listing_id>/changes/",
        views_market.control_request_listing_changes,
        name="control_request_listing_changes",
    ),
    path(
        "control/scouting/exceptions/<int:exception_id>/resolve/",
        views_market.control_resolve_scout_exception,
        name="control_resolve_scout_exception",
    ),
    path(
        "control/results/<int:submission_id>/approve/",
        views_market.control_approve_result,
        name="control_approve_result",
    ),
    path(
        "control/results/<int:submission_id>/reject/",
        views_market.control_reject_result,
        name="control_reject_result",
    ),
    path(
        "control/results/<int:submission_id>/rollback/",
        views_market.control_rollback_result,
        name="control_rollback_result",
    ),
    path(
        "control/awards/weekly/<int:batch_id>/approve/",
        views_market.control_approve_weekly_awards,
        name="control_approve_weekly_awards",
    ),
    path(
        "control/awards/weekly/<int:batch_id>/reject/",
        views_market.control_reject_weekly_awards,
        name="control_reject_weekly_awards",
    ),
    path(
        "control/awards/weekly/<int:batch_id>/recalculate/",
        views_market.control_recalculate_weekly_awards,
        name="control_recalculate_weekly_awards",
    ),
    path(
        "control/awards/monthly/<int:batch_id>/approve/",
        views_market.control_approve_monthly_awards,
        name="control_approve_monthly_awards",
    ),
    path(
        "control/tokens/adjust/",
        views_market.control_adjust_tokens,
        name="control_adjust_tokens",
    ),
    path(
        "control/auctions/<int:auction_id>/close/",
        views_market.control_close_auction,
        name="control_close_auction",
    ),
    path(
        "control/auctions/<int:auction_id>/cancel/",
        views_market.control_cancel_auction,
        name="control_cancel_auction",
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
    path(
        "control/press/<int:press_id>/approve/",
        views_market.control_approve_press,
        name="control_approve_press",
    ),
    path(
        "control/press/<int:press_id>/reject/",
        views_market.control_reject_press,
        name="control_reject_press",
    ),
    path(
        "control/releases/<int:release_id>/approve/",
        views_market.control_approve_release,
        name="control_approve_release",
    ),
    path(
        "control/releases/<int:release_id>/reject/",
        views_market.control_reject_release,
        name="control_reject_release",
    ),
]
