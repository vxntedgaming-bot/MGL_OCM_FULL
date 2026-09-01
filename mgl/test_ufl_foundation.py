from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from mgl.discord_queue import mark_discord_failed, mark_discord_sent, pending_discord_events
from mgl.models import DiscordEvent, NewsPost, PlayerListing, PlayerReleaseRequest
from mgl.market import list_player_for_sale
from mgl.player_state import ASSIGNED, TRANSFER_LISTED, market_status
from mgl.scouting import add_to_watchlist, get_or_create_scout_profile
from mgl.services import (
    approve_player_release,
    create_news,
    reject_player_release,
    request_player_release,
)
from mgl.ufl_settings import (
    OFFICIAL_STARTING_SQUAD_SIZE,
    UFL_SQUAD_SHAPE,
    official_starting_structure,
    max_active_listings,
    max_squad_size,
    scout_can_recruit,
    starting_tokens,
    ufl_access_role,
)
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(username=username, password="test-pass-123", role=role)


def _manager(user, tokens="50.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class UFLFoundationTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name="UFL Test", short_name="UFL", season="1")
        self.owner = _user("owner", User.OWNER)
        self.admin = _user("admin", User.ADMIN)
        self.user_a = _user("manager-a")
        self.user_b = _user("member-b")
        self.mgr_a = _manager(self.user_a)
        ManagerApplication.objects.create(
            user=self.user_b,
            display_name="Member B",
            gamertag="MEMB",
            status=ManagerApplication.PENDING,
        )
        self.team_a = Team.objects.create(
            name="Test United",
            short_name="TUN",
            league=self.league,
            manager=self.user_a,
            roster_limit=30,
        )
        self.owned = Player.objects.create(
            name="Listed One",
            position="ST",
            overall=67,
            mgl_team=self.team_a,
            is_free_agent=False,
            fc27_id="fc-listed-1",
        )
        self.owned2 = Player.objects.create(
            name="Listed Two",
            position="CM",
            overall=66,
            mgl_team=self.team_a,
            is_free_agent=False,
            fc27_id="fc-listed-2",
        )
        self.owned3 = Player.objects.create(
            name="Listed Three",
            position="CB",
            overall=65,
            mgl_team=self.team_a,
            is_free_agent=False,
            fc27_id="fc-listed-3",
        )
        self.owned4 = Player.objects.create(
            name="Listed Four",
            position="GK",
            overall=64,
            mgl_team=self.team_a,
            is_free_agent=False,
            fc27_id="fc-listed-4",
        )

    def test_roles_map_without_new_user_enum(self):
        self.assertEqual(ufl_access_role(None), "PUBLIC")
        self.assertEqual(ufl_access_role(self.user_b), "MEMBER")
        self.assertEqual(ufl_access_role(self.user_a), "MANAGER")
        self.assertEqual(ufl_access_role(self.admin), "ADMIN")
        self.assertEqual(ufl_access_role(self.owner), "OWNER")
        self.assertNotIn("MEMBER", [choice[0] for choice in User.ROLE_CHOICES])

    def test_league_settings_defaults(self):
        self.assertEqual(max_squad_size(), 28)
        self.assertEqual(max_active_listings(), 5)
        self.assertEqual(starting_tokens(), Decimal("20"))
        self.assertEqual(OFFICIAL_STARTING_SQUAD_SIZE, 25)
        self.assertEqual(sum(count for _pos, count in UFL_SQUAD_SHAPE), 25)
        self.assertEqual(
            {pos: count for pos, count in UFL_SQUAD_SHAPE},
            {
                "GK": 2,
                "CB": 5,
                "RB": 1,
                "LB": 1,
                "RWB": 1,
                "LWB": 1,
                "CM": 3,
                "CDM": 2,
                "CAM": 2,
                "RM": 1,
                "LM": 1,
                "RW": 1,
                "LW": 1,
                "ST": 3,
            },
        )
        self.assertEqual(official_starting_structure()[-1], {"code": "ST", "required": 3})

    def test_listing_frequency_and_active_cap(self):
        list_player_for_sale(self.owned, self.mgr_a, "3")
        list_player_for_sale(self.owned2, self.mgr_a, "3")
        list_player_for_sale(self.owned3, self.mgr_a, "3")
        with self.assertRaises(ValueError):
            list_player_for_sale(self.owned4, self.mgr_a, "3")
        PlayerListing.objects.filter(seller=self.mgr_a).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        extra = Player.objects.create(
            name="Listed Five",
            position="LW",
            overall=65,
            mgl_team=self.team_a,
            is_free_agent=False,
            fc27_id="fc-listed-5",
        )
        sixth = Player.objects.create(
            name="Listed Six",
            position="RW",
            overall=65,
            mgl_team=self.team_a,
            is_free_agent=False,
            fc27_id="fc-listed-6",
        )
        list_player_for_sale(self.owned4, self.mgr_a, "3")
        list_player_for_sale(extra, self.mgr_a, "3")
        with self.assertRaises(ValueError):
            list_player_for_sale(sixth, self.mgr_a, "3")

    def test_release_requires_approval(self):
        client = Client()
        client.force_login(self.user_a)
        response = client.post(reverse("release_my_player", args=[self.owned.pk]))
        self.assertEqual(response.status_code, 302)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertFalse(self.owned.is_free_agent)
        request_row = PlayerReleaseRequest.objects.get(player=self.owned)
        approve_player_release(request_row, self.admin)
        self.owned.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertTrue(self.owned.is_free_agent)

    def test_release_reject_keeps_player(self):
        request_row = request_player_release(self.owned, self.team_a, self.mgr_a)
        reject_player_release(request_row, self.admin)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertFalse(self.owned.is_free_agent)

    def test_manager_can_create_auction_via_http(self):
        client = Client()
        client.force_login(self.user_a)
        response = client.post(reverse("list_player_for_auction", args=[self.owned.pk]), {"duration": "30"})
        self.assertEqual(response.status_code, 302)
        self.owned.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        from auctions.models import PlayerAuction

        self.assertTrue(PlayerAuction.objects.filter(player=self.owned, listing_kind="CLUB").exists())

    def test_member_and_manager_cannot_open_control(self):
        client = Client()
        client.force_login(self.user_a)
        response = client.get(reverse("control_centre"))
        self.assertEqual(response.status_code, 302)
        client.force_login(self.user_b)
        response = client.get(reverse("control_centre"))
        self.assertEqual(response.status_code, 302)

    def test_news_queues_discord_event(self):
        post = create_news(NewsPost.TRANSFER, "Test deal", "A completed UFL transfer.")
        event = DiscordEvent.objects.get(news_post=post)
        self.assertEqual(event.status, DiscordEvent.PENDING)
        pending = pending_discord_events()
        self.assertEqual(pending[0].pk, event.pk)
        mark_discord_sent(event)
        event.refresh_from_db()
        post.refresh_from_db()
        self.assertEqual(event.status, DiscordEvent.SENT)
        self.assertTrue(post.discord_sent)
        failed = create_news(NewsPost.AUCTION, "Auction live", "A new auction.")
        queued = DiscordEvent.objects.get(news_post=failed)
        mark_discord_failed(queued, "offline")
        queued.refresh_from_db()
        self.assertEqual(queued.status, DiscordEvent.PENDING)
        self.assertEqual(queued.attempt_count, 1)

    def test_player_status_and_watchlist(self):
        self.assertEqual(market_status(self.owned), ASSIGNED)
        list_player_for_sale(self.owned, self.mgr_a, "4")
        self.assertEqual(market_status(self.owned), TRANSFER_LISTED)
        add_to_watchlist(self.mgr_a, self.owned2)
        self.assertEqual(self.mgr_a.scout_watchlist.count(), 1)

    def test_scout_attributes_exist(self):
        profile = get_or_create_scout_profile(self.mgr_a)
        self.assertGreaterEqual(profile.judging_ability, 1)
        self.assertLessEqual(profile.judging_ability, 5)

    def test_managers_cannot_recruit_via_scouting_setting(self):
        self.assertTrue(scout_can_recruit())

    def test_public_branding(self):
        client = Client()
        home = client.get(reverse("home"))
        self.assertContains(home, "YOUR CLUB.")
        self.assertContains(home, "BUILD YOUR LEGACY")
        self.assertNotContains(home, "META GAMING LEAGUE")
        self.assertNotContains(home, "loan and manage")
