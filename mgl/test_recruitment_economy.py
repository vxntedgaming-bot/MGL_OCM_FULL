from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from managers.models import ManagerApplication
from mgl.market import (
    close_expired_auctions,
    create_free_agent_auction,
    create_manager_auction,
    place_auction_bid,
    settle_auction,
)
from mgl.models import (
    LeagueSettings,
    RecruitmentOpening,
    RecruitmentPack,
    RewardTransaction,
    ScoutAssignment,
    ScoutLevelConfig,
)
from mgl.player_state import enter_ufl_free_agency, free_agents, is_ufl_free_agent, unassigned_players
from mgl.recruitment import (
    choose_recruitment_player,
    open_recruitment_pack,
    pack_by_code,
    save_recruitment_pack,
)
from mgl.scouting import (
    choose_scout_player,
    complete_ready_assignments,
    cooldown_hours,
    dispatch_scout,
    save_scout_level_config,
    upgrade_scout,
)
from mgl.services import sign_free_agent
from mgl.tokens import MANAGER_AUCTION_LISTING_FEE, validate_token_amount
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(username=username, password="test-pass-123", role=role)


def _manager(user, tokens="20.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


def _league():
    return League.objects.create(name="Economy League", short_name="ECO", season="1")


def _club(user, league, name="Economy FC", short="ECO"):
    return Team.objects.create(name=name, short_name=short, league=league, manager=user)


def _unsigned(**kwargs):
    defaults = {
        "name": "Unsigned One",
        "position": "ST",
        "overall": 68,
        "is_free_agent": False,
        "mgl_team": None,
        "released_at": None,
    }
    defaults.update(kwargs)
    return Player.objects.create(**defaults)


class TokenRuleTests(TestCase):
    def test_half_steps_are_valid(self):
        for amount in ("0", "0.5", "1", "1.5", "2", "2.5", "3"):
            self.assertEqual(validate_token_amount(amount), Decimal(amount))

    def test_invalid_increments_rejected(self):
        for amount in ("0.25", "0.75", "1.25", "0.1"):
            with self.assertRaises(ValueError):
                validate_token_amount(amount)

    def test_listing_fee_exception(self):
        self.assertEqual(
            validate_token_amount("0.1", allow_listing_fee=True),
            MANAGER_AUCTION_LISTING_FEE,
        )


class RecruitmentEconomyTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.owner_user = _user("eco-owner", User.OWNER)
        self.admin_user = _user("eco-admin", User.ADMIN)
        self.mgr_user = _user("eco-mgr")
        self.other_user = _user("eco-other")
        self.member_user = _user("eco-member")
        self.owner = _manager(self.owner_user, "50.00")
        self.admin = _manager(self.admin_user, "50.00")
        self.manager = _manager(self.mgr_user, "10.00")
        self.other = _manager(self.other_user, "10.00")
        self.team = _club(self.mgr_user, self.league)
        self.other_team = _club(self.other_user, self.league, "Other FC", "OTH")
        for index in range(8):
            _unsigned(name=f"Unsigned ST {index}", position="ST", overall=70 + (index % 4), fc27_id=f"st{index}")
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_admin_can_configure_pack(self):
        pack = save_recruitment_pack(
            actor=self.admin_user,
            code="LOW",
            name="Low Rated ST",
            token_cost="1.5",
            result_count=3,
            select_count=1,
            min_ovr=60,
            max_ovr=69,
            positions="ST CF",
            opening_limit=2,
        )
        pack.refresh_from_db()
        self.assertEqual(pack.token_cost, Decimal("1.50"))
        self.assertEqual(pack.opening_limit, 2)
        self.assertEqual(pack.positions, ["ST", "CF"])

    def test_manager_cannot_configure_pack(self):
        with self.assertRaises(ValueError):
            save_recruitment_pack(
                actor=self.mgr_user,
                code="HACK",
                name="Hacked pack",
                token_cost="0",
            )

    def test_inactive_pack_cannot_be_opened(self):
        pack = pack_by_code("ST")
        pack.active = False
        pack.save(update_fields=["active"])
        with self.assertRaises(ValueError):
            open_recruitment_pack(self.mgr_user, "ST")
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("10.00"))

    def test_default_pack_returns_three_and_choose_one(self):
        opening = open_recruitment_pack(self.mgr_user, "ST")
        self.assertEqual(len(opening.player_ids), 3)
        self.assertEqual(len(set(opening.player_ids)), 3)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("9.00"))
        ledger = RewardTransaction.objects.filter(reference=f"recruitment:open:{opening.pk}")
        self.assertEqual(ledger.count(), 1)
        self.assertEqual(ledger.get().amount, Decimal("-1.00"))
        chosen_id = opening.player_ids[0]
        others = opening.player_ids[1:]
        choose_recruitment_player(self.mgr_user, opening.id, chosen_id)
        chosen = Player.objects.get(pk=chosen_id)
        self.assertEqual(chosen.mgl_team_id, self.team.id)
        self.assertIsNone(chosen.released_at)
        for pk in others:
            other = Player.objects.get(pk=pk)
            self.assertIsNone(other.mgl_team_id)
            self.assertIsNone(other.released_at)
            self.assertFalse(is_ufl_free_agent(other))
        with self.assertRaises(ValueError):
            choose_recruitment_player(self.mgr_user, opening.id, chosen_id)

    def test_opening_limit_enforced(self):
        pack = pack_by_code("ST")
        pack.opening_limit = 1
        pack.save(update_fields=["opening_limit"])
        opening = open_recruitment_pack(self.mgr_user, "ST")
        choose_recruitment_player(self.mgr_user, opening.id, opening.player_ids[0])
        with self.assertRaises(ValueError):
            open_recruitment_pack(self.mgr_user, "ST")

    def test_insufficient_tokens_rejected(self):
        self.manager.tokens = Decimal("0.50")
        self.manager.save(update_fields=["tokens"])
        with self.assertRaises(ValueError):
            open_recruitment_pack(self.mgr_user, "ST")
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("0.50"))
        self.assertEqual(RecruitmentOpening.objects.count(), 0)

    def test_repeated_open_does_not_double_charge(self):
        open_recruitment_pack(self.mgr_user, "ST")
        with self.assertRaises(ValueError):
            open_recruitment_pack(self.mgr_user, "ST")
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("9.00"))
        self.assertEqual(RecruitmentOpening.objects.filter(manager=self.manager).count(), 1)

    def test_two_managers_cannot_claim_same_player(self):
        first = open_recruitment_pack(self.mgr_user, "ST")
        second = open_recruitment_pack(self.other_user, "ST")
        shared = set(first.player_ids) & set(second.player_ids)
        self.assertFalse(shared)
        choose_recruitment_player(self.mgr_user, first.id, first.player_ids[0])
        with self.assertRaises(ValueError):
            choose_recruitment_player(self.other_user, second.id, first.player_ids[0])

    def test_invalid_pack_cost_rejected(self):
        with self.assertRaises(ValueError):
            save_recruitment_pack(
                actor=self.owner_user,
                code="BAD",
                name="Bad cost",
                token_cost="0.25",
            )


class ScoutingEconomyTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.owner_user = _user("scout-owner", User.OWNER)
        self.mgr_user = _user("scout-mgr")
        self.other_user = _user("scout-other")
        self.manager = _manager(self.mgr_user, "80.00")
        self.other = _manager(self.other_user, "80.00")
        self.team = _club(self.mgr_user, self.league, "Scout A", "SCA")
        self.other_team = _club(self.other_user, self.league, "Scout B", "SCB")
        for index in range(8):
            _unsigned(
                name=f"Bronze ST {index}",
                position="ST",
                overall=50 + (index % 5),
                nationality="Brazil",
                fc27_id=f"br{index}",
            )
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_scout_starts_with_server_duration(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        wait = cooldown_hours("BRONZE", 1)
        self.assertEqual(assignment.status, ScoutAssignment.PENDING)
        self.assertAlmostEqual(
            (assignment.ready_at - assignment.started_at).total_seconds(),
            float(wait) * 3600,
            delta=3,
        )
        self.assertEqual(assignment.player_ids, [])

    def test_cannot_complete_early(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        ready, _ = complete_ready_assignments(self.manager)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, ScoutAssignment.PENDING)
        self.assertEqual(ready, [])
        with self.assertRaises(ValueError):
            choose_scout_player(self.manager, assignment.id, 1)

    def test_completed_scout_returns_four_choose_one(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        assignment.ready_at = timezone.now() - timedelta(seconds=5)
        assignment.save(update_fields=["ready_at"])
        from mgl.scouting import complete_ready_assignments

        complete_ready_assignments(self.manager)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, ScoutAssignment.READY)
        self.assertEqual(len(assignment.player_ids), 4)
        self.assertEqual(len(set(assignment.player_ids)), 4)
        chosen_id = assignment.player_ids[0]
        others = assignment.player_ids[1:]
        choose_scout_player(self.manager, assignment.id, chosen_id)
        chosen = Player.objects.get(pk=chosen_id)
        self.assertEqual(chosen.mgl_team_id, self.team.id)
        for pk in others:
            other = Player.objects.get(pk=pk)
            self.assertIsNone(other.mgl_team_id)
            self.assertIsNone(other.released_at)
        with self.assertRaises(ValueError):
            choose_scout_player(self.manager, assignment.id, others[0])

    def test_levels_and_upgrade_costs(self):
        profile, level, cost = upgrade_scout(self.manager)
        self.assertEqual(level, 2)
        self.assertEqual(cost, Decimal("18.00"))
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("62.00"))
        self.assertEqual(
            RewardTransaction.objects.filter(reference=f"scout:upgrade:{self.manager.id}:2").count(),
            1,
        )
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        self.assertEqual(cooldown_hours("BRONZE", 2), Decimal("4"))
        self.assertAlmostEqual(
            (assignment.ready_at - assignment.started_at).total_seconds(),
            4 * 3600,
            delta=3,
        )
        upgrade_scout(self.manager)
        upgrade_scout(self.manager)
        with self.assertRaises(ValueError):
            upgrade_scout(self.manager)
        self.assertEqual(profile.__class__.objects.get(manager=self.manager).scout_level, 4)

    def test_upgrade_reduces_pending_duration(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        original_ready = assignment.ready_at
        upgrade_scout(self.manager)
        assignment.refresh_from_db()
        self.assertLess(assignment.ready_at, original_ready)
        self.assertEqual(assignment.level, 2)

    def test_configured_percent_reduces_hours(self):
        save_scout_level_config(
            actor=_user("cfg-owner", User.OWNER),
            level=1,
            time_reduction_percent="50",
        )
        hours = cooldown_hours("BRONZE", 1)
        self.assertEqual(hours, Decimal("3"))

    def test_manager_cannot_edit_scout_config(self):
        with self.assertRaises(ValueError):
            save_scout_level_config(actor=self.mgr_user, level=2, upgrade_cost="0")

    def test_insufficient_upgrade_tokens(self):
        self.manager.tokens = Decimal("1.00")
        self.manager.save(update_fields=["tokens"])
        with self.assertRaises(ValueError):
            upgrade_scout(self.manager)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("1.00"))

    def test_repeated_upgrade_does_not_double_charge(self):
        upgrade_scout(self.manager)
        first_balance = ManagerApplication.objects.get(pk=self.manager.pk).tokens
        from mgl.services import debit_manager

        debit_manager(
            self.manager,
            Decimal("18.00"),
            "repeat",
            category="SCOUTING",
            reference=f"scout:upgrade:{self.manager.id}:2",
        )
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, first_balance)


class FreeAgentEconomyTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.user = _user("fa-mgr")
        self.manager = _manager(self.user, "8.00")
        self.team = _club(self.user, self.league)
        self.unsigned = _unsigned(name="Pool Unsigned", position="ST", overall=71, is_free_agent=True)
        self.genuine = _unsigned(name="Genuine FA", position="CM", overall=72, is_free_agent=False)
        enter_ufl_free_agency(self.genuine)
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_unsigned_and_legacy_flag_do_not_appear(self):
        names = list(free_agents().values_list("name", flat=True))
        self.assertIn("Genuine FA", names)
        self.assertNotIn("Pool Unsigned", names)
        self.client.login(username="fa-mgr", password="test-pass-123")
        page = self.client.get(reverse("free_agents"))
        self.assertContains(page, "Genuine FA")
        self.assertNotContains(page, "Pool Unsigned")
        self.assertContains(page, "0 TOKENS")

    def test_sign_costs_zero_and_removes_from_pool(self):
        before = self.manager.tokens
        signed = sign_free_agent(self.genuine, self.manager)
        self.manager.refresh_from_db()
        self.genuine.refresh_from_db()
        self.assertEqual(signed.mgl_team_id, self.team.id)
        self.assertIsNone(self.genuine.released_at)
        self.assertEqual(self.manager.tokens, before)
        self.assertNotIn(self.genuine, free_agents())
        with self.assertRaises(ValueError):
            sign_free_agent(self.genuine, self.manager)
        with self.assertRaises(ValueError):
            sign_free_agent(self.unsigned, self.manager)


class AuctionEconomyTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.owner_user = _user("auc-owner", User.OWNER)
        self.seller_user = _user("auc-seller")
        self.buyer_user = _user("auc-buyer")
        self.seller = _manager(self.seller_user, "10.00")
        self.buyer = _manager(self.buyer_user, "10.00")
        self.team_a = _club(self.seller_user, self.league, "Seller FC", "SEL")
        self.team_b = _club(self.buyer_user, self.league, "Buyer FC", "BUY")
        self.owned = _unsigned(name="Club ST", position="ST", overall=74, mgl_team=self.team_a)
        self.other = _unsigned(name="Other ST", position="ST", overall=70, mgl_team=self.team_b)
        self.unsigned = _unsigned(name="Admin Auction ST", position="ST", overall=66)
        self.fa = _unsigned(name="Already FA", position="CM", overall=67)
        enter_ufl_free_agency(self.fa)

    def test_manager_can_only_auction_own_player(self):
        with self.assertRaises(ValueError):
            create_manager_auction(self.other, self.seller, 30)
        with self.assertRaises(ValueError):
            create_manager_auction(self.unsigned, self.seller, 30)
        with self.assertRaises(ValueError):
            create_manager_auction(self.fa, self.seller, 30)

    def test_listing_fee_is_point_one_once_and_not_refunded(self):
        before = self.seller.tokens
        auction = create_manager_auction(self.owned, self.seller, 30, starting_bid=0)
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.tokens, before - MANAGER_AUCTION_LISTING_FEE)
        self.assertEqual(
            RewardTransaction.objects.filter(reference=f"auction:list:{auction.pk}").count(),
            1,
        )
        with self.assertRaises(ValueError):
            create_manager_auction(self.owned, self.seller, 30, starting_bid=0)
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.tokens, before - MANAGER_AUCTION_LISTING_FEE)
        self.owned.refresh_from_db()
        self.assertIsNone(self.owned.mgl_team_id)
        self.assertEqual(auction.origin_team_id, self.team_a.id)
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        close_expired_auctions()
        self.owned.refresh_from_db()
        self.seller.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_a.id)
        self.assertFalse(is_ufl_free_agent(self.owned))
        self.assertEqual(self.seller.tokens, before - MANAGER_AUCTION_LISTING_FEE)

    def test_sold_player_transfers(self):
        auction = create_manager_auction(self.owned, self.seller, 30, starting_bid=1)
        place_auction_bid(auction, self.buyer, 4)
        settle_auction(auction)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.mgl_team_id, self.team_b.id)
        self.seller.refresh_from_db()
        self.buyer.refresh_from_db()
        self.assertEqual(self.seller.tokens, Decimal("13.90"))
        self.assertEqual(self.buyer.tokens, Decimal("6.00"))

    def test_admin_unsigned_no_bid_becomes_genuine_fa(self):
        auction = create_free_agent_auction(self.unsigned, self.owner_user, 30)
        auction.ends_at = timezone.now() - timedelta(minutes=1)
        auction.save(update_fields=["ends_at"])
        close_expired_auctions()
        self.unsigned.refresh_from_db()
        self.assertTrue(is_ufl_free_agent(self.unsigned))
        self.assertIsNone(self.unsigned.mgl_team_id)
        self.assertIn(self.unsigned, free_agents())


class EconomyPermissionTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.member = _user("perm-member")
        self.mgr_user = _user("perm-mgr")
        self.other_user = _user("perm-other")
        self.manager = _manager(self.mgr_user, "10.00")
        self.other = _manager(self.other_user, "10.00")
        self.team = _club(self.mgr_user, self.league)
        self.other_team = _club(self.other_user, self.league, "Perm B", "PMB")
        self.owned = _unsigned(name="Perm ST", position="ST", overall=70, mgl_team=self.team)
        for index in range(4):
            _unsigned(name=f"Perm Pool {index}", position="ST", overall=68, fc27_id=f"pp{index}")
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_member_cannot_open_pack_or_auction(self):
        self.client.login(username="perm-member", password="test-pass-123")
        pack = self.client.post(reverse("open_recruitment_pack"), {"pack_code": "ST"})
        self.assertEqual(pack.status_code, 302)
        self.assertEqual(RecruitmentOpening.objects.count(), 0)
        auction = self.client.post(
            reverse("list_player_for_auction", args=[self.owned.id]),
            {"duration": "30", "starting_bid": "1"},
        )
        self.assertEqual(auction.status_code, 302)
        self.assertEqual(PlayerAuction.objects.count(), 0)

    def test_manager_cannot_open_control_or_award_tokens(self):
        self.client.login(username="perm-mgr", password="test-pass-123")
        packs = self.client.get(reverse("control_recruitment"))
        self.assertEqual(packs.status_code, 302)
        scout = self.client.get(reverse("control_scout_config"))
        self.assertEqual(scout.status_code, 302)
        tokens = self.client.post(
            reverse("control_adjust_tokens"),
            {"manager_id": str(self.manager.id), "amount": "50", "reason": "self"},
        )
        self.assertEqual(tokens.status_code, 302)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("10.00"))

    def test_manager_cannot_operate_other_club(self):
        self.client.login(username="perm-other", password="test-pass-123")
        response = self.client.post(
            reverse("list_player_for_auction", args=[self.owned.id]),
            {"duration": "30", "starting_bid": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PlayerAuction.objects.count(), 0)

    def test_csrf_still_required(self):
        csrf = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        csrf.login(username="perm-mgr", password="test-pass-123")
        response = csrf.post(reverse("open_recruitment_pack"), {"pack_code": "ST"})
        self.assertEqual(response.status_code, 403)
