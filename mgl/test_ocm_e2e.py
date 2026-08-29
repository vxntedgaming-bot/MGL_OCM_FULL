from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from managers.models import ManagerApplication
from mgl.market import place_auction_bid
from mgl.models import MarketTransaction, PlayerListing
from players.models import Player
from teams.models import Team


class OcmEndToEndTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = League.objects.create(name="MGL", short_name="MGL", season="1")
        self.owner = User.objects.create_user(
            username="owner",
            password="test-pass-123",
            role=User.OWNER,
        )
        self.club_a = Team.objects.create(
            name="Alpha FC",
            short_name="AFC",
            league=self.league,
        )
        self.club_b = Team.objects.create(
            name="Beta FC",
            short_name="BFC",
            league=self.league,
        )
        self.player = Player.objects.create(
            name="Player X",
            position="ST",
            overall=70,
            mgl_team=self.club_a,
            is_free_agent=False,
        )
        self.kept = Player.objects.create(
            name="Kept Player",
            position="CB",
            overall=68,
            mgl_team=self.club_a,
            is_free_agent=False,
        )
        self.fa = Player.objects.create(
            name="Free Agent Y",
            position="CM",
            overall=68,
            is_free_agent=True,
        )

    def _register(self, username, display_name, gamertag):
        return self.client.post(
            reverse("manager_register"),
            {
                "username": username,
                "email": f"{username}@example.com",
                "display_name": display_name,
                "gamertag": gamertag,
                "preferred_team": "Alpha FC",
                "password": "Ocm-pass-12345",
                "confirm_password": "Ocm-pass-12345",
            },
        )

    def test_full_career_mode_lifecycle(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "No upcoming fixtures have been released.")
        self.assertNotContains(home, "250m")

        register = self._register("alice", "Alice", "AlicePSN")
        self.assertEqual(register.status_code, 200)
        self.assertContains(register, "20 tokens")

        user_a = User.objects.get(username="alice")
        self.assertFalse(user_a.is_active)
        self.assertEqual(user_a.role, User.MANAGER)
        application_a = ManagerApplication.objects.get(user=user_a)
        self.assertEqual(application_a.status, ManagerApplication.PENDING)

        blocked = self.client.post(
            reverse("manager_login"),
            {"username": "alice", "password": "Ocm-pass-12345"},
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertFalse(blocked.wsgi_request.user.is_authenticated)

        self.assertEqual(self.client.get(reverse("control_centre")).status_code, 302)
        self.assertEqual(self.client.get(reverse("manager_hub")).status_code, 302)

        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertEqual(control.status_code, 200)
        self.assertContains(control, "Alice")
        self.assertContains(control, "Alpha FC")
        self.assertContains(control, "50.00 TKN")
        self.client.post(reverse("control_approve_manager", args=[application_a.id]))
        application_a.refresh_from_db()
        user_a.refresh_from_db()
        self.assertEqual(application_a.status, ManagerApplication.APPROVED)
        self.assertTrue(user_a.is_active)
        self.assertEqual(application_a.tokens, Decimal("20.00"))
        self.client.logout()

        self.assertTrue(self.client.login(username="alice", password="Ocm-pass-12345"))
        hub = self.client.get(reverse("manager_hub"))
        self.assertEqual(hub.status_code, 200)
        self.assertContains(hub, "APPLY FOR A CLUB")
        apply = self.client.post(
            reverse("apply_for_club", args=[self.club_a.id]),
            {
                "gamertag": "AlicePSN",
                "discord_username": "alice",
                "games_per_week": "3",
                "new_gen_confirmed": "on",
            },
        )
        self.assertEqual(apply.status_code, 302)
        self.client.logout()

        self.client.login(username="owner", password="test-pass-123")
        job = application_a.club_applications.get(team=self.club_a)
        self.client.post(reverse("control_approve_job", args=[job.id]))
        self.club_a.refresh_from_db()
        self.assertEqual(self.club_a.manager_id, user_a.id)
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))
        self.client.logout()

        self.assertTrue(self.client.login(username="alice", password="Ocm-pass-12345"))
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, "AFC")
        squad = self.client.get(reverse("team_management"))
        self.assertContains(squad, "PLAYER X")
        self.assertContains(squad, "20")
        self.assertNotContains(squad, "250")

        forbidden = self.client.post(reverse("control_approve_listing", args=[9999]))
        self.assertEqual(forbidden.status_code, 302)
        self.assertEqual(forbidden["Location"], reverse("manager_hub"))

        self.client.post(
            reverse("sell_player", args=[self.player.id]),
            {"asking_price": "12"},
        )
        listing = PlayerListing.objects.get(player=self.player)
        self.assertEqual(listing.status, PlayerListing.PENDING)
        self.client.post(
            reverse("sell_player", args=[self.player.id]),
            {"asking_price": "15"},
        )
        self.assertEqual(PlayerListing.objects.filter(player=self.player).count(), 1)
        self.client.logout()

        self._register("bob", "Bob", "BobPSN")
        user_b = User.objects.get(username="bob")
        application_b = user_b.manager_application
        self.client.login(username="owner", password="test-pass-123")
        self.client.post(reverse("control_approve_manager", args=[application_b.id]))
        self.club_b.manager = user_b
        self.club_b.save(update_fields=["manager"])
        steal = self.client.login(username="bob", password="Ocm-pass-12345")
        self.assertTrue(steal)
        steal_sale = self.client.post(
            reverse("sell_player", args=[self.player.id]),
            {"asking_price": "9"},
        )
        self.assertEqual(steal_sale.status_code, 302)
        self.player.refresh_from_db()
        self.assertEqual(self.player.mgl_team_id, self.club_a.id)
        self.assertEqual(
            PlayerListing.objects.filter(player=self.player, seller=application_b).count(),
            0,
        )
        buy_early = self.client.post(reverse("buy_player", args=[listing.id]))
        self.assertEqual(buy_early.status_code, 302)
        self.club_a.refresh_from_db()
        self.club_b.refresh_from_db()
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))
        self.assertEqual(self.club_b.tokens, Decimal("50.00"))
        self.client.logout()

        self.client.login(username="owner", password="test-pass-123")
        self.client.post(reverse("control_approve_listing", args=[listing.id]))
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.LIVE)
        self.client.logout()

        self.client.login(username="alice", password="Ocm-pass-12345")
        own_buy = self.client.post(reverse("buy_player", args=[listing.id]))
        self.assertEqual(own_buy.status_code, 302)
        self.player.refresh_from_db()
        self.assertEqual(self.player.mgl_team_id, self.club_a.id)
        self.client.logout()

        self.client.login(username="bob", password="Ocm-pass-12345")
        self.client.post(reverse("buy_player", args=[listing.id]), {"asking_price": "12"})
        self.client.post(reverse("buy_player", args=[listing.id]))
        self.player.refresh_from_db()
        application_a.refresh_from_db()
        application_b.refresh_from_db()
        self.club_a.refresh_from_db()
        self.club_b.refresh_from_db()
        self.assertEqual(self.player.mgl_team_id, self.club_b.id)
        self.assertFalse(self.player.is_free_agent)
        self.assertEqual(application_a.tokens, Decimal("32.00"))
        self.assertEqual(application_b.tokens, Decimal("8.00"))
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))
        self.assertEqual(self.club_b.tokens, Decimal("50.00"))
        tx = MarketTransaction.objects.get(
            player=self.player,
            transaction_type=MarketTransaction.SALE,
            status=MarketTransaction.COMPLETED,
        )
        self.assertEqual(tx.amount, Decimal("12.00"))
        self.assertEqual(tx.from_team_id, self.club_a.id)
        self.assertEqual(tx.to_team_id, self.club_b.id)
        self.assertEqual(tx.approved_by_id, self.owner.id)

        history = self.client.get(reverse("manager_rewards"))
        self.assertContains(history, "Player X")
        self.assertContains(history, "AFC")
        self.assertContains(history, "BFC")
        self.assertContains(history, "12")
        self.client.logout()

        self.client.login(username="owner", password="test-pass-123")
        global_ledger = self.client.get(reverse("control_centre"))
        self.assertContains(global_ledger, "Player X")
        self.assertContains(global_ledger, "12")
        self.client.post(reverse("remove_club_manager", args=[self.club_a.id]))
        self.club_a.refresh_from_db()
        application_a.refresh_from_db()
        self.assertIsNone(self.club_a.manager_id)
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))
        self.assertEqual(application_a.tokens, Decimal("32.00"))
        self.assertEqual(self.club_a.players.count(), 1)
        self.assertEqual(self.club_a.players.get().name, "Kept Player")
        self.client.logout()

        self.client.login(username="alice", password="Ocm-pass-12345")
        after_leave = self.client.get(reverse("team_management"))
        self.assertContains(after_leave, "NO CLUB ASSIGNED")
        self.client.post(
            reverse("sell_player", args=[self.player.id]),
            {"asking_price": "5"},
        )
        self.player.refresh_from_db()
        self.assertEqual(self.player.mgl_team_id, self.club_b.id)
        self.client.logout()

        self.client.login(username="owner", password="test-pass-123")
        self.client.post(
            reverse("change_club_manager", args=[self.club_a.id]),
            {"manager_application": application_a.id},
        )
        self.club_a.refresh_from_db()
        self.assertEqual(self.club_a.manager_id, user_a.id)
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))
        application_a.refresh_from_db()
        self.assertEqual(application_a.tokens, Decimal("32.00"))
        self.client.logout()

        self.client.login(username="alice", password="Ocm-pass-12345")
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, "AFC")
        self.client.logout()

    def test_zero_and_invalid_bids_are_rejected(self):
        user = User.objects.create_user(username="mgr", password="test-pass-123")
        manager = ManagerApplication.objects.create(
            user=user,
            display_name="Mgr",
            gamertag="M1",
            status=ManagerApplication.APPROVED,
        )
        self.club_a.manager = user
        self.club_a.save(update_fields=["manager"])
        auction = PlayerAuction.objects.create(
            player=self.fa,
            starting_bid=1,
            minimum_increment=1,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(hours=1),
            status=PlayerAuction.LIVE,
        )
        for amount in ["0", "-3", "abc", ""]:
            with self.assertRaises(ValueError):
                place_auction_bid(auction, manager, amount)
        self.club_a.refresh_from_db()
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))

    def test_manager_can_withdraw_pending_listing_and_relist(self):
        user = User.objects.create_user(username="mgr", password="test-pass-123")
        manager = ManagerApplication.objects.create(
            user=user,
            display_name="Mgr",
            gamertag="M1",
            status=ManagerApplication.APPROVED,
        )
        self.club_a.manager = user
        self.club_a.save(update_fields=["manager"])
        self.client.login(username="mgr", password="test-pass-123")
        self.client.post(reverse("sell_player", args=[self.player.id]), {"asking_price": "20"})
        listing = PlayerListing.objects.get(player=self.player)
        self.client.post(reverse("cancel_player_listing", args=[listing.id]))
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.CANCELLED)
        self.client.post(reverse("sell_player", args=[self.player.id]), {"asking_price": "11"})
        self.assertTrue(
            PlayerListing.objects.filter(
                player=self.player,
                asking_price=Decimal("11.00"),
                status=PlayerListing.PENDING,
            ).exists()
        )
        other = User.objects.create_user(username="other", password="test-pass-123")
        ManagerApplication.objects.create(
            user=other,
            display_name="Other",
            gamertag="O1",
            status=ManagerApplication.APPROVED,
        )
        self.club_b.manager = other
        self.club_b.save(update_fields=["manager"])
        listing = PlayerListing.objects.get(player=self.player, status=PlayerListing.PENDING)
        self.client.login(username="other", password="test-pass-123")
        self.client.post(reverse("cancel_player_listing", args=[listing.id]))
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)

    def test_squad_generator_fills_empty_clubs_only(self):
        Team.objects.all().delete()
        Player.objects.all().delete()
        club = Team.objects.create(name="Gamma FC", short_name="GFC", league=self.league)
        filled = Team.objects.create(name="Delta FC", short_name="DFC", league=self.league)
        existing = Player.objects.create(
            name="Kept Player",
            position="ST",
            overall=70,
            mgl_team=filled,
            is_free_agent=False,
        )
        positions = [
            "GK", "GK",
            "CB", "CB", "CB", "CB",
            "LB", "LB",
            "RB", "RB",
            "CDM", "CDM", "CM", "CM",
            "CAM", "CAM",
            "LM", "LM", "LW",
            "RM", "RM", "RW",
            "ST", "ST", "ST", "CF",
        ]
        for index, position in enumerate(positions):
            Player.objects.create(
                name=f"FA {index}",
                position=position,
                overall=64 + (index % 10),
                is_free_agent=True,
            )
        with self.assertRaises(CommandError):
            call_command("generate_balanced_squads")
        club.refresh_from_db()
        filled.refresh_from_db()
        existing.refresh_from_db()
        self.assertEqual(club.players.count(), 0)
        self.assertEqual(filled.players.count(), 1)
        self.assertEqual(existing.mgl_team_id, filled.id)
        leftovers = Player.objects.filter(is_free_agent=True, mgl_team__isnull=True)
        self.assertEqual(leftovers.count(), 26)
        self.assertEqual(
            Player.objects.filter(mgl_team=club).count()
            + Player.objects.filter(mgl_team=filled).count()
            + leftovers.count(),
            Player.objects.count(),
        )

    def test_auction_http_bid_close_moves_player(self):
        user = User.objects.create_user(username="mgr", password="test-pass-123")
        manager = ManagerApplication.objects.create(
            user=user,
            display_name="Mgr",
            gamertag="M1",
            status=ManagerApplication.APPROVED,
        )
        self.club_a.manager = user
        self.club_a.save(update_fields=["manager"])
        auction = PlayerAuction.objects.create(
            player=self.fa,
            starting_bid=1,
            minimum_increment=1,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(hours=1),
            status=PlayerAuction.LIVE,
        )
        self.client.login(username="mgr", password="test-pass-123")
        self.client.post(reverse("place_bid", args=[auction.id]), {"amount": "8", "next": "/market/"})
        manager.refresh_from_db()
        self.club_a.refresh_from_db()
        self.assertEqual(manager.tokens, Decimal("12.00"))
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))
        self.client.logout()
        self.client.login(username="owner", password="test-pass-123")
        self.client.post(reverse("control_close_auction", args=[auction.id]))
        self.fa.refresh_from_db()
        auction.refresh_from_db()
        manager.refresh_from_db()
        self.club_a.refresh_from_db()
        self.assertEqual(self.fa.mgl_team_id, self.club_a.id)
        self.assertFalse(self.fa.is_free_agent)
        self.assertEqual(auction.status, PlayerAuction.ENDED)
        self.assertEqual(manager.tokens, Decimal("12.00"))
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))
        self.assertTrue(
            MarketTransaction.objects.filter(
                player=self.fa,
                transaction_type=MarketTransaction.AUCTION,
                status=MarketTransaction.COMPLETED,
                amount=Decimal("8.00"),
            ).exists()
        )
