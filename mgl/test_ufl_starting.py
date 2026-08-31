from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from managers.models import ManagerApplication
from mgl.models import DiscordEvent, NewsPost, PlayerListing, SiteChangeLog, StartingSquadLock, StartingSquadProposal
from mgl.ufl_settings import (
    OFFICIAL_STARTING_SQUAD_SIZE,
    UFL_SQUAD_SHAPE,
    official_starting_structure,
)
from mgl.ufl_starting import (
    OFFICIAL_STRUCTURE,
    PLAYERS_PER_CLUB,
    SHAPE_COUNTS,
    ProposedPlayer,
    approve_proposal,
    create_proposal,
    eligible_queryset,
    generate_allocation,
    squads_from_payload,
    validate_allocation,
)

OFFICIAL_COUNTS = {
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
}
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
    return League.objects.create(name="UFL Start", short_name="UFLS", season="1")


def _club(user, league, name, short):
    return Team.objects.create(name=name, short_name=short, league=league, manager=user, tokens=Decimal("50.00"))


def _player(**kwargs):
    defaults = {
        "name": "Pool Player",
        "position": "ST",
        "overall": 66,
        "nationality": "England",
        "is_free_agent": False,
        "mgl_team": None,
        "fc27_id": kwargs.get("fc27_id") or f"fc-{kwargs.get('name', 'x')}-{kwargs.get('position', 'ST')}",
    }
    defaults.update(kwargs)
    if "fc27_id" not in kwargs:
        defaults["fc27_id"] = f"fc-{defaults['name']}-{defaults['position']}-{defaults['overall']}"
    return Player.objects.create(**defaults)


def _fill_pool(prefix="P", extras=2, club_count=None):
    created = []
    n = 0
    clubs = club_count if club_count is not None else max(2, Team.objects.count())
    for position, count in UFL_SQUAD_SHAPE:
        for index in range(count * clubs + extras):
            n += 1
            ovr = 64 + (n % 6)
            created.append(
                _player(
                    name=f"{prefix} {position} {index}",
                    position=position,
                    overall=ovr,
                    fc27_id=f"fc-{prefix}-{position}-{index}",
                )
            )
    return created


class StartingGeneratorTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.owner = _user("start-owner", User.OWNER)
        self.admin = _user("start-admin", User.ADMIN)
        self.manager_user = _user("start-mgr")
        self.manager = _manager(self.manager_user)
        self.other = _user("start-mgr-b")
        _manager(self.other)
        self.club_a = _club(self.manager_user, self.league, "Alpha FC", "ALF")
        self.club_b = _club(self.other, self.league, "Beta FC", "BET")
        self.pool = _fill_pool()
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_shape_is_exactly_25(self):
        self.assertEqual(PLAYERS_PER_CLUB, 25)
        self.assertEqual(OFFICIAL_STARTING_SQUAD_SIZE, 25)
        self.assertEqual(sum(count for _pos, count in UFL_SQUAD_SHAPE), 25)
        self.assertEqual(sum(SHAPE_COUNTS.values()), 25)
        self.assertEqual(SHAPE_COUNTS, OFFICIAL_COUNTS)
        self.assertEqual(OFFICIAL_STRUCTURE, official_starting_structure())
        self.assertEqual(
            [(slot["code"], slot["required"]) for slot in official_starting_structure()],
            list(OFFICIAL_COUNTS.items()),
        )
        self.assertEqual(SHAPE_COUNTS["GK"], 2)
        self.assertEqual(SHAPE_COUNTS["CB"], 5)
        self.assertEqual(SHAPE_COUNTS["RB"], 1)
        self.assertEqual(SHAPE_COUNTS["LB"], 1)
        self.assertEqual(SHAPE_COUNTS["RWB"], 1)
        self.assertEqual(SHAPE_COUNTS["LWB"], 1)
        self.assertEqual(SHAPE_COUNTS["CM"], 3)
        self.assertEqual(SHAPE_COUNTS["CDM"], 2)
        self.assertEqual(SHAPE_COUNTS["CAM"], 2)
        self.assertEqual(SHAPE_COUNTS["RM"], 1)
        self.assertEqual(SHAPE_COUNTS["LM"], 1)
        self.assertEqual(SHAPE_COUNTS["RW"], 1)
        self.assertEqual(SHAPE_COUNTS["LW"], 1)
        self.assertEqual(SHAPE_COUNTS["ST"], 3)

    def test_generate_does_not_assign_or_touch_fc26(self):
        before = list(Player.objects.order_by("id").values_list("id", "fc27_id", "overall", "name", "mgl_team_id"))
        tokens = self.manager.tokens
        proposal = create_proposal(self.owner, seed=20260831, clubs=[self.club_a, self.club_b])
        self.assertEqual(proposal.status, StartingSquadProposal.DRAFT)
        after = list(Player.objects.order_by("id").values_list("id", "fc27_id", "overall", "name", "mgl_team_id"))
        self.assertEqual(before, after)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, tokens)
        self.assertFalse(NewsPost.objects.exists())
        self.assertFalse(DiscordEvent.objects.exists())
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)

    def test_generated_squads_are_valid_and_balanced(self):
        proposal = create_proposal(self.owner, seed=11, clubs=[self.club_a, self.club_b])
        self.assertTrue(proposal.validation["ok"], proposal.validation)
        clubs = proposal.payload["clubs"]
        self.assertEqual(len(clubs), 2)
        ids = []
        for club in clubs:
            self.assertEqual(len(club["players"]), 25)
            self.assertEqual(club["position_counts"], OFFICIAL_COUNTS)
            self.assertEqual(club["position_counts"]["GK"], 2)
            self.assertEqual(club["position_counts"]["CB"], 5)
            self.assertEqual(club["position_counts"]["RB"], 1)
            self.assertEqual(club["position_counts"]["LB"], 1)
            self.assertEqual(club["position_counts"]["RWB"], 1)
            self.assertEqual(club["position_counts"]["LWB"], 1)
            self.assertEqual(club["position_counts"]["CM"], 3)
            self.assertEqual(club["position_counts"]["CDM"], 2)
            self.assertEqual(club["position_counts"]["CAM"], 2)
            self.assertEqual(club["position_counts"]["RM"], 1)
            self.assertEqual(club["position_counts"]["LM"], 1)
            self.assertEqual(club["position_counts"]["RW"], 1)
            self.assertEqual(club["position_counts"]["LW"], 1)
            self.assertEqual(club["position_counts"]["ST"], 3)
            ovrs = [row["overall"] for row in club["players"]]
            self.assertGreaterEqual(min(ovrs), 64)
            self.assertLessEqual(max(ovrs), 69)
            ids.extend(row["id"] for row in club["players"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(float(proposal.largest_avg_diff), 1.5)

    def test_wrong_structure_fails_validation_and_cannot_be_approved(self):
        proposal = create_proposal(self.owner, seed=17, clubs=[self.club_a, self.club_b])
        squads = squads_from_payload(proposal.payload)
        cb = next(player for player in squads[0].players if player.position == "CB")
        squads[0].players[squads[0].players.index(cb)] = ProposedPlayer(
            id=cb.id,
            fc27_id=cb.fc27_id,
            name=cb.name,
            position="ST",
            overall=cb.overall,
        )
        result = validate_allocation(squads)
        self.assertFalse(result["ok"])
        shape = next(check for check in result["checks"] if check["key"] == "shape")
        self.assertFalse(shape["ok"])
        self.assertIn("CB 5 / 5", shape["detail"])
        self.assertTrue(any("CB 4 / 5" in problem for problem in result["problems"]))
        self.assertTrue(any("ST 4 / 3" in problem for problem in result["problems"]))

        payload = proposal.payload
        payload["clubs"][0]["players"] = [player.as_dict() for player in squads[0].players]
        proposal.payload = payload
        proposal.save(update_fields=["payload"])
        with self.assertRaisesMessage(ValueError, "stale"):
            approve_proposal(proposal, self.owner, confirm=True)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, StartingSquadProposal.DRAFT)
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)

    def test_random_seed_changes_allocation(self):
        first = create_proposal(self.owner, seed=1, clubs=[self.club_a, self.club_b])
        second = create_proposal(self.owner, seed=99, clubs=[self.club_a, self.club_b])
        a = [row["id"] for row in first.payload["clubs"][0]["players"]]
        b = [row["id"] for row in second.payload["clubs"][0]["players"]]
        self.assertNotEqual(a, b)
        self.assertEqual(StartingSquadProposal.objects.filter(status=StartingSquadProposal.SUPERSEDED).count(), 1)
        self.assertEqual(StartingSquadProposal.objects.filter(status=StartingSquadProposal.DRAFT).count(), 1)

    def test_same_seed_reproduces(self):
        first = generate_allocation(seed=42, clubs=[self.club_a, self.club_b])
        second = generate_allocation(seed=42, clubs=[self.club_a, self.club_b])
        self.assertEqual(
            [player.id for player in first["clubs"][0].players],
            [player.id for player in second["clubs"][0].players],
        )

    def test_eligibility_excludes_owned_fa_auction_and_listing(self):
        owned = _player(name="Already Owned", position="ST", overall=66, fc27_id="fc-owned", mgl_team=self.club_a)
        fa = _player(name="Free Agent", position="ST", overall=66, fc27_id="fc-fa", is_free_agent=True)
        auctioned = _player(name="On Auction", position="ST", overall=66, fc27_id="fc-auc")
        PlayerAuction.objects.create(
            player=auctioned,
            listing_kind=PlayerAuction.FREE_AGENT,
            status=PlayerAuction.LIVE,
            duration_minutes=30,
        )
        listed = _player(name="Listed", position="ST", overall=66, fc27_id="fc-list")
        PlayerListing.objects.create(
            player=listed,
            team=self.club_a,
            seller=self.manager,
            asking_price=Decimal("3.00"),
            status=PlayerListing.LIVE,
        )
        low = _player(name="Too Low", position="ST", overall=63, fc27_id="fc-low")
        high = _player(name="Too High", position="ST", overall=70, fc27_id="fc-high")
        ids = set(eligible_queryset().values_list("id", flat=True))
        self.assertNotIn(owned.id, ids)
        self.assertNotIn(fa.id, ids)
        self.assertNotIn(auctioned.id, ids)
        self.assertNotIn(listed.id, ids)
        self.assertNotIn(low.id, ids)
        self.assertNotIn(high.id, ids)
        self.assertIn(fa.id, set(eligible_queryset(include_free_agents=True).values_list("id", flat=True)))

    def test_owner_approval_assigns_atomically_and_emits_news(self):
        proposal = create_proposal(self.owner, seed=7, clubs=[self.club_a, self.club_b])
        tokens = self.manager.tokens
        snapshot = list(Player.objects.values_list("fc27_id", "overall", "name"))
        approved = approve_proposal(proposal, self.owner, confirm=True)
        self.assertEqual(approved.status, StartingSquadProposal.APPROVED)
        self.assertEqual(Player.objects.filter(mgl_team=self.club_a).count(), 25)
        self.assertEqual(Player.objects.filter(mgl_team=self.club_b).count(), 25)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, tokens)
        self.assertEqual(
            list(Player.objects.values_list("fc27_id", "overall", "name")),
            snapshot,
        )
        self.assertTrue(StartingSquadLock.objects.filter(proposal=approved).exists())
        self.assertTrue(NewsPost.objects.filter(title="UFL STARTING SQUADS ALLOCATED").exists())
        self.assertTrue(DiscordEvent.objects.filter(news_post__title="UFL STARTING SQUADS ALLOCATED").exists())
        self.assertTrue(SiteChangeLog.objects.filter(action="starting_squads.approve").exists())

    def test_approval_requires_owner_and_confirmation(self):
        proposal = create_proposal(self.owner, seed=3, clubs=[self.club_a, self.club_b])
        with self.assertRaisesMessage(ValueError, "Only the Owner"):
            approve_proposal(proposal, self.admin, confirm=True)
        with self.assertRaisesMessage(ValueError, "explicit confirmation"):
            approve_proposal(proposal, self.owner, confirm=False)
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)
        self.assertFalse(NewsPost.objects.exists())

    def test_stale_player_aborts_approval(self):
        proposal = create_proposal(self.owner, seed=5, clubs=[self.club_a, self.club_b])
        first_id = proposal.payload["clubs"][0]["players"][0]["id"]
        stolen = Player.objects.get(pk=first_id)
        stolen.mgl_team = self.club_a
        stolen.save(update_fields=["mgl_team"])
        with self.assertRaisesMessage(ValueError, "stale"):
            approve_proposal(proposal, self.owner, confirm=True)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, StartingSquadProposal.DRAFT)
        self.assertEqual(Player.objects.exclude(pk=first_id).filter(mgl_team__isnull=False).count(), 0)
        self.assertFalse(NewsPost.objects.exists())

    def test_atomic_failure_assigns_nobody(self):
        proposal = create_proposal(self.owner, seed=8, clubs=[self.club_a, self.club_b])
        calls = {"n": 0}

        def boom(player, team, source="ADMIN", reference=""):
            calls["n"] += 1
            if calls["n"] > 30:
                raise ValueError("forced mid-allocation failure")
            player.mgl_team = team
            player.is_free_agent = False
            player.save(update_fields=["mgl_team", "is_free_agent"])
            return player

        with patch("mgl.services.assign_player", side_effect=boom):
            with self.assertRaisesMessage(ValueError, "forced mid-allocation failure"):
                approve_proposal(proposal, self.owner, confirm=True)
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, StartingSquadProposal.DRAFT)
        self.assertFalse(StartingSquadLock.objects.exists())
        self.assertFalse(NewsPost.objects.exists())

    def test_season_lock_blocks_second_approval(self):
        first = create_proposal(self.owner, seed=4, clubs=[self.club_a, self.club_b])
        approve_proposal(first, self.owner, confirm=True)
        extra = _fill_pool(prefix="Q")
        for player in extra:
            player.mgl_team = None
            player.save(update_fields=["mgl_team"])
        second = create_proposal(self.owner, seed=6, clubs=[self.club_a, self.club_b])
        with self.assertRaisesMessage(ValueError, "already locked"):
            approve_proposal(second, self.owner, confirm=True)

    def test_http_permissions_and_owner_flow(self):
        public = self.client.get(reverse("control_starting_squads"))
        self.assertEqual(public.status_code, 302)
        self.client.login(username="start-mgr", password="test-pass-123")
        blocked = self.client.get(reverse("control_starting_squads"))
        self.assertEqual(blocked.status_code, 302)
        generate = self.client.post(reverse("control_starting_squads"), {"action": "generate"})
        self.assertEqual(generate.status_code, 302)
        self.assertFalse(StartingSquadProposal.objects.exists())
        self.client.logout()

        self.client.login(username="start-admin", password="test-pass-123")
        view = self.client.get(reverse("control_starting_squads"))
        self.assertEqual(view.status_code, 200)
        self.assertContains(view, "UFL STARTING SQUAD GENERATOR")
        self.assertContains(view, "Only the Owner can generate or approve")
        self.assertContains(view, "OFFICIAL STRUCTURE")
        self.assertContains(view, "GK 2 / 2")
        self.assertContains(view, "CB 5 / 5")
        self.assertContains(view, "RB 1 / 1")
        self.assertContains(view, "LB 1 / 1")
        self.assertContains(view, "RWB 1 / 1")
        self.assertContains(view, "LWB 1 / 1")
        self.assertContains(view, "CM 3 / 3")
        self.assertContains(view, "CDM 2 / 2")
        self.assertContains(view, "CAM 2 / 2")
        self.assertContains(view, "RM 1 / 1")
        self.assertContains(view, "LM 1 / 1")
        self.assertContains(view, "RW 1 / 1")
        self.assertContains(view, "LW 1 / 1")
        self.assertContains(view, "ST 3 / 3")
        self.assertContains(view, "TOTAL 25 / 25")
        self.assertNotContains(view, "22-player")
        self.assertNotContains(view, "22 players")
        self.client.post(reverse("control_starting_squads"), {"action": "generate", "seed": "12"})
        self.assertFalse(StartingSquadProposal.objects.exists())
        self.client.logout()

        self.client.login(username="start-owner", password="test-pass-123")
        page = self.client.get(reverse("control_starting_squads"))
        self.assertContains(page, "GENERATE PROPOSAL")
        created = self.client.post(
            reverse("control_starting_squads"),
            {"action": "generate", "seed": "21"},
        )
        self.assertEqual(created.status_code, 302)
        proposal = StartingSquadProposal.objects.get()
        preview = self.client.get(reverse("control_starting_squads"))
        self.assertContains(preview, "NOT YET LIVE")
        self.assertContains(preview, "Alpha FC")
        self.assertContains(preview, "TOTAL 25 / 25")
        self.assertContains(preview, "GK 2 / 2")
        self.assertContains(preview, "CB 5 / 5")
        self.assertContains(preview, "ST 3 / 3")
        self.assertNotContains(preview, "22 Players")
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)
        denied = self.client.post(
            reverse("control_starting_squads"),
            {"action": "approve", "proposal": str(proposal.pk)},
        )
        self.assertEqual(denied.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, StartingSquadProposal.DRAFT)
        approved = self.client.post(
            reverse("control_starting_squads"),
            {"action": "approve", "proposal": str(proposal.pk), "confirm_approval": "1"},
        )
        self.assertEqual(approved.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, StartingSquadProposal.APPROVED)
        self.assertEqual(
            Player.objects.filter(mgl_team__isnull=False).count(),
            25 * Team.objects.count(),
        )
        live = self.client.get(reverse("control_starting_squads"))
        self.assertContains(live, "STARTING SQUADS ALREADY ALLOCATED")
