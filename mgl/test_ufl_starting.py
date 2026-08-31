from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from auctions.models import PlayerAuction
from leagues.models import League
from managers.models import ManagerApplication
from mgl.models import DiscordEvent, NewsPost, PlayerListing, SiteChangeLog, StartingSquadLock, StartingSquadProposal
from mgl.ufl_settings import UFL_SQUAD_SHAPE
from mgl.ufl_starting import (
    PLAYERS_PER_CLUB,
    SHAPE_COUNTS,
    approve_proposal,
    create_proposal,
    eligible_queryset,
    generate_allocation,
)
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


def _fill_pool(prefix="P", extras=2):
    created = []
    n = 0
    for position, count in UFL_SQUAD_SHAPE:
        for index in range(count * 2 + extras):
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
        self.assertEqual(sum(SHAPE_COUNTS.values()), 25)
        self.assertEqual(SHAPE_COUNTS["CB"], 4)
        self.assertEqual(SHAPE_COUNTS["ST"], 2)
        self.assertEqual(SHAPE_COUNTS["CM"], 2)

    def test_generate_does_not_assign_or_touch_fc26(self):
        before = list(Player.objects.order_by("id").values_list("id", "fc27_id", "overall", "name", "mgl_team_id"))
        tokens = self.manager.tokens
        proposal = create_proposal(self.owner, seed=20260831)
        self.assertEqual(proposal.status, StartingSquadProposal.DRAFT)
        after = list(Player.objects.order_by("id").values_list("id", "fc27_id", "overall", "name", "mgl_team_id"))
        self.assertEqual(before, after)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, tokens)
        self.assertFalse(NewsPost.objects.exists())
        self.assertFalse(DiscordEvent.objects.exists())
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)

    def test_generated_squads_are_valid_and_balanced(self):
        proposal = create_proposal(self.owner, seed=11)
        self.assertTrue(proposal.validation["ok"], proposal.validation)
        clubs = proposal.payload["clubs"]
        self.assertEqual(len(clubs), 2)
        ids = []
        for club in clubs:
            self.assertEqual(len(club["players"]), 25)
            self.assertEqual(club["position_counts"], SHAPE_COUNTS)
            ovrs = [row["overall"] for row in club["players"]]
            self.assertGreaterEqual(min(ovrs), 64)
            self.assertLessEqual(max(ovrs), 69)
            ids.extend(row["id"] for row in club["players"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(float(proposal.largest_avg_diff), 1.5)

    def test_random_seed_changes_allocation(self):
        first = create_proposal(self.owner, seed=1)
        second = create_proposal(self.owner, seed=99)
        a = [row["id"] for row in first.payload["clubs"][0]["players"]]
        b = [row["id"] for row in second.payload["clubs"][0]["players"]]
        self.assertNotEqual(a, b)
        self.assertEqual(StartingSquadProposal.objects.filter(status=StartingSquadProposal.SUPERSEDED).count(), 1)
        self.assertEqual(StartingSquadProposal.objects.filter(status=StartingSquadProposal.DRAFT).count(), 1)

    def test_same_seed_reproduces(self):
        first = generate_allocation(seed=42)
        second = generate_allocation(seed=42)
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
        proposal = create_proposal(self.owner, seed=7)
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
        proposal = create_proposal(self.owner, seed=3)
        with self.assertRaisesMessage(ValueError, "Only the Owner"):
            approve_proposal(proposal, self.admin, confirm=True)
        with self.assertRaisesMessage(ValueError, "explicit confirmation"):
            approve_proposal(proposal, self.owner, confirm=False)
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)
        self.assertFalse(NewsPost.objects.exists())

    def test_stale_player_aborts_approval(self):
        proposal = create_proposal(self.owner, seed=5)
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
        proposal = create_proposal(self.owner, seed=8)
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
        first = create_proposal(self.owner, seed=4)
        approve_proposal(first, self.owner, confirm=True)
        extra = _fill_pool(prefix="Q")
        for player in extra:
            player.mgl_team = None
            player.save(update_fields=["mgl_team"])
        # Existing clubs already have 25; a new draft cannot be approved.
        second = create_proposal(self.owner, seed=6)
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
        self.assertContains(preview, "25 Players")
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
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 50)
        live = self.client.get(reverse("control_starting_squads"))
        self.assertContains(live, "STARTING SQUADS ALREADY ALLOCATED")
