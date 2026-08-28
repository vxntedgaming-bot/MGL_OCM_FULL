from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_super_league_1
from managers.models import ManagerApplication
from mgl.models import PlayerListing
from players.models import Player
from teams.badges import static_badge_path
from teams.models import Team


class PlayerCardAndBadgeTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_super_league_1()
        self.team = Team.objects.filter(short_name="ARS").first() or Team.objects.create(
            name="Arsenal",
            short_name="ARS",
            league=self.league,
        )
        self.gold = Player.objects.create(
            name="Gold Striker",
            position="ST",
            overall=80,
            pace=81,
            shooting=82,
            passing=70,
            dribbling=75,
            defending=40,
            physical=72,
            nationality="England",
            mgl_team=self.team,
            is_free_agent=False,
        )
        self.silver = Player.objects.create(
            name="Silver Mid",
            position="CM",
            overall=70,
            is_free_agent=True,
        )
        self.bronze = Player.objects.create(
            name="Bronze Back",
            position="CB",
            overall=60,
            is_free_agent=True,
        )
        self.user = User.objects.create_user(
            username="carduser",
            password="test-pass-123",
        )
        self.manager = ManagerApplication.objects.create(
            user=self.user,
            display_name="Card User",
            gamertag="CU1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("50.00"),
        )

    def test_official_badge_path_uses_short_name(self):
        self.assertEqual(static_badge_path(self.team), "core/img/clubs/ARS.svg")
        self.assertEqual(static_badge_path(None), "")

    def test_homepage_renders_club_badges(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "core/img/clubs/ARS.svg")
        self.assertContains(response, "Arsenal")

    def test_player_profile_uses_reusable_card_and_free_agent_copy(self):
        self.client.login(username="carduser", password="test-pass-123")
        gold = self.client.get(reverse("player_profile", args=[self.gold.id]))
        self.assertEqual(gold.status_code, 200)
        self.assertContains(gold, "mgl/cards/gold_card.png")
        self.assertContains(gold, "Arsenal")
        self.assertContains(gold, "PAC")
        self.assertContains(gold, "NO DATA YET")

        silver = self.client.get(reverse("player_profile", args=[self.silver.id]))
        self.assertContains(silver, "mgl/cards/silver_card.png")
        self.assertContains(silver, "FREE AGENT")
        self.assertNotContains(silver, "core/img/clubs/")

        bronze = self.client.get(reverse("player_profile", args=[self.bronze.id]))
        self.assertContains(bronze, "mgl/cards/bronze_card.png")

    def test_player_database_filters_and_cards(self):
        self.assertEqual(self.client.get(reverse("player_database")).status_code, 302)
        self.client.login(username="carduser", password="test-pass-123")
        response = self.client.get(reverse("player_database"), {"tier": "GOLD"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GOLD STRIKER")
        self.assertContains(response, "mgl/cards/gold_card.png")
        self.assertNotContains(response, "Bronze Back")

        free = self.client.get(reverse("player_database"), {"free": "1"})
        self.assertContains(free, "SILVER MID")
        self.assertNotContains(free, "GOLD STRIKER")

    def test_market_and_squad_keep_permissions(self):
        self.team.manager = self.user
        self.team.save(update_fields=["manager"])
        listing = PlayerListing.objects.create(
            player=self.gold,
            team=self.team,
            seller=self.manager,
            asking_price=Decimal("12.00"),
            status=PlayerListing.LIVE,
        )
        market = self.client.get(reverse("transfer_market"))
        self.assertEqual(market.status_code, 200)
        self.assertContains(market, "Gold Striker")
        self.assertContains(market, "12")
        self.assertNotContains(market, "BUY NOW")

        self.client.login(username="carduser", password="test-pass-123")
        squad = self.client.get(reverse("team_management"))
        self.assertEqual(squad.status_code, 200)
        self.assertContains(squad, "Gold Striker")
        self.assertContains(squad, "mgl/cards/gold_card.png")
        self.assertContains(squad, "SELL A PLAYER")
        self.assertContains(squad, "WITHDRAW")
        return listing
