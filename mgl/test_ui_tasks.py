from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.market import create_manager_auction
from mgl.models import NewsPost
from mgl.nav import live_competition_choices
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


class HomepageNewsAndActivityTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = League.objects.create(name="News League", short_name="NWS", season="1")
        self.seller = Team.objects.create(name="Seller FC", short_name="SFC", league=self.league)
        self.buyer = Team.objects.create(name="Buyer FC", short_name="BFC", league=self.league)

    def test_homepage_transfer_news_shows_both_club_logos(self):
        NewsPost.objects.create(
            category=NewsPost.TRANSFER,
            title="Karol Knap transferred",
            body="Karol Knap has joined Buyer FC from Seller FC.",
            published=True,
            primary_team=self.buyer,
            secondary_team=self.seller,
        )
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "Karol Knap transferred")
        self.assertContains(home, "mgl-news-logo-pair")
        self.assertContains(home, 'title="Seller FC"')
        self.assertContains(home, 'title="Buyer FC"')
        self.assertContains(home, "LATEST NEWS")
        self.assertNotContains(home, "LEAGUE LIVE UPDATES")
        self.assertNotContains(home, "mgl-activity-feed--home")
        self.assertNotContains(home, "mgl-deal-card")

    def test_homepage_listing_news_shows_one_club_logo(self):
        NewsPost.objects.create(
            category=NewsPost.TRANSFER,
            title="Manuel Maranda listed for sale",
            body="Seller FC listed Manuel Maranda for 2 tokens.",
            published=True,
            primary_team=self.seller,
        )
        home = self.client.get("/")
        self.assertContains(home, "Manuel Maranda listed for sale")
        self.assertContains(home, 'title="Seller FC"')
        self.assertNotContains(home, "mgl-news-logo-pair")

    def test_live_activity_page_still_works(self):
        NewsPost.objects.create(
            category=NewsPost.TRANSFER,
            title="Karol Knap transferred",
            body="Karol Knap has joined Buyer FC from Seller FC.",
            published=True,
            primary_team=self.buyer,
            secondary_team=self.seller,
            details={"deal": True, "amount": "2.00", "buying_club": "Buyer FC", "selling_club": "Seller FC"},
        )
        page = self.client.get(reverse("live_activity"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Live Activity")
        self.assertContains(page, "mgl-deal-card")
        self.assertContains(page, "Buyer FC")


class CompetitionSelectorTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        ensure_premier_league()

    def test_tables_and_stats_use_the_same_selector(self):
        choices = live_competition_choices()
        self.assertEqual(
            [row["slug"] for row in choices],
            ["premier-league", "championship", "league-one"],
        )
        tables = self.client.get(reverse("leagues_page"))
        stats = self.client.get(reverse("stats_page"))
        premier = self.client.get(reverse("competition_page", kwargs={"slug": "premier-league"}))
        champ_stats = self.client.get(reverse("league_stats", kwargs={"slug": "championship"}))
        for page in (tables, stats, premier, champ_stats):
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "mgl-comp-tabs")
            self.assertContains(page, ">PREMIER LEAGUE</a>")
            self.assertContains(page, ">CHAMPIONSHIP</a>")
            self.assertContains(page, ">LEAGUE ONE</a>")
            self.assertNotContains(page, ">PL</a>")
            self.assertNotContains(page, ">CH</a>")
            self.assertNotContains(page, ">L1</a>")
        self.assertContains(tables, reverse("competition_page", kwargs={"slug": "premier-league"}))
        self.assertContains(stats, reverse("league_stats", kwargs={"slug": "championship"}))
        self.assertContains(premier, "mgl-league-tab is-active")
        self.assertContains(champ_stats, "mgl-league-tab is-active")
        self.assertContains(champ_stats, "CHAMPIONSHIP STATS")
        self.assertEqual(
            self.client.get(reverse("competition_page", kwargs={"slug": "league-one"})).status_code,
            200,
        )


class AuctionCountdownTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = League.objects.create(name="Auction UI", short_name="AUI", season="1")
        self.user_a = _user("auc-seller")
        self.user_b = _user("auc-buyer")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
        self.team_a = Team.objects.create(
            name="Auction Alpha", short_name="AAL", league=self.league, manager=self.user_a
        )
        self.team_b = Team.objects.create(
            name="Auction Beta", short_name="ABE", league=self.league, manager=self.user_b
        )
        self.player = Player.objects.create(
            name="Auction Subject", position="ST", overall=74, mgl_team=self.team_a
        )

    def test_auction_page_has_live_countdown_markup(self):
        auction = create_manager_auction(self.player, self.mgr_a, 30, starting_bid=1)
        self.client.login(username="auc-buyer", password="test-pass-123")
        page = self.client.get(reverse("live_auctions"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "LIVE AUCTIONS")
        self.assertContains(page, "data-auction-end")
        self.assertContains(page, "mgl-auction-countdown.js")
        self.assertContains(page, ">BID</a>")
        self.assertContains(page, "PLACE BID")
        self.assertNotContains(page, "VIEW AUCTION")
        self.assertContains(page, "RECENTLY ENDED")
        self.assertContains(page, reverse("player_profile", args=[self.player.id]))
        self.assertContains(page, str(auction.id))

    def test_expired_auction_cannot_receive_a_bid(self):
        auction = create_manager_auction(self.player, self.mgr_a, 30, starting_bid=1)
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        self.client.login(username="auc-buyer", password="test-pass-123")
        response = self.client.post(
            reverse("place_bid", args=[auction.id]),
            {"amount": "5", "next": reverse("live_auctions")},
        )
        self.assertEqual(response.status_code, 302)
        auction.refresh_from_db()
        self.assertEqual(auction.status, PlayerAuction.ENDED)
        self.assertEqual(auction.bids.count(), 0)
        self.assertEqual(self.player.mgl_team_id, self.team_a.id)
        page = self.client.get(reverse("live_auctions"))
        self.assertContains(page, "AUCTION SUBJECT")
        self.assertNotContains(page, f'action="{reverse("place_bid", args=[auction.id])}"')


class FreeAgentSearchTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = League.objects.create(name="FA Search", short_name="FAS", season="1")
        self.user = _user("fa-search")
        _manager(self.user)
        self.owned = Team.objects.create(
            name="Owned Club", short_name="OWN", league=self.league, manager=self.user
        )
        self.fa = Player.objects.create(
            name="Free Striker", position="ST", overall=77, is_free_agent=True
        )
        self.other_fa = Player.objects.create(
            name="Free Back", position="CB", overall=71, is_free_agent=True
        )
        self.club_player = Player.objects.create(
            name="Club Bound", position="ST", overall=80, mgl_team=self.owned, is_free_agent=False
        )
        self.client.login(username="fa-search", password="test-pass-123")

    def test_name_search_only_returns_free_agents(self):
        page = self.client.get(reverse("free_agents"), {"search": "Free Striker"})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "FREE STRIKER")
        self.assertNotContains(page, "FREE BACK")
        self.assertNotContains(page, "CLUB BOUND")
        self.assertContains(page, reverse("player_profile", args=[self.fa.id]))
        self.assertContains(page, "RESET")

    def test_filters_and_reset_and_empty_results(self):
        filtered = self.client.get(
            reverse("free_agents"),
            {"search": "Free", "position": "ST", "min_ovr": "75"},
        )
        self.assertContains(filtered, "FREE STRIKER")
        self.assertNotContains(filtered, "FREE BACK")
        empty = self.client.get(reverse("free_agents"), {"search": "Club Bound"})
        self.assertContains(empty, "NO PLAYERS FOUND")
        reset = self.client.get(reverse("free_agents"))
        self.assertContains(reset, "FREE STRIKER")
        self.assertContains(reset, "FREE BACK")


class PlayerDatabaseFilterTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = League.objects.create(name="DB Search", short_name="DBS", season="1")
        self.user = _user("db-search")
        _manager(self.user)
        self.club = Team.objects.create(
            name="Database FC", short_name="DBF", league=self.league, manager=self.user
        )
        self.mbappe = Player.objects.create(
            name="Kylian Mbappe",
            position="ST",
            overall=91,
            nationality="France",
            preferred_foot="Right",
            skill_moves=5,
            weak_foot=4,
            pace=97,
            shooting=89,
            mgl_team=self.club,
        )
        self.cb = Player.objects.create(
            name="Quiet Centre",
            position="CB",
            overall=72,
            nationality="England",
            preferred_foot="Left",
            skill_moves=2,
            weak_foot=2,
            is_free_agent=True,
        )
        self.client.login(username="db-search", password="test-pass-123")

    def test_search_and_combined_filters(self):
        found = self.client.get(reverse("player_database"), {"search": "Mbappe"})
        self.assertContains(found, "KYLIAN MBAPPE")
        self.assertContains(found, reverse("player_profile", args=[self.mbappe.id]))
        self.assertNotContains(found, "QUIET CENTRE")
        miss = self.client.get(reverse("player_database"), {"search": "Mbappe", "position": "CB"})
        self.assertContains(miss, "NO PLAYERS FOUND")
        rating = self.client.get(reverse("player_database"), {"rating_min": "90"})
        self.assertContains(rating, "KYLIAN MBAPPE")
        self.assertNotContains(rating, "QUIET CENTRE")
        club = self.client.get(reverse("player_database"), {"club": str(self.club.id)})
        self.assertContains(club, "KYLIAN MBAPPE")
        self.assertNotContains(club, "QUIET CENTRE")
        status = self.client.get(reverse("player_database"), {"status": "FREE_AGENT"})
        self.assertContains(status, "QUIET CENTRE")
        self.assertNotContains(status, "KYLIAN MBAPPE")
        nation = self.client.get(reverse("player_database"), {"nationality": "France"})
        self.assertContains(nation, "KYLIAN MBAPPE")
        self.assertNotContains(nation, "QUIET CENTRE")
        skills = self.client.get(reverse("player_database"), {"min_skills": "5", "min_weak_foot": "4"})
        self.assertContains(skills, "KYLIAN MBAPPE")
        self.assertNotContains(skills, "QUIET CENTRE")
        foot = self.client.get(reverse("player_database"), {"preferred_foot": "Left"})
        self.assertContains(foot, "QUIET CENTRE")
        self.assertNotContains(foot, "KYLIAN MBAPPE")

    def test_pagination_preserves_filters_and_reset_clears_them(self):
        for index in range(30):
            Player.objects.create(
                name=f"Filter Clone {index:02d}",
                fc27_id=f"filter-clone-{index}",
                position="CM",
                overall=60,
                is_free_agent=True,
            )
        page_two = self.client.get(
            reverse("player_database"),
            {"search": "Filter Clone", "position": "CM", "page": "2"},
        )
        self.assertEqual(page_two.status_code, 200)
        self.assertContains(page_two, "Page 2 of")
        self.assertContains(page_two, "search=Filter+Clone")
        self.assertContains(page_two, "position=CM")
        reset = self.client.get(reverse("player_database"))
        self.assertContains(reset, "KYLIAN MBAPPE")
        self.assertContains(reset, "RESET")
        self.assertContains(reset, "PLAYER DATABASE")

    def test_direct_urls_still_work(self):
        self.assertEqual(self.client.get("/leagues/").status_code, 200)
        self.assertEqual(self.client.get("/stats/").status_code, 200)
        self.assertEqual(self.client.get("/news/activity/").status_code, 200)
        self.assertEqual(self.client.get(reverse("player_database")).status_code, 200)
        self.assertEqual(self.client.get(reverse("free_agents")).status_code, 200)
        self.assertEqual(self.client.get(reverse("player_profile", args=[self.mbappe.id])).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get("/").status_code, 200)
