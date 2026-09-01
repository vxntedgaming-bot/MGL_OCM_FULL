from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from mgl.activity import activity_payloads, completed_deal_payload, extract_newsroom_feed, extract_page_main, published_football_activity
from mgl.market import (
    approve_listing,
    create_listed_purchase_offer,
    list_player_for_sale,
    reject_listing,
    respond_to_transfer_offer,
)
from mgl.models import NewsPost, PlayerListing
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


class CompletedDealCardTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = League.objects.create(name="Deal League", short_name="DEL", season="1")
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("buyer")
        self.user_b = _user("seller")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
        self.team_a = Team.objects.create(
            name="Bayer Test", short_name="BAY", league=self.league, manager=self.user_a
        )
        self.team_b = Team.objects.create(
            name="Atletico Test", short_name="ATM", league=self.league, manager=self.user_b
        )
        self.target = Player.objects.create(
            name="Target Forward", position="ST", overall=78, mgl_team=self.team_b
        )
        self.swap_one = Player.objects.create(
            name="First Swap", position="CM", overall=76, mgl_team=self.team_a
        )
        self.swap_two = Player.objects.create(
            name="Second Swap", position="CB", overall=74, mgl_team=self.team_a
        )
        self.swap_three = Player.objects.create(
            name="Third Swap", position="LW", overall=71, mgl_team=self.team_a
        )
        self.listing = list_player_for_sale(self.target, self.mgr_b, "3.00")

    def _complete(self, amount="3.00", offered=None):
        kwargs = {}
        if isinstance(offered, (list, tuple)):
            kwargs["offered_players"] = offered
        elif offered is not None:
            kwargs["offered_player"] = offered
        listing = create_listed_purchase_offer(
            self.listing,
            self.mgr_a,
            amount,
            **kwargs,
        )
        respond_to_transfer_offer(listing, self.user_b, True)
        return approve_listing(listing, self.owner)

    def _activity(self):
        return self.client.get(reverse("live_activity"))

    def _deal_posts(self):
        return NewsPost.objects.filter(category=NewsPost.TRANSFER, published=True).exclude(
            title__icontains="listed"
        )

    def test_token_only_transfer_shows_player_fee_and_no_empty_sides(self):
        sold = self._complete("3.00")
        self.assertEqual(sold.status, PlayerListing.SOLD)
        page = self._activity()
        html = page.content.decode()
        self.assertContains(page, "TRANSFER")
        self.assertContains(page, "Atletico Test")
        self.assertContains(page, "Bayer Test")
        self.assertContains(page, "Target Forward")
        self.assertContains(page, "78 OVR")
        self.assertContains(page, "Bayer Test paid 3.00 TKN")
        self.assertContains(page, "TRANSFER COMPLETED")
        self.assertContains(page, reverse("player_profile", args=[self.target.id]))
        self.assertIn("→", html)
        self.assertIn("IN", html)
        self.assertIn("OUT", html)
        self.assertIn("—", html)
        self.assertEqual(self._deal_posts().count(), 1)
        post = self._deal_posts().get()
        deal = activity_payloads([post])[0]["deal"]
        self.assertEqual([row["name"] for row in deal["seller_out"]], ["Target Forward"])
        self.assertEqual(deal["seller_in"], [])
        self.assertEqual([row["name"] for row in deal["buyer_in"]], ["Target Forward"])
        self.assertEqual(deal["buyer_out"], [])
        self.assertEqual(post.details["swaps"], [])
        self.assertEqual(post.details["amount"], "3.00")

    def test_one_player_swap_separates_both_clubs(self):
        self._complete("2.00", offered=self.swap_one)
        page = self._activity()
        html = extract_page_main(page.content.decode())
        self.assertContains(page, "Atletico Test")
        self.assertContains(page, "Bayer Test")
        self.assertContains(page, "Target Forward")
        self.assertContains(page, "78 OVR")
        self.assertContains(page, "First Swap")
        self.assertContains(page, "76 OVR")
        self.assertContains(page, "Bayer Test paid 2.00 TKN")
        self.assertContains(page, "TRANSFER COMPLETED")
        self.assertContains(page, reverse("player_profile", args=[self.target.id]))
        self.assertContains(page, reverse("player_profile", args=[self.swap_one.id]))
        self.assertIn("→", html)
        self.assertNotIn("↔", html)
        post = self._deal_posts().get()
        deal = activity_payloads([post])[0]["deal"]
        self.assertEqual([row["name"] for row in deal["seller_out"]], ["Target Forward"])
        self.assertEqual([row["name"] for row in deal["seller_in"]], ["First Swap"])
        self.assertEqual([row["name"] for row in deal["buyer_in"]], ["Target Forward"])
        self.assertEqual([row["name"] for row in deal["buyer_out"]], ["First Swap"])
        self.assertEqual(html.count("First Swap"), 2)
        self.assertEqual(html.count("Target Forward"), 2)

    def test_multiple_swap_players_all_appear(self):
        listing = create_listed_purchase_offer(
            self.listing,
            self.mgr_a,
            "2.00",
            offered_players=[self.swap_one, self.swap_two, self.swap_three],
        )
        respond_to_transfer_offer(listing, self.user_b, True)
        approve_listing(listing, self.owner)
        page = self._activity()
        self.assertContains(page, "Target Forward")
        self.assertContains(page, "First Swap")
        self.assertContains(page, "Second Swap")
        self.assertContains(page, "Third Swap")
        self.assertContains(page, "76 OVR")
        self.assertContains(page, "74 OVR")
        self.assertContains(page, "71 OVR")
        self.assertContains(page, "Bayer Test paid 2.00 TKN")
        self.assertContains(page, reverse("player_profile", args=[self.swap_two.id]))
        self.assertContains(page, reverse("player_profile", args=[self.swap_three.id]))
        post = self._deal_posts().get()
        deal = activity_payloads([post])[0]["deal"]
        self.assertEqual(len(post.details["swaps"]), 3)
        names = {row["name"] for row in post.details["swaps"]}
        self.assertEqual(names, {"First Swap", "Second Swap", "Third Swap"})
        self.assertEqual(
            [row["name"] for row in deal["buyer_out"]],
            [row["name"] for row in deal["seller_in"]],
        )
        self.assertEqual([row["name"] for row in deal["buyer_in"]], ["Target Forward"])
        self.assertEqual(len(deal["seller_in"]), 3)

    def test_player_only_swap_shows_zero_tokens(self):
        self._complete("0", offered=self.swap_one)
        page = self._activity()
        self.assertContains(page, "Bayer Test paid 0.00 TKN")
        self.assertContains(page, "First Swap")
        self.assertContains(page, "Target Forward")
        self.assertNotContains(page, "Transfer fee:")
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("40.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("40.00"))

    def test_player_and_token_deal_shows_both(self):
        self._complete("3.00", offered=[self.swap_one, self.swap_two])
        page = self._activity()
        self.assertContains(page, "Target Forward")
        self.assertContains(page, "First Swap")
        self.assertContains(page, "Second Swap")
        self.assertContains(page, "Bayer Test paid 3.00 TKN")
        self.assertContains(page, "TRANSFER COMPLETED")

    def test_seller_rejection_is_not_a_completed_deal(self):
        listing = create_listed_purchase_offer(
            self.listing, self.mgr_a, "3.00", offered_player=self.swap_one
        )
        respond_to_transfer_offer(listing, self.user_b, False)
        page = self._activity()
        main = extract_page_main(page.content.decode())
        self.assertNotIn("TRANSFER COMPLETED", main)
        self.assertNotIn("Target Forward", main)
        self.assertFalse(self._deal_posts().exists())
        self.assertFalse(published_football_activity().filter(category=NewsPost.TRANSFER).exists())

    def test_owner_rejection_is_not_a_completed_deal(self):
        listing = create_listed_purchase_offer(self.listing, self.mgr_a, "3.00")
        respond_to_transfer_offer(listing, self.user_b, True)
        reject_listing(listing, self.owner)
        page = self._activity()
        main = extract_page_main(page.content.decode())
        self.assertNotIn("TRANSFER COMPLETED", main)
        self.assertNotIn("Target Forward", main)
        self.assertFalse(self._deal_posts().exists())

    def test_snapshot_stays_after_players_move_again(self):
        self._complete("1.00", offered=self.swap_one)
        post = self._deal_posts().get()
        self.assertEqual(post.details["target"]["name"], "Target Forward")
        self.assertEqual(post.details["target"]["overall"], 78)
        self.assertEqual(post.details["swaps"][0]["name"], "First Swap")
        self.assertEqual(post.details["swaps"][0]["overall"], 76)

        self.target.name = "Renamed Later"
        self.target.overall = 99
        self.target.save(update_fields=["name", "overall"])
        self.swap_one.name = "Moved Again"
        self.swap_one.overall = 60
        self.swap_one.save(update_fields=["name", "overall"])

        page = self._activity()
        self.assertContains(page, "Target Forward")
        self.assertContains(page, "78 OVR")
        self.assertContains(page, "First Swap")
        self.assertContains(page, "76 OVR")
        self.assertNotContains(page, "Renamed Later")
        self.assertNotContains(page, "Moved Again")
        self.assertNotContains(page, "99 OVR")
        payload = activity_payloads([post])[0]
        self.assertEqual(payload["deal"]["target"]["name"], "Target Forward")
        self.assertEqual(payload["deal"]["swaps"][0]["overall"], 76)

    def test_one_completed_deal_creates_one_activity_card(self):
        self._complete("3.00", offered=self.swap_one)
        self.assertEqual(self._deal_posts().count(), 1)
        page = self._activity()
        self.assertEqual(page.content.decode().count("mgl-deal-card"), 1)
        self.assertEqual(page.content.decode().count("TRANSFER COMPLETED"), 1)

    def test_home_and_activity_use_the_same_deal_card(self):
        self._complete("3.00")
        home = self.client.get(reverse("home"))
        activity = self._activity()
        self.assertNotContains(home, "mgl-deal-card")
        self.assertNotContains(home, "LEAGUE LIVE UPDATES")
        self.assertContains(home, "Target Forward transferred")
        self.assertContains(home, "mgl-news-logo-pair")
        self.assertContains(home, "Atletico Test")
        self.assertContains(home, "Bayer Test")
        self.assertContains(activity, "mgl-deal-card")
        self.assertContains(activity, "Bayer Test paid 3.00 TKN")

    def test_live_activity_hides_free_agent_auction_and_scouting(self):
        NewsPost.objects.create(
            category=NewsPost.SIGNING,
            title="Free Signing signed",
            body="Free Signing joined Bayer Test on a free signing.",
            published=True,
            primary_team=self.team_a,
        )
        NewsPost.objects.create(
            category=NewsPost.AUCTION,
            title="Auction started for Pool Player",
            body="Pool Player is now available in an Admin auction.",
            published=True,
        )
        NewsPost.objects.create(
            category=NewsPost.FREE_AGENT,
            title="Pool Player is a Free Agent",
            body="Pool Player is now available as a Free Agent after an auction received no bids.",
            published=True,
        )
        NewsPost.objects.create(
            category=NewsPost.SCOUTING,
            title="Scouted Mid recruited",
            body="Bayer Test recruited Scouted Mid through the MGL scouting network.",
            published=True,
            primary_team=self.team_a,
        )
        NewsPost.objects.create(
            category=NewsPost.MANAGER,
            title="Buyer has left Bayer Test",
            body="Buyer has left Bayer Test.",
            published=True,
            primary_team=self.team_a,
        )
        page = self._activity()
        feed = extract_newsroom_feed(page.content.decode())
        self.assertNotIn("Free Signing", feed)
        self.assertNotIn("Pool Player", feed)
        self.assertNotIn("Scouted Mid", feed)
        self.assertNotIn("has left Bayer Test", feed)
        self.assertFalse(published_football_activity().exclude(category__in=["RESULTS", "TRANSFER"]).exists())

    def test_transfer_header_uses_existing_club_logos(self):
        self.team_a.badge_code = "B04"
        self.team_b.badge_code = "ATM"
        self.team_a.save(update_fields=["badge_code"])
        self.team_b.save(update_fields=["badge_code"])
        self._complete("3.00")
        page = self._activity()
        html = page.content.decode()
        header = html.split("mgl-deal-sides", 1)[0]
        self.assertIn("mgl-team-logo", header)
        self.assertIn('title="Atletico Test"', header)
        self.assertIn('title="Bayer Test"', header)
        self.assertIn("core/img/clubs/ATM.svg", header)
        self.assertIn("core/img/clubs/B04.svg", header)
        self.assertIn("mgl-deal-arrow", header)
        self.assertIn("→", header)
        self.assertContains(page, "Atletico Test")
        self.assertContains(page, "Bayer Test")
        deal = activity_payloads(self._deal_posts())[0]["deal"]
        self.assertEqual(deal["selling_team"].id, self.team_b.id)
        self.assertEqual(deal["buying_team"].id, self.team_a.id)

    def test_header_logos_follow_snapshot_clubs(self):
        self._complete("3.00")
        post = self._deal_posts().get()
        post.primary_team = self.team_b
        post.secondary_team = self.team_a
        deal = completed_deal_payload(post, [self.team_a, self.team_b])
        self.assertEqual(deal["selling_team"].id, self.team_b.id)
        self.assertEqual(deal["buying_team"].id, self.team_a.id)

    def test_legacy_transfer_without_snapshot_keeps_simple_card(self):
        NewsPost.objects.create(
            category=NewsPost.TRANSFER,
            title="Old Deal transferred",
            body="Old Deal has joined Bayer Test from Atletico Test.",
            published=True,
            primary_team=self.team_a,
            secondary_team=self.team_b,
        )
        page = self._activity()
        self.assertContains(page, "Old Deal")
        self.assertContains(page, "Transfer completed")
        self.assertNotContains(page, "mgl-deal-card")
        self.assertNotContains(page, "TRANSFER COMPLETED")
