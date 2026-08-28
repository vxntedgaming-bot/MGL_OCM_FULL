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
from managers.services import STARTING_TOKENS, approve_manager_application
from mgl.market import (
    close_expired_auctions,
    create_free_agent_auction,
    create_manager_auction,
    parse_auction_duration,
    place_auction_bid,
    settle_auction,
)
from mgl.models import ManagerCareerStat, ScoutReport
from mgl.scouting import (
    TIER_RANGES,
    cooldown_hours,
    dispatch_scout,
    upgrade_scout,
)
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
        self.fa = Player.objects.create(name="Free Agent Z", position="CB", overall=66, is_free_agent=True)
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_parse_duration_max_12_hours(self):
        self.assertEqual(parse_auction_duration(720), 720)
        with self.assertRaises(ValueError):
            parse_auction_duration(721)
        with self.assertRaises(ValueError):
            parse_auction_duration(24 * 60)

    def test_admin_can_auction_free_agent(self):
        self.client.login(username="owner", password="test-pass-123")
        response = self.client.post(
            reverse("auction_free_agent", args=[self.fa.id]),
            {"duration": "30", "starting_bid": "1"},
        )
        self.assertEqual(response.status_code, 302)
        auction = PlayerAuction.objects.get(player=self.fa)
        self.assertEqual(auction.listing_kind, PlayerAuction.FREE_AGENT)
        self.assertEqual(auction.status, PlayerAuction.LIVE)
        self.assertEqual(Player.objects.filter(pk=self.fa.id).count(), 1)

    def test_manager_can_only_auction_own_players(self):
        with self.assertRaises(ValueError):
            create_manager_auction(self.other, self.mgr_a, 30)
        with self.assertRaises(ValueError):
            create_manager_auction(self.fa, self.mgr_a, 30)
        auction = create_manager_auction(self.owned, self.mgr_a, 60)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertEqual(auction.origin_team_id, self.team_a.id)

    def test_manager_auction_limit_is_server_side(self):
        extras = [
            Player.objects.create(name=f"Extra {i}", position="ST", overall=64, mgl_team=self.team_a, is_free_agent=False)
            for i in range(3)
        ]
        create_manager_auction(extras[0], self.mgr_a, 30)
        create_manager_auction(extras[1], self.mgr_a, 30)
        create_manager_auction(extras[2], self.mgr_a, 30)
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
        self.assertEqual(self.mgr_a.tokens, Decimal("25.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("15.00"))
        self.assertEqual(Player.objects.filter(pk=self.owned.id).count(), 1)
        again, message = settle_auction(auction)
        self.assertIn("no longer live", message)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("25.00"))

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

    def test_unsold_free_agent_stays_free(self):
        auction = create_free_agent_auction(self.fa, self.owner, 30)
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        close_expired_auctions()
        self.fa.refresh_from_db()
        self.assertTrue(self.fa.is_free_agent)
        self.assertIsNone(self.fa.mgl_team_id)

    def test_cannot_bid_expired_or_go_negative(self):
        auction = create_free_agent_auction(self.fa, self.owner, 30)
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


class ScoutingTests(TestCase):
    def setUp(self):
        self.user = _user("scout")
        self.manager = _manager(self.user, tokens="50.00")
        self.other_user = _user("other")
        self.other = _manager(self.other_user, tokens="50.00")
        self.bronze = Player.objects.create(name="Bronze Scout Target", position="ST", overall=50, nationality="France", is_free_agent=True)
        self.silver = Player.objects.create(name="Silver Scout Target", position="CM", overall=66, nationality="Spain", is_free_agent=True)
        self.gold = Player.objects.create(name="Gold Scout Target", position="CB", overall=75, nationality="Germany", is_free_agent=True)

    def test_ranges_cooldowns_and_real_players(self):
        self.assertEqual(TIER_RANGES["BRONZE"], (45, 56))
        self.assertEqual(TIER_RANGES["SILVER"], (60, 74))
        self.assertEqual(TIER_RANGES["GOLD"], (70, 81))
        self.assertEqual(cooldown_hours("BRONZE", 0), Decimal("5"))
        self.assertEqual(cooldown_hours("BRONZE", 1), Decimal("3"))
        self.assertEqual(cooldown_hours("BRONZE", 2), Decimal("1"))
        self.assertEqual(cooldown_hours("BRONZE", 3), Decimal("2.5"))
        self.assertEqual(cooldown_hours("SILVER", 1), Decimal("8"))
        self.assertEqual(cooldown_hours("GOLD", 3), Decimal("12"))
        assignment = dispatch_scout(self.manager, "BRONZE", "France", "ST")
        self.assertEqual(assignment.player_id, self.bronze.id)
        self.assertEqual(Player.objects.filter(name="Bronze Scout Target").count(), 1)

    def test_upgrade_costs_and_insufficient_tokens(self):
        poor = _manager(_user("broke"), tokens="5.00")
        with self.assertRaises(ValueError):
            upgrade_scout(poor, "BRONZE")
        profile, level, cost = upgrade_scout(self.manager, "BRONZE")
        self.assertEqual(level, 1)
        self.assertEqual(cost, Decimal("8.00"))
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("42.00"))
        upgrade_scout(self.manager, "BRONZE")
        upgrade_scout(self.manager, "BRONZE")
        with self.assertRaises(ValueError):
            upgrade_scout(self.manager, "BRONZE")

    def test_reports_are_private(self):
        assignment = dispatch_scout(self.manager, "SILVER", "Spain", "CM")
        assignment.ready_at = timezone.now() - timedelta(minutes=1)
        assignment.save(update_fields=["ready_at"])
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.client.login(username="scout", password="test-pass-123")
        page = self.client.get(reverse("scouting"))
        self.assertContains(page, "Silver Scout Target")
        self.assertContains(page, "BRONZE")
        self.assertContains(page, "Anywhere")
        self.client.login(username="other", password="test-pass-123")
        other_page = self.client.get(reverse("scouting"))
        self.assertNotContains(other_page, "Silver Scout Target")
        self.assertEqual(ScoutReport.objects.filter(manager=self.other).count(), 0)


class StatsHubTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_sections_and_empty_state(self):
        response = self.client.get(reverse("stats_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TOP GOAL SCORERS")
        self.assertContains(response, "TOP ASSISTERS")
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
        scorer = Player.objects.create(name="Official Scorer", position="ST", overall=70, goals=3, is_free_agent=True)
        response = self.client.get(reverse("stats_page"))
        self.assertContains(response, "Official Scorer")
        self.assertContains(response, manager.display_name)
        self.assertEqual(scorer.goals, 3)
