from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from mgl.market import (
    approve_listing,
    create_listed_purchase_offer,
    create_transfer_offer,
    list_player_for_sale,
    reject_listing,
    respond_to_transfer_offer,
)
from mgl.models import ManagerNotification, MarketTransaction, PlayerListing
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(username=username, password="test-pass-123", role=role)


def _manager(user, tokens="40.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class PurchaseSwapWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = League.objects.create(name="Purchase League", short_name="PUL", season="1")
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("buyer")
        self.user_b = _user("seller")
        self.user_c = _user("other")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
        self.mgr_c = _manager(self.user_c)
        self.team_a = Team.objects.create(
            name="Bayern Test", short_name="BAY", league=self.league, manager=self.user_a
        )
        self.team_b = Team.objects.create(
            name="Atletico Test", short_name="ATM", league=self.league, manager=self.user_b
        )
        self.team_c = Team.objects.create(
            name="Inter Test", short_name="INT", league=self.league, manager=self.user_c
        )
        self.target = Player.objects.create(
            name="Ola Solbakken", position="CAM", overall=70, mgl_team=self.team_b
        )
        self.swap = Player.objects.create(
            name="Kai Player", position="CM", overall=74, mgl_team=self.team_a
        )
        self.other_club_player = Player.objects.create(
            name="Away Winger", position="LW", overall=71, mgl_team=self.team_c
        )
        self.listing = list_player_for_sale(self.target, self.mgr_b, "1.00")

    def test_market_buy_button_order_and_purchase_page(self):
        self.client.login(username="buyer", password="test-pass-123")
        market = self.client.get(reverse("transfer_market"))
        html = market.content.decode()
        self.assertNotIn(">OFFER</button>", html)
        self.assertIn("VIEW PLAYER", html)
        self.assertIn(">BUY</a>", html)
        self.assertLess(html.index("VIEW PLAYER"), html.index(">BUY</a>"))
        self.assertContains(market, reverse("purchase_listing", args=[self.listing.id]))
        self.assertNotContains(market, reverse("buy_player", args=[self.listing.id]))

        page = self.client.get(reverse("purchase_listing", args=[self.listing.id]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Ola Solbakken")
        self.assertContains(page, "Atletico Test")
        self.assertContains(page, "Bayern Test")
        self.assertContains(page, "Kai Player")
        self.assertContains(page, "SEND OFFER")
        self.assertContains(page, 'type="checkbox"')
        self.assertContains(page, f'value="{self.swap.id}"')
        self.assertNotContains(page, f'value="{self.target.id}"')
        self.assertNotContains(page, f'value="{self.other_club_player.id}"')

    def test_player_lock_query_does_not_join_nullable_team(self):
        sql = str(Player.objects.select_for_update().filter(pk=self.target.id).query)
        self.assertNotIn("JOIN", sql.upper())
        self.assertNotIn("teams_team", sql)

    def test_seller_does_not_see_buy_and_cannot_open_own_purchase_page(self):
        self.client.login(username="seller", password="test-pass-123")
        market = self.client.get(reverse("transfer_market"))
        self.assertNotContains(market, reverse("purchase_listing", args=[self.listing.id]))
        blocked = self.client.get(reverse("purchase_listing", args=[self.listing.id]))
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(blocked["Location"], reverse("transfer_market"))

    def test_cannot_offer_another_clubs_player_as_swap(self):
        self.client.login(username="buyer", password="test-pass-123")
        posted = self.client.post(
            reverse("purchase_listing", args=[self.listing.id]),
            {"asking_price": "2.00", "offered_player": str(self.other_club_player.id)},
        )
        self.assertEqual(posted.status_code, 302)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, PlayerListing.LIVE)
        self.assertIsNone(self.listing.reserved_buyer_id)
        self.target.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)

    def test_tokens_only_offer_uses_existing_approval_workflow(self):
        self.client.login(username="buyer", password="test-pass-123")
        posted = self.client.post(
            reverse("purchase_listing", args=[self.listing.id]),
            {"asking_price": "2.00"},
        )
        self.assertEqual(posted.status_code, 302)
        self.assertEqual(posted["Location"], reverse("manager_hub"))
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, PlayerListing.OFFER)
        self.assertEqual(self.listing.reserved_buyer_id, self.mgr_a.id)
        self.assertEqual(self.listing.asking_price, Decimal("2.00"))
        self.assertIsNone(self.listing.offered_player_id)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))

        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"transfer-offer-{self.listing.pk}",
        )
        self.client.login(username="seller", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "Transfer Request")
        self.assertContains(inbox, "Ola Solbakken")
        self.assertContains(inbox, "2.00 TKN")
        accepted = self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        self.assertEqual(accepted.status_code, 302)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, PlayerListing.PENDING)
        self.target.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))

        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertContains(control, "Ola Solbakken")
        self.assertContains(control, "Atletico Test")
        self.assertContains(control, "Bayern Test")
        self.assertContains(control, "SELLER RECEIVES")
        self.assertContains(control, "BUYER RECEIVES")
        self.assertContains(control, "2.00 TKN")
        approved = approve_listing(self.listing, self.owner)
        self.assertEqual(approved.status, PlayerListing.SOLD)
        self.target.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_a.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("38.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("42.00"))
        self.assertTrue(
            MarketTransaction.objects.filter(
                listing=self.listing,
                player=self.target,
                status=MarketTransaction.COMPLETED,
            ).exists()
        )

    def test_player_and_tokens_swap_moves_both_players_once(self):
        listing = create_listed_purchase_offer(self.listing, self.mgr_a, "2.00", offered_player=self.swap)
        self.assertEqual(listing.status, PlayerListing.OFFER)
        self.assertEqual(listing.offered_player_id, self.swap.id)
        self.assertEqual(list(listing.offered_players.values_list("id", flat=True)), [self.swap.id])
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"transfer-offer-{listing.pk}",
        )
        self.client.login(username="seller", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "Kai Player")
        self.assertContains(inbox, "Selling club receives")
        self.assertContains(inbox, "Buying club receives")
        respond_to_transfer_offer(listing, self.user_b, True)
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.PENDING)
        self.target.refresh_from_db()
        self.swap.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)
        self.assertEqual(self.swap.mgl_team_id, self.team_a.id)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))

        approve_listing(listing, self.owner)
        self.target.refresh_from_db()
        self.swap.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_a.id)
        self.assertEqual(self.swap.mgl_team_id, self.team_b.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("38.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("42.00"))
        self.assertEqual(
            MarketTransaction.objects.filter(listing=listing, status=MarketTransaction.COMPLETED).count(),
            2,
        )

    def test_player_only_swap_does_not_change_tokens(self):
        listing = create_listed_purchase_offer(self.listing, self.mgr_a, "0", offered_player=self.swap)
        respond_to_transfer_offer(listing, self.user_b, True)
        approve_listing(listing, self.owner)
        self.target.refresh_from_db()
        self.swap.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_a.id)
        self.assertEqual(self.swap.mgl_team_id, self.team_b.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("40.00"))

    def test_seller_reject_keeps_players_and_tokens(self):
        listing = create_listed_purchase_offer(self.listing, self.mgr_a, "3.00", offered_player=self.swap)
        respond_to_transfer_offer(listing, self.user_b, False)
        listing.refresh_from_db()
        self.target.refresh_from_db()
        self.swap.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.REJECTED)
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)
        self.assertEqual(self.swap.mgl_team_id, self.team_a.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("40.00"))

    def test_admin_reject_keeps_players_and_tokens(self):
        listing = create_listed_purchase_offer(self.listing, self.mgr_a, "3.00")
        respond_to_transfer_offer(listing, self.user_b, True)
        reject_listing(listing, self.owner)
        listing.refresh_from_db()
        self.target.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.REJECTED)
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("40.00"))

    def test_duplicate_purchase_does_not_create_second_offer(self):
        create_listed_purchase_offer(self.listing, self.mgr_a, "2.00")
        with self.assertRaises(ValueError):
            create_listed_purchase_offer(self.listing, self.mgr_a, "2.00")
        self.assertEqual(
            PlayerListing.objects.filter(player=self.target, status=PlayerListing.OFFER).count(),
            1,
        )

    def test_buyer_cannot_accept_own_offer(self):
        listing = create_listed_purchase_offer(self.listing, self.mgr_a, "2.00")
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"transfer-offer-{listing.pk}",
        )
        self.client.login(username="buyer", password="test-pass-123")
        stolen = self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        self.assertEqual(stolen.status_code, 302)
        listing.refresh_from_db()
        self.assertEqual(listing.status, PlayerListing.OFFER)
        self.target.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)

    def test_buy_player_url_cannot_transfer_immediately(self):
        self.client.login(username="buyer", password="test-pass-123")
        bought = self.client.post(reverse("buy_player", args=[self.listing.id]))
        self.assertEqual(bought.status_code, 302)
        self.assertEqual(bought["Location"], reverse("purchase_listing", args=[self.listing.id]))
        self.listing.refresh_from_db()
        self.target.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.listing.status, PlayerListing.LIVE)
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))

    def test_multiple_swap_players_move_together_after_final_approval(self):
        extra = Player.objects.create(
            name="Second Swap", position="ST", overall=72, mgl_team=self.team_a
        )
        third = Player.objects.create(
            name="Third Swap", position="CB", overall=71, mgl_team=self.team_a
        )
        self.client.login(username="buyer", password="test-pass-123")
        posted = self.client.post(
            reverse("purchase_listing", args=[self.listing.id]),
            {
                "asking_price": "2.00",
                "offered_players": [str(self.swap.id), str(extra.id), str(third.id)],
            },
        )
        self.assertEqual(posted.status_code, 302)
        self.assertEqual(posted["Location"], reverse("manager_hub"))
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, PlayerListing.OFFER)
        self.assertEqual(self.listing.offered_players.count(), 3)
        self.target.refresh_from_db()
        extra.refresh_from_db()
        third.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)
        self.assertEqual(self.swap.mgl_team_id, self.team_a.id)
        self.assertEqual(extra.mgl_team_id, self.team_a.id)
        self.assertEqual(third.mgl_team_id, self.team_a.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))

        self.client.login(username="seller", password="test-pass-123")
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "Kai Player")
        self.assertContains(inbox, "Second Swap")
        self.assertContains(inbox, "Third Swap")
        respond_to_transfer_offer(self.listing, self.user_b, True)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, PlayerListing.PENDING)
        self.target.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_b.id)

        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertContains(control, "Kai Player")
        self.assertContains(control, "Second Swap")
        approve_listing(self.listing, self.owner)
        self.target.refresh_from_db()
        self.swap.refresh_from_db()
        extra.refresh_from_db()
        third.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.team_a.id)
        self.assertEqual(self.swap.mgl_team_id, self.team_b.id)
        self.assertEqual(extra.mgl_team_id, self.team_b.id)
        self.assertEqual(third.mgl_team_id, self.team_b.id)
        self.assertEqual(self.mgr_a.tokens, Decimal("38.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("42.00"))

    def test_existing_unlisted_transfer_request_still_works(self):
        unlisted = Player.objects.create(
            name="Unlisted Mid", position="CM", overall=73, mgl_team=self.team_b
        )
        listing = create_transfer_offer(unlisted, self.mgr_a, "8.00")
        self.assertEqual(listing.status, PlayerListing.OFFER)
        self.assertIsNone(listing.offered_player_id)
        respond_to_transfer_offer(listing, self.user_b, True)
        approve_listing(listing, self.owner)
        unlisted.refresh_from_db()
        self.assertEqual(unlisted.mgl_team_id, self.team_a.id)

    def test_locked_swap_player_cannot_be_offered(self):
        extra = Player.objects.create(
            name="Listed Swap", position="ST", overall=72, mgl_team=self.team_a
        )
        list_player_for_sale(extra, self.mgr_a, "4.00")
        self.client.login(username="buyer", password="test-pass-123")
        page = self.client.get(reverse("purchase_listing", args=[self.listing.id]))
        self.assertContains(page, "Listed Swap")
        posted = self.client.post(
            reverse("purchase_listing", args=[self.listing.id]),
            {"asking_price": "1.00", "offered_player": str(extra.id)},
        )
        self.assertEqual(posted.status_code, 302)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, PlayerListing.LIVE)
        extra.refresh_from_db()
        self.assertEqual(extra.mgl_team_id, self.team_a.id)
