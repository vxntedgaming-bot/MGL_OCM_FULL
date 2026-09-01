from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from managers.models import ManagerApplication
from mgl.market import (
    counter_transfer_offer,
    create_listed_purchase_offer,
    list_player_for_sale,
    place_auction_bid,
    respond_to_transfer_offer,
)
from mgl.models import PlayerListing, PressConference, ScoutSquadException
from mgl.press import approve_press_conference, create_press_question, submit_press_answer
from mgl.scouting import dispatch_scout
from mgl.test_scouting import _finish
from players.models import Player
from teams.models import Team


def _user(name, role=User.MANAGER):
    return User.objects.create_user(username=name, password="test-pass-123", role=role)


def _manager(user, tokens="20.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username,
        gamertag=user.username[:8],
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class UFLCareerModeTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name="Career", short_name="CAR", season="1")
        self.owner = _user("career-owner", User.OWNER)
        self.user_a = _user("career-a")
        self.user_b = _user("career-b")
        self.mgr_a = _manager(self.user_a, "20.00")
        self.mgr_b = _manager(self.user_b, "20.00")
        self.club_a = Team.objects.create(name="Alpha", short_name="ALP", league=self.league, manager=self.user_a)
        self.club_b = Team.objects.create(name="Beta", short_name="BET", league=self.league, manager=self.user_b)
        self.player = Player.objects.create(
            name="Career Striker", position="ST", overall=66, mgl_team=self.club_a, is_free_agent=False
        )
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_public_pages_are_visible(self):
        for name in ("home", "leagues_page", "clubs_index", "player_database", "transfer_market", "live_auctions", "pressroom", "ufl_rules"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_negotiation_counter_then_accept_stays_owned_until_admin(self):
        listing = list_player_for_sale(self.player, self.mgr_a, "8")
        listing.status = PlayerListing.LIVE
        listing.save(update_fields=["status"])
        create_listed_purchase_offer(listing, self.mgr_b, "8")
        listing.refresh_from_db()
        counter_transfer_offer(listing, self.user_a, "10")
        listing.refresh_from_db()
        self.assertEqual(listing.asking_price, Decimal("10"))
        self.assertEqual(listing.status, PlayerListing.OFFER)
        self.assertEqual(listing.negotiation_events.count(), 2)
        respond_to_transfer_offer(listing, self.user_a, True)
        listing.refresh_from_db()
        self.player.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        self.assertEqual(self.player.mgl_team_id, self.club_a.id)

    def test_self_auction_bid_is_rejected(self):
        from mgl.market import create_manager_auction

        auction = create_manager_auction(self.player, self.mgr_a, 30, 1)
        with self.assertRaisesMessage(ValueError, "your own auction"):
            place_auction_bid(auction, self.mgr_a, 2)
        self.assertEqual(PlayerAuction.objects.get(pk=auction.pk).winning_bid, 0)

    def test_press_pays_only_after_approval(self):
        press = create_press_question(
            manager=self.user_a,
            team=self.club_a,
            question="What pleased you most?",
            question_key="career_press",
            category="performance",
            trigger=PressConference.MATCH,
        )
        submit_press_answer(press, "The pressing.")
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("20.00"))
        approve_press_conference(press, reviewer=self.owner)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("20.50"))

    def test_full_squad_scout_creates_exception(self):
        for index in range(27):
            Player.objects.create(
                name=f"Filled {index}",
                position="CM",
                overall=61,
                nationality="England",
                mgl_team=self.club_a,
                is_free_agent=False,
            )
        target = Player.objects.create(
            name="Waiting Prospect",
            position="ST",
            overall=50,
            nationality="France",
            is_free_agent=False,
        )
        assignment = dispatch_scout(self.mgr_a, "BRONZE", "europe", "ST")
        _finish(assignment)
        target.refresh_from_db()
        self.assertIsNone(target.mgl_team_id)
        self.assertTrue(ScoutSquadException.objects.filter(player=target, status="PENDING").exists())
        self.assertEqual(Player.objects.filter(mgl_team=self.club_a).count(), 28)
