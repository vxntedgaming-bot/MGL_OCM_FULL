from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from auctions.models import PlayerAuction, TokenTransaction
from mgl.models import RewardTransaction
from leagues.models import League
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from managers.services import STARTING_TOKENS, approve_manager_application
from mgl.market import (
    close_expired_auctions,
    create_free_agent_auction,
    create_manager_auction,
    parse_auction_duration,
    place_auction_bid,
    settle_auction,
)
from mgl.models import ManagerCareerStat, PlayerOwnershipHistory
from mgl.services import release_player, sign_free_agent
from mgl.tenure import close_club_spell_for_user, open_club_spell
from players.models import Player
from teams.models import Team
from teams.official_sl1 import OFFICIAL_SL1_SHORT_NAMES


def _user(username, role=User.MANAGER, **kwargs):
    return User.objects.create_user(username=username, password="test-pass-123", role=role, **kwargs)


def _manager(user, tokens="20.00", status=ManagerApplication.APPROVED):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=status,
        tokens=Decimal(tokens),
    )


class ManagerTokenPersistenceTests(TestCase):
    def setUp(self):
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.club_a = Team.objects.filter(short_name="ARS").first() or Team.objects.create(
            name="Arsenal", short_name="ARS", league=self.league
        )
        self.club_b = Team.objects.filter(short_name="LIV").first() or Team.objects.create(
            name="Liverpool", short_name="LIV", league=self.league
        )

    def test_new_signup_receives_20_tokens(self):
        user = _user("newbie", is_active=False)
        application = ManagerApplication.objects.create(
            user=user,
            display_name="Newbie",
            gamertag="NEW",
            status=ManagerApplication.PENDING,
        )
        self.assertEqual(application.tokens, STARTING_TOKENS)
        approve_manager_application(application, self.owner)
        application.refresh_from_db()
        self.assertEqual(application.tokens, Decimal("20.00"))

    def test_existing_manager_is_not_reset_to_20(self):
        user = _user("veteran")
        application = _manager(user, tokens="47.00")
        self.assertEqual(application.tokens, Decimal("47.00"))
        self.club_a.manager = user
        self.club_a.save(update_fields=["manager"])
        application.refresh_from_db()
        self.assertEqual(application.tokens, Decimal("47.00"))

    def test_leave_and_rejoin_keeps_spent_balance(self):
        user = _user("hopper")
        application = _manager(user, tokens="8.00")
        self.club_a.manager = user
        self.club_a.save(update_fields=["manager"])
        open_club_spell(application, self.club_a)
        self.club_a.manager = None
        self.club_a.save(update_fields=["manager"])
        close_club_spell_for_user(user, self.club_a)
        application.refresh_from_db()
        self.assertEqual(application.tokens, Decimal("8.00"))
        self.assertEqual(application.club_spells.filter(ended_at__isnull=True).count(), 0)
        self.assertEqual(application.club_spells.count(), 1)

        self.club_b.manager = user
        self.club_b.save(update_fields=["manager"])
        open_club_spell(application, self.club_b)
        application.refresh_from_db()
        self.assertEqual(application.tokens, Decimal("8.00"))
        self.assertEqual(self.club_a.tokens, Decimal("50.00"))
        self.assertEqual(self.club_b.tokens, Decimal("50.00"))


class GoalkeeperCardTests(TestCase):
    def test_card_stat_rows_switch_for_gk(self):
        from mgl.templatetags.mgl_ui import card_stat_rows

        gk = Player(position="GK", fc_gk_diving=71, fc_gk_handling=72, fc_gk_kicking=64, fc_gk_reflexes=71, fc_gk_speed=39, fc_gk_positioning=67)
        labels = [row["label"] for row in card_stat_rows(gk)]
        self.assertEqual(labels, ["DIV", "HAN", "KIC", "REF", "SPE", "POS"])
        outfield = Player(position="ST", pace=80, shooting=81, passing=70, dribbling=75, defending=40, physical=72)
        self.assertEqual(
            [row["label"] for row in card_stat_rows(outfield)],
            ["PAC", "SHO", "PAS", "DRI", "DEF", "PHY"],
        )


class LeagueStructureTests(TestCase):
    def test_active_structure_and_official_clubs(self):
        premier = ensure_premier_league()
        self.assertEqual(premier.short_name, "PL")
        self.assertEqual(premier.name, "Premier League")
        self.assertFalse(League.objects.filter(short_name="SL1", is_active=True).exists())
        self.assertEqual(
            set(League.objects.filter(is_active=True).values_list("short_name", flat=True)),
            {"PL", "CH", "L1"},
        )
        self.assertEqual(
            Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES, league=premier).count(),
            14,
        )
        self.assertEqual(Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES).count(), 14)
        mls = League.objects.create(name="MLS", short_name="MLS", season="1", is_active=True)
        Team.objects.create(name="MLS Hold", short_name="MLH", league=mls)
        ensure_premier_league()
        mls.refresh_from_db()
        self.assertFalse(mls.is_active)
        self.assertTrue(Team.objects.filter(short_name="MLH", league=mls).exists())

    def test_mls_route_is_gone(self):
        client = Client(HTTP_HOST="127.0.0.1")
        self.assertEqual(client.get("/leagues/mls/").status_code, 404)
        home = client.get("/")
        self.assertNotContains(home, reverse("competition_page", kwargs={"slug": "mls"}))


class AuctionWorkflowTests(TestCase):
    def setUp(self):
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("seller")
        self.user_b = _user("buyer")
        self.mgr_a = _manager(self.user_a, tokens="20.00")
        self.mgr_b = _manager(self.user_b, tokens="20.00")
        self.team_a = Team.objects.create(name="Alpha", short_name="ALP", league=self.league, manager=self.user_a)
        self.team_b = Team.objects.create(name="Beta", short_name="BET", league=self.league, manager=self.user_b)
        self.owned = Player.objects.create(name="Club Player", position="ST", overall=70, mgl_team=self.team_a, is_free_agent=False)
        self.other = Player.objects.create(name="Other Club", position="CM", overall=68, mgl_team=self.team_b, is_free_agent=False)
        self.unassigned = Player.objects.create(name="Unassigned Z", position="CB", overall=66, is_free_agent=False)
        self.fa = Player.objects.create(
            name="Free Agent Z",
            position="CB",
            overall=66,
            is_free_agent=True,
            released_at=timezone.now(),
        )
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_parse_duration_max_120_minutes(self):
        self.assertEqual(parse_auction_duration(120), 120)
        with self.assertRaises(ValueError):
            parse_auction_duration(180)
        with self.assertRaises(ValueError):
            parse_auction_duration(720)

    def test_admin_can_auction_unassigned_player(self):
        self.client.login(username="owner", password="test-pass-123")
        response = self.client.post(
            reverse("auction_free_agent", args=[self.unassigned.id]),
            {"duration": "30", "starting_bid": "1"},
        )
        self.assertEqual(response.status_code, 302)
        auction = PlayerAuction.objects.get(player=self.unassigned)
        self.assertEqual(auction.listing_kind, PlayerAuction.FREE_AGENT)
        self.assertEqual(auction.status, PlayerAuction.LIVE)
        self.unassigned.refresh_from_db()
        self.assertFalse(self.unassigned.is_free_agent)
        self.assertIsNone(self.unassigned.mgl_team_id)
        self.assertEqual(Player.objects.filter(pk=self.unassigned.id).count(), 1)

    def test_admin_role_can_auction_unassigned_player(self):
        admin = _user("siteadmin", role=User.ADMIN)
        self.client.login(username="siteadmin", password="test-pass-123")
        response = self.client.post(
            reverse("auction_free_agent", args=[self.unassigned.id]),
            {"duration": "60", "starting_bid": "0"},
        )
        self.assertEqual(response.status_code, 302)
        auction = PlayerAuction.objects.get(player=self.unassigned)
        self.assertEqual(auction.created_by_id, admin.id)
        self.assertEqual(auction.starting_bid, 0)
        self.assertEqual(auction.duration_minutes, 60)
        self.unassigned.refresh_from_db()
        self.assertFalse(self.unassigned.is_free_agent)
        self.assertIsNone(self.unassigned.mgl_team_id)

    def test_admin_can_auction_a_real_free_agent(self):
        self.client.login(username="owner", password="test-pass-123")
        response = self.client.post(
            reverse("auction_free_agent", args=[self.fa.id]),
            {"duration": "30", "starting_bid": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PlayerAuction.objects.filter(player=self.fa, status=PlayerAuction.LIVE).exists())
        self.fa.refresh_from_db()
        self.assertTrue(self.fa.is_free_agent)
        self.assertIsNone(self.fa.mgl_team_id)

    def test_manager_cannot_release_unassigned_player(self):
        self.client.login(username="seller", password="test-pass-123")
        before_auctions = PlayerAuction.objects.count()
        before_tokens = self.mgr_a.tokens
        response = self.client.post(
            reverse("auction_free_agent", args=[self.unassigned.id]),
            {"duration": "30", "starting_bid": "1"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(PlayerAuction.objects.count(), before_auctions)
        self.unassigned.refresh_from_db()
        self.assertFalse(self.unassigned.is_free_agent)
        self.assertIsNone(self.unassigned.mgl_team_id)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, before_tokens)

    def test_python_api_rejects_manager_unassigned_auction(self):
        with self.assertRaises(PermissionDenied):
            create_free_agent_auction(self.unassigned, self.user_a, 30)
        self.assertFalse(PlayerAuction.objects.filter(player=self.unassigned).exists())

    def test_free_agents_page_excludes_unassigned_and_hides_release(self):
        self.client.login(username="seller", password="test-pass-123")
        legacy = Player.objects.create(
            name="Legacy Unsigned",
            position="ST",
            overall=67,
            is_free_agent=True,
        )
        response = self.client.get(reverse("free_agents"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FREE AGENT Z")
        self.assertNotContains(response, "UNASSIGNED Z")
        self.assertNotContains(response, "LEGACY UNSIGNED")
        self.assertNotContains(response, "RELEASE TO AUCTION")
        self.assertContains(response, "SIGN FOR 0 TKN")
        self.assertNotContains(response, ">BUY</button>")
        self.client.logout()
        self.client.login(username="owner", password="test-pass-123")
        unassigned = self.client.get(reverse("unassigned_players"))
        self.assertContains(unassigned, "LEGACY UNSIGNED")
        self.assertContains(unassigned, "UNASSIGNED Z")
        self.assertNotContains(unassigned, "FREE AGENT Z")
        legacy.refresh_from_db()
        self.assertTrue(legacy.is_free_agent)
        self.assertIsNone(legacy.released_at)

    def test_unassigned_page_is_admin_only_and_excludes_free_agents(self):
        self.client.login(username="seller", password="test-pass-123")
        blocked = self.client.get(reverse("unassigned_players"))
        self.assertEqual(blocked.status_code, 302)
        self.client.logout()
        self.client.login(username="owner", password="test-pass-123")
        response = self.client.get(reverse("unassigned_players"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UNASSIGNED Z")
        self.assertNotContains(response, "FREE AGENT Z")
        self.assertContains(response, "RELEASE TO AUCTION")

    def test_manager_can_only_auction_own_players(self):
        with self.assertRaises(ValueError):
            create_manager_auction(self.other, self.mgr_a, 30)
        with self.assertRaises(ValueError):
            create_manager_auction(self.fa, self.mgr_a, 30)
        with self.assertRaises(ValueError):
            create_manager_auction(self.unassigned, self.mgr_a, 30)
        auction = create_manager_auction(self.owned, self.mgr_a, 60)
        self.owned.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertFalse(self.owned.is_free_agent)
        self.assertEqual(auction.origin_team_id, self.team_a.id)

    def test_manager_auction_limit_is_server_side(self):
        extras = [
            Player.objects.create(name=f"Extra {i}", position="ST", overall=64, mgl_team=self.team_a, is_free_agent=False)
            for i in range(5)
        ]
        from auctions.models import PlayerAuction
        from django.utils import timezone
        from datetime import timedelta

        for extra in extras:
            create_manager_auction(extra, self.mgr_a, 30)
            PlayerAuction.objects.filter(listed_by_manager=self.mgr_a).update(
                created_at=timezone.now() - timedelta(hours=25)
            )
        with self.assertRaises(ValueError):
            create_manager_auction(self.owned, self.mgr_a, 30)

    def test_sold_club_player_moves_tokens_and_ownership(self):
        auction = create_manager_auction(self.owned, self.mgr_a, 30, starting_bid=1)
        place_auction_bid(auction, self.mgr_b, 5)
        settle_auction(auction)
        self.owned.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_b.id)
        self.assertFalse(self.owned.is_free_agent)
        self.assertEqual(self.mgr_a.tokens, Decimal("24.90"))
        self.assertEqual(self.mgr_b.tokens, Decimal("15.00"))
        self.assertEqual(Player.objects.filter(pk=self.owned.id).count(), 1)
        again, message = settle_auction(auction)
        self.assertIn("no longer live", message)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("24.90"))

    def test_unsold_club_player_returns_home(self):
        auction = create_manager_auction(self.owned, self.mgr_a, 30)
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        close_expired_auctions()
        self.owned.refresh_from_db()
        auction.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertFalse(self.owned.is_free_agent)
        self.assertEqual(auction.status, PlayerAuction.ENDED)

    def test_unsold_unassigned_auction_becomes_free_agent(self):
        tokens_before = self.mgr_b.tokens
        tx_before = TokenTransaction.objects.count()
        auction = create_free_agent_auction(self.unassigned, self.owner, 30)
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        _, message = settle_auction(auction)
        self.assertEqual(message, "Auction ended with no bids — Player is now a Free Agent.")
        self.unassigned.refresh_from_db()
        auction.refresh_from_db()
        self.assertTrue(self.unassigned.is_free_agent)
        self.assertIsNone(self.unassigned.mgl_team_id)
        self.assertIsNone(auction.winning_manager_id)
        self.assertEqual(auction.status, PlayerAuction.ENDED)
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_b.tokens, tokens_before)
        self.assertEqual(TokenTransaction.objects.count(), tx_before)
        self.assertFalse(
            PlayerOwnershipHistory.objects.filter(player=self.unassigned, source="AUCTION").exists()
        )
        self.client.login(username="buyer", password="test-pass-123")
        page = self.client.get(reverse("free_agents"))
        self.assertContains(page, "UNASSIGNED Z")
        self.assertContains(page, "SIGN FOR 0 TKN")
        self.assertNotContains(page, ">BUY</button>")

    def test_winning_unassigned_auction_assigns_club_not_free_agent(self):
        auction = create_free_agent_auction(self.unassigned, self.owner, 30)
        place_auction_bid(auction, self.mgr_b, 4)
        settle_auction(auction)
        self.unassigned.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.unassigned.mgl_team_id, self.team_b.id)
        self.assertFalse(self.unassigned.is_free_agent)
        self.assertEqual(self.mgr_b.tokens, Decimal("16.00"))
        self.assertEqual(
            PlayerOwnershipHistory.objects.filter(
                player=self.unassigned,
                team=self.team_b,
                source="AUCTION",
            ).count(),
            1,
        )
        self.assertTrue(
            RewardTransaction.objects.filter(
                manager=self.mgr_b,
                category="MARKET",
                amount=-Decimal("4"),
            ).exists()
        )
        self.assertFalse(
            TokenTransaction.objects.filter(
                manager=self.mgr_b,
                auction=auction,
                transaction_type=TokenTransaction.DEBIT,
            ).exists()
        )
        again, _message = settle_auction(auction)
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_b.tokens, Decimal("16.00"))
        self.assertEqual(
            PlayerOwnershipHistory.objects.filter(player=self.unassigned, source="AUCTION").count(),
            1,
        )

    def test_manager_can_release_own_player_to_free_agents(self):
        from mgl.models import PlayerReleaseRequest

        self.client.login(username="seller", password="test-pass-123")
        tokens_before = self.mgr_a.tokens
        response = self.client.post(reverse("release_my_player", args=[self.owned.id]))
        self.assertEqual(response.status_code, 302)
        self.owned.refresh_from_db()
        self.assertTrue(self.owned.is_free_agent)
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertIsNotNone(self.owned.released_at)
        request_row = PlayerReleaseRequest.objects.get(player=self.owned)
        self.assertEqual(request_row.status, "APPROVED")
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, tokens_before)
        page = self.client.get(reverse("free_agents"))
        self.assertContains(page, "CLUB PLAYER")
        self.assertContains(page, "SIGN FOR 0 TKN")
        self.assertNotContains(page, ">BUY</button>")

    def test_manager_cannot_release_other_club_or_unassigned_player(self):
        self.client.login(username="seller", password="test-pass-123")
        other = self.client.post(reverse("release_my_player", args=[self.other.id]))
        self.assertEqual(other.status_code, 404)
        self.other.refresh_from_db()
        self.assertEqual(self.other.mgl_team_id, self.team_b.id)
        unassigned = self.client.post(reverse("release_my_player", args=[self.unassigned.id]))
        self.assertEqual(unassigned.status_code, 404)
        self.unassigned.refresh_from_db()
        self.assertFalse(self.unassigned.is_free_agent)
        self.assertIsNone(self.unassigned.mgl_team_id)
        with self.assertRaises(ValueError):
            release_player(self.unassigned, self.team_a)

    def test_cannot_bid_when_club_is_at_roster_limit(self):
        for index in range(30):
            Player.objects.create(
                name=f"Full {index}",
                position="ST",
                overall=64,
                mgl_team=self.team_b,
                is_free_agent=False,
            )
        auction = create_free_agent_auction(self.unassigned, self.owner, 30)
        with self.assertRaises(ValueError):
            place_auction_bid(auction, self.mgr_b, 3)
        self.unassigned.refresh_from_db()
        self.assertIsNone(self.unassigned.mgl_team_id)
        self.assertFalse(self.unassigned.is_free_agent)
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_b.tokens, Decimal("20.00"))

    def test_cannot_bid_expired_or_go_negative(self):
        auction = create_free_agent_auction(self.unassigned, self.owner, 30)
        auction.ends_at = timezone.now() - timedelta(seconds=5)
        auction.save(update_fields=["ends_at"])
        with self.assertRaises(ValueError):
            place_auction_bid(auction, self.mgr_b, 3)
        live = create_manager_auction(self.owned, self.mgr_a, 30)
        with self.assertRaises(ValueError):
            place_auction_bid(live, self.mgr_b, 50)
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_b.tokens, Decimal("20.00"))
        self.assertGreaterEqual(self.mgr_b.tokens, 0)

    def test_bid_and_settle_locks_do_not_join_nullable_fks(self):
        import inspect

        from mgl import market

        bid_src = inspect.getsource(market.place_auction_bid)
        settle_src = inspect.getsource(market.settle_auction)
        self.assertNotIn('select_related("manager", "team")', bid_src)
        self.assertNotIn("winning_manager__user", settle_src)


class FreeAgentSigningTests(TestCase):
    def setUp(self):
        self.league = ensure_premier_league()
        self.user_a = _user("arsman")
        self.user_b = _user("livman")
        self.mgr_a = _manager(self.user_a, tokens="20.00")
        self.mgr_b = _manager(self.user_b, tokens="20.00")
        self.team_a = Team.objects.create(
            name="Sign Alpha", short_name="SGA", league=self.league, manager=self.user_a
        )
        self.team_b = Team.objects.create(
            name="Sign Beta", short_name="SGB", league=self.league, manager=self.user_b
        )
        self.fa = Player.objects.create(
            name="Free Signing",
            position="ST",
            overall=66,
            is_free_agent=True,
            released_at=timezone.now(),
        )
        self.unassigned = Player.objects.create(
            name="Still Pool", position="CM", overall=65, is_free_agent=False
        )
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_manager_signs_free_agent_for_zero_tokens(self):
        tokens_before = self.mgr_a.tokens
        tx_before = TokenTransaction.objects.count()
        signed = sign_free_agent(self.fa, self.mgr_a)
        signed.refresh_from_db()
        self.mgr_a.refresh_from_db()
        self.assertEqual(signed.mgl_team_id, self.team_a.id)
        self.assertFalse(signed.is_free_agent)
        self.assertEqual(self.mgr_a.tokens, tokens_before)
        self.assertEqual(TokenTransaction.objects.count(), tx_before)
        self.assertEqual(
            PlayerOwnershipHistory.objects.filter(
                player=self.fa, team=self.team_a, source="FREE_AGENT"
            ).count(),
            1,
        )
        self.client.login(username="arsman", password="test-pass-123")
        page = self.client.get(reverse("free_agents"))
        self.assertNotContains(page, "FREE SIGNING")
        self.assertNotContains(page, "STILL POOL")

    def test_http_sign_and_second_claim_fails(self):
        self.client.login(username="arsman", password="test-pass-123")
        first = self.client.post(reverse("sign_free_agent", args=[self.fa.id]))
        self.assertEqual(first.status_code, 302)
        self.fa.refresh_from_db()
        self.assertEqual(self.fa.mgl_team_id, self.team_a.id)
        self.assertFalse(self.fa.is_free_agent)
        self.client.logout()
        self.client.login(username="livman", password="test-pass-123")
        second = self.client.post(reverse("sign_free_agent", args=[self.fa.id]))
        self.assertEqual(second.status_code, 302)
        self.fa.refresh_from_db()
        self.assertEqual(self.fa.mgl_team_id, self.team_a.id)
        self.assertEqual(Player.objects.filter(pk=self.fa.id, mgl_team=self.team_a).count(), 1)
        self.assertEqual(
            PlayerOwnershipHistory.objects.filter(player=self.fa, source="FREE_AGENT").count(),
            1,
        )
        with self.assertRaises(ValueError):
            sign_free_agent(self.fa, self.mgr_b)

    def test_cannot_sign_unassigned_or_exceed_roster(self):
        with self.assertRaises(ValueError):
            sign_free_agent(self.unassigned, self.mgr_a)
        self.unassigned.refresh_from_db()
        self.assertIsNone(self.unassigned.mgl_team_id)
        self.assertFalse(self.unassigned.is_free_agent)
        for index in range(30):
            Player.objects.create(
                name=f"Cap {index}",
                position="ST",
                overall=64,
                mgl_team=self.team_b,
                is_free_agent=False,
            )
        with self.assertRaises(ValueError):
            sign_free_agent(self.fa, self.mgr_b)
        self.fa.refresh_from_db()
        self.assertTrue(self.fa.is_free_agent)
        self.assertIsNone(self.fa.mgl_team_id)

    def test_sign_get_is_not_allowed(self):
        self.client.login(username="arsman", password="test-pass-123")
        response = self.client.get(reverse("sign_free_agent", args=[self.fa.id]))
        self.assertEqual(response.status_code, 405)
        self.fa.refresh_from_db()
        self.assertTrue(self.fa.is_free_agent)


class StatsHubTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_sections_and_empty_state(self):
        response = self.client.get(reverse("stats_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TOP GOAL SCORERS")
        self.assertContains(response, "TOP ASSISTS")
        self.assertContains(response, "TOP DEFENDERS")
        self.assertContains(response, "TOP GOALKEEPERS")
        self.assertContains(response, "TOP MANAGERS")
        self.assertContains(response, "NO STATISTICS AVAILABLE YET.")
        self.assertNotContains(response, "mgl-standings")
        self.assertNotContains(response, "class=\"mgl-standings\"")

    def test_approved_manager_stats_appear(self):
        user = _user("boss")
        manager = _manager(user)
        ManagerCareerStat.objects.create(manager=manager, wins=4, draws=1, losses=0)
        scorer = Player.objects.create(
            name="Typed Scorer",
            position="ST",
            overall=70,
            goals=3,
            is_free_agent=True,
        )
        response = self.client.get(reverse("stats_page"))
        self.assertNotContains(response, "Typed Scorer")
        self.assertContains(response, manager.display_name)
        self.assertEqual(scorer.goals, 3)


class ControlCentreFreeAgentFilterTests(TestCase):
    def setUp(self):
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.club = Team.objects.filter(short_name="ARS").first() or Team.objects.create(
            name="Arsenal", short_name="ARS", league=self.league
        )
        self.low = Player.objects.create(name="Filter Low", position="CB", overall=55, is_free_agent=False)
        self.floor = Player.objects.create(name="Filter Floor", position="CM", overall=62, is_free_agent=False)
        self.mid = Player.objects.create(name="Filter Mid", position="ST", overall=70, is_free_agent=False)
        self.high = Player.objects.create(name="Filter High", position="ST", overall=71, is_free_agent=False)
        self.star = Player.objects.create(name="Filter Star", position="ST", overall=88, is_free_agent=False)
        self.fa = Player.objects.create(
            name="Filter Free Agent",
            position="ST",
            overall=66,
            is_free_agent=True,
            released_at=timezone.now(),
        )
        self.assigned = Player.objects.create(
            name="Filter Assigned",
            position="CM",
            overall=66,
            is_free_agent=False,
            mgl_team=self.club,
        )
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.client.login(username="owner", password="test-pass-123")

    def _snapshot(self):
        return list(
            Player.objects.order_by("id").values_list(
                "id", "name", "overall", "is_free_agent", "mgl_team_id"
            )
        )

    def test_default_filter_is_62_70_and_does_not_mutate_players(self):
        before = self._snapshot()
        response = self.client.get(reverse("control_auctions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MANAGER AUCTIONS")
        self.assertContains(response, "LEAGUE OFFICE AUCTIONS")
        self.assertContains(response, "62–70 OVR")
        self.assertContains(response, self.floor.name)
        self.assertContains(response, self.mid.name)
        self.assertNotContains(response, self.low.name)
        self.assertNotContains(response, self.high.name)
        self.assertNotContains(response, self.star.name)
        self.assertNotContains(response, self.assigned.name)
        self.assertNotContains(response, self.fa.name)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(Player.objects.filter(is_free_agent=True).count(), 1)
        self.assertEqual(Player.objects.filter(is_free_agent=False, mgl_team__isnull=True).count(), 5)
        self.assertEqual(self.assigned.overall, 66)

    def test_all_71_plus_and_under_62_filters_are_selection_only(self):
        before = self._snapshot()
        all_view = self.client.get(reverse("control_auctions"), {"ovr": "all"})
        self.assertContains(all_view, self.star.name)
        self.assertContains(all_view, self.low.name)
        self.assertContains(all_view, self.mid.name)
        self.assertNotContains(all_view, self.assigned.name)
        self.assertNotContains(all_view, self.fa.name)

        plus = self.client.get(reverse("control_auctions"), {"ovr": "71-plus"})
        self.assertContains(plus, self.high.name)
        self.assertContains(plus, self.star.name)
        self.assertNotContains(plus, self.mid.name)
        self.assertNotContains(plus, self.low.name)
        plus_alias = self.client.get(reverse("control_auctions"), {"ovr": "71+"})
        self.assertContains(plus_alias, self.star.name)
        self.assertNotContains(plus_alias, self.mid.name)

        under = self.client.get(reverse("control_auctions"), {"ovr": "under-62"})
        self.assertContains(under, self.low.name)
        self.assertNotContains(under, self.floor.name)
        self.assertNotContains(under, self.star.name)

        unknown = self.client.get(reverse("control_auctions"), {"ovr": "invented"})
        self.assertContains(unknown, self.mid.name)
        self.assertNotContains(unknown, self.star.name)
        self.assertEqual(self._snapshot(), before)

    def test_auction_from_62_70_filter_uses_existing_auction_system(self):
        before_ratings = list(Player.objects.order_by("id").values_list("id", "overall", "is_free_agent"))
        next_url = reverse("control_auctions") + "?ovr=62-70"
        response = self.client.post(
            reverse("auction_free_agent", args=[self.mid.id]),
            {
                "duration": "30",
                "starting_bid": "1",
                "ovr": "62-70",
                "next": next_url,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("ovr=62-70", response["Location"])
        auction = PlayerAuction.objects.get(player=self.mid)
        self.assertEqual(auction.listing_kind, PlayerAuction.FREE_AGENT)
        self.assertEqual(auction.status, PlayerAuction.LIVE)
        self.assertEqual(auction.starting_bid, 1)
        self.assertEqual(auction.duration_minutes, 30)
        self.assertIsNone(auction.listed_by_manager_id)
        after = list(Player.objects.order_by("id").values_list("id", "overall", "is_free_agent"))
        self.assertEqual(after, before_ratings)
        self.assertEqual(Player.objects.filter(pk=self.mid.id).count(), 1)
