from django.urls import path
from . import views


urlpatterns = [
    path(
        "",
        views.home,
        name="home",
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
]
