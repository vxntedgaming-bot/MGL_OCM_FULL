from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from mgl.models import ScoutAssignment, ScoutProfile, ScoutReport
from mgl.regions import (
    REGION_MENU,
    REGION_NATIONS,
    SCOUT_POSITIONS,
    mapping_count,
    nations_for_region,
    region_option_count,
    unique_mapped_nations,
)
from mgl.scouting import (
    SQUAD_FULL_MESSAGE,
    TIER_RANGES,
    complete_ready_assignments,
    cooldown_hours,
    dispatch_scout,
    eligible_players,
    get_or_create_scout_profile,
    manager_scout_level,
    upgrade_scout,
)
from mgl.tenure import close_club_spell_for_user, open_club_spell
from players.models import Player
from teams.models import Team


REGION_FIXTURES = (
    ("europe", "France", "Brazil"),
    ("british-isles", "England", "France"),
    ("nordic", "Sweden", "Germany"),
    ("baltic", "Latvia", "Poland"),
    ("western-europe", "Germany", "Italy"),
    ("southern-europe", "Spain", "England"),
    ("eastern-europe", "Poland", "France"),
    ("balkans", "Serbia", "Germany"),
    ("south-america", "Brazil", "Spain"),
    ("north-central-america", "Mexico", "Brazil"),
    ("africa", "Senegal", "France"),
    ("north-africa", "Morocco", "Nigeria"),
    ("west-africa", "Nigeria", "Egypt"),
    ("central-africa", "Cameroon", "Ghana"),
    ("east-africa", "Kenya", "South Africa"),
    ("southern-africa", "South Africa", "Egypt"),
    ("asia", "Japan", "Brazil"),
    ("east-asia", "Japan", "India"),
    ("middle-east", "Saudi Arabia", "Japan"),
    ("south-asia", "India", "Japan"),
    ("southeast-asia", "Thailand", "Japan"),
    ("oceania", "Australia", "England"),
)


def _user(username, role=User.MANAGER, **kwargs):
    return User.objects.create_user(
        username=username, password="test-pass-123", role=role, **kwargs
    )


def _manager(user, tokens="50.00", status=ManagerApplication.APPROVED):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=status,
        tokens=Decimal(tokens),
    )


def _league():
    return League.objects.create(name="Scout League", short_name="SCL", season="1")


def _club(user, league, name="Scout FC", short="SCF"):
    team = Team.objects.create(
        name=name,
        short_name=short,
        league=league,
        manager=user,
        tokens=Decimal("50.00"),
    )
    return team


def _player(**kwargs):
    defaults = {
        "name": "Scout Target",
        "position": "ST",
        "overall": 50,
        "nationality": "France",
        "is_free_agent": True,
        "mgl_team": None,
    }
    defaults.update(kwargs)
    return Player.objects.create(**defaults)


def _finish(assignment):
    assignment.ready_at = timezone.now() - timedelta(seconds=5)
    assignment.save(update_fields=["ready_at"])
    return complete_ready_assignments(assignment.manager)


class ScoutLevelTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.user = _user("scout")
        self.manager = _manager(self.user, tokens="50.00")
        self.club = _club(self.user, self.league)
        open_club_spell(self.manager, self.club)

    def test_new_manager_starts_at_level_1_for_free(self):
        profile = get_or_create_scout_profile(self.manager)
        self.assertEqual(profile.scout_level, 1)
        self.assertEqual(manager_scout_level(self.manager), 1)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("50.00"))

    def test_level_2_costs_18_tokens_and_level_3_costs_25(self):
        club_tokens = self.club.tokens
        profile, level, cost = upgrade_scout(self.manager)
        self.assertEqual(level, 2)
        self.assertEqual(cost, Decimal("18.00"))
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("32.00"))
        self.club.refresh_from_db()
        self.assertEqual(self.club.tokens, club_tokens)

        profile, level, cost = upgrade_scout(self.manager)
        self.assertEqual(level, 3)
        self.assertEqual(cost, Decimal("25.00"))
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("7.00"))
        self.assertGreaterEqual(self.manager.tokens, 0)
        self.club.refresh_from_db()
        self.assertEqual(self.club.tokens, club_tokens)

        with self.assertRaises(ValueError):
            upgrade_scout(self.manager)

    def test_insufficient_tokens_prevents_upgrade_and_negative_balance(self):
        poor_user = _user("broke")
        poor = _manager(poor_user, tokens="17.00")
        with self.assertRaises(ValueError):
            upgrade_scout(poor)
        poor.refresh_from_db()
        self.assertEqual(poor.tokens, Decimal("17.00"))
        self.assertGreaterEqual(poor.tokens, 0)
        self.assertEqual(get_or_create_scout_profile(poor).scout_level, 1)

    def test_scout_level_survives_leaving_and_joining_clubs(self):
        upgrade_scout(self.manager)
        self.assertEqual(manager_scout_level(self.manager), 2)
        self.club.manager = None
        self.club.save(update_fields=["manager"])
        close_club_spell_for_user(self.user, self.club)
        self.assertEqual(manager_scout_level(self.manager), 2)

        other = _club(_user("parked"), self.league, name="Second FC", short="SEC")
        other.manager = self.user
        other.save(update_fields=["manager"])
        open_club_spell(self.manager, other)
        self.assertEqual(ScoutProfile.objects.filter(manager=self.manager).count(), 1)
        self.assertEqual(manager_scout_level(self.manager), 2)


class ScoutTimeTests(TestCase):
    def test_final_cooldown_table(self):
        expected = {
            (1, "BRONZE"): Decimal("8"),
            (1, "SILVER"): Decimal("10"),
            (1, "GOLD"): Decimal("12"),
            (2, "BRONZE"): Decimal("4"),
            (2, "SILVER"): Decimal("5"),
            (2, "GOLD"): Decimal("6"),
            (3, "BRONZE"): Decimal("1"),
            (3, "SILVER"): Decimal("2.5"),
            (3, "GOLD"): Decimal("3"),
        }
        for (level, tier), hours in expected.items():
            self.assertEqual(cooldown_hours(tier, level), hours)
        self.assertEqual(TIER_RANGES["BRONZE"], (45, 56))
        self.assertEqual(TIER_RANGES["SILVER"], (60, 74))
        self.assertEqual(TIER_RANGES["GOLD"], (70, 81))


class ScoutRegionTests(TestCase):
    def test_menu_contains_only_requested_regions(self):
        labels = [label for _group, items in REGION_MENU for _key, label in items]
        self.assertEqual(
            labels,
            [
                "Anywhere",
                "Europe (all)",
                "British Isles",
                "Nordic",
                "Baltic",
                "Western Europe",
                "Southern Europe",
                "Eastern Europe",
                "Balkans",
                "South America",
                "North & Central America",
                "Africa (all)",
                "North Africa",
                "West Africa",
                "Central Africa",
                "East Africa",
                "Southern Africa",
                "Asia (all)",
                "East Asia",
                "Middle East",
                "South Asia",
                "Southeast Asia",
                "Oceania",
            ],
        )
        self.assertEqual(region_option_count(), 23)
        self.assertEqual(len(REGION_NATIONS), 22)
        self.assertGreaterEqual(mapping_count(), 160)
        self.assertEqual(len(unique_mapped_nations()), 160)

    def test_region_filters_return_correct_nations(self):
        self.assertIsNone(nations_for_region("anywhere"))
        self.assertIsNone(nations_for_region(""))
        for key, inside, outside in REGION_FIXTURES:
            nations = nations_for_region(key)
            self.assertIn(inside, nations)
            self.assertNotIn(outside, nations)
            player_in = _player(
                name=f"{key}-in",
                nationality=inside,
                overall=50,
                position="ST",
            )
            player_out = _player(
                name=f"{key}-out",
                nationality=outside,
                overall=50,
                position="ST",
            )
            ids = set(eligible_players("BRONZE", key, "ST").values_list("id", flat=True))
            self.assertIn(player_in.id, ids)
            self.assertNotIn(player_out.id, ids)

        anywhere = _player(name="Anywhere Man", nationality="Uruguay", overall=51, position="ST")
        self.assertIn(anywhere, eligible_players("BRONZE", "anywhere", "ST"))
        self.assertIn(anywhere, eligible_players("BRONZE", "", "ST"))


class ScoutPositionTests(TestCase):
    def test_each_position_filter(self):
        self.assertEqual(
            list(SCOUT_POSITIONS),
            ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "ST"],
        )
        players = {
            pos: _player(name=f"Pos {pos}", position=pos, overall=52, nationality="France")
            for pos in SCOUT_POSITIONS
        }
        for pos, player in players.items():
            ids = set(eligible_players("BRONZE", "europe", pos).values_list("id", flat=True))
            self.assertEqual(ids, {player.id})


class ScoutGenerationTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.user = _user("recruiter")
        self.manager = _manager(self.user, tokens="50.00")
        self.club = _club(self.user, self.league)
        open_club_spell(self.manager, self.club)
        self.bronze = _player(name="Bronze Scout Target", position="ST", overall=50, nationality="Brazil")
        self.silver = _player(name="Silver Scout Target", position="CM", overall=66, nationality="Spain")
        self.gold = _player(name="Gold Scout Target", position="CB", overall=75, nationality="Germany")

    def _complete(self, tier, region, position, expected):
        before = Player.objects.count()
        snapshot = (
            expected.name,
            expected.overall,
            expected.position,
            expected.nationality,
            expected.fc27_id,
        )
        assignment = dispatch_scout(self.manager, tier, region, position)
        self.assertIsNone(assignment.player_id)
        reports, notices = _finish(assignment)
        self.assertEqual(len(reports), 1)
        report = reports[0]
        expected.refresh_from_db()
        self.assertEqual(report.player_id, expected.id)
        self.assertTrue(report.recruited)
        self.assertEqual(report.club_id, self.club.id)
        self.assertEqual(expected.mgl_team_id, self.club.id)
        self.assertFalse(expected.is_free_agent)
        self.assertEqual(Player.objects.count(), before)
        self.assertEqual(Player.objects.filter(pk=expected.pk).count(), 1)
        self.assertEqual(
            (
                expected.name,
                expected.overall,
                expected.position,
                expected.nationality,
                expected.fc27_id,
            ),
            snapshot,
        )
        return report

    def test_bronze_silver_gold_recruit_existing_players(self):
        self._complete("BRONZE", "south-america", "ST", self.bronze)
        self._complete("SILVER", "southern-europe", "CM", self.silver)
        self._complete("GOLD", "western-europe", "CB", self.gold)

    def test_region_and_position_combination(self):
        other = _player(name="Wrong Combo", position="ST", overall=50, nationality="France")
        report = self._complete("BRONZE", "south-america", "ST", self.bronze)
        self.assertEqual(report.region, "south-america")
        self.assertEqual(report.position, "ST")
        other.refresh_from_db()
        self.assertTrue(other.is_free_agent)
        self.assertIsNone(other.mgl_team_id)


class ScoutRosterLimitTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.user = _user("limit")
        self.manager = _manager(self.user, tokens="50.00")
        self.club = _club(self.user, self.league)
        open_club_spell(self.manager, self.club)
        self.target = _player(name="Last Recruit", position="ST", overall=50, nationality="France")

    def _fill(self, count):
        for i in range(count):
            _player(
                name=f"Squad {i}",
                position="CM",
                overall=61,
                nationality="England",
                is_free_agent=False,
                mgl_team=self.club,
            )

    def test_29_players_allows_recruitment_to_30(self):
        self._fill(29)
        assignment = dispatch_scout(self.manager, "BRONZE", "europe", "ST")
        reports, _notices = _finish(assignment)
        self.assertEqual(len(reports), 1)
        self.target.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.club.id)
        self.assertEqual(Player.objects.filter(mgl_team=self.club).count(), 30)
        self.assertFalse(self.target.is_free_agent)

    def test_30_players_rejects_recruitment_and_keeps_player_free(self):
        self._fill(30)
        with self.assertRaisesMessage(ValueError, SQUAD_FULL_MESSAGE):
            dispatch_scout(self.manager, "BRONZE", "europe", "ST")
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_free_agent)
        self.assertIsNone(self.target.mgl_team_id)
        self.assertEqual(Player.objects.filter(mgl_team=self.club).count(), 30)
        self.assertEqual(Player.objects.filter(name="Last Recruit").count(), 1)

    def test_pending_scout_cannot_push_squad_to_31(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "europe", "ST")
        self._fill(30)
        assignment.ready_at = timezone.now() - timedelta(seconds=5)
        assignment.save(update_fields=["ready_at"])
        reports, notices = complete_ready_assignments(self.manager)
        self.assertEqual(reports, [])
        self.assertIn(SQUAD_FULL_MESSAGE, notices)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, ScoutAssignment.PENDING)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_free_agent)
        self.assertEqual(Player.objects.filter(mgl_team=self.club).count(), 30)


class ScoutPageTests(TestCase):
    def setUp(self):
        self.league = _league()
        self.user = _user("page")
        self.manager = _manager(self.user, tokens="50.00")
        self.other_user = _user("other")
        self.other = _manager(self.other_user, tokens="50.00")
        _club(self.user, self.league)
        _club(self.other_user, self.league, name="Other FC", short="OFC")
        self.silver = _player(name="Silver Scout Target", position="CM", overall=66, nationality="Spain")
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_page_shows_one_upgrade_and_grouped_regions(self):
        self.client.login(username="page", password="test-pass-123")
        page = self.client.get(reverse("scouting"))
        self.assertContains(page, "LEVEL 1 / 3")
        self.assertContains(page, "UPGRADE YOUR SCOUTING NETWORK")
        self.assertContains(page, "One upgrade improves Bronze, Silver &amp; Gold scouts.")
        self.assertContains(page, "UPGRADE TO LEVEL 2")
        self.assertContains(page, "18 TOKENS")
        self.assertContains(page, "8 Hours")
        self.assertContains(page, "10 Hours")
        self.assertContains(page, "12 Hours")
        self.assertContains(page, 'optgroup label="Europe"')
        self.assertContains(page, "British Isles")
        self.assertContains(page, "North &amp; Central America")
        self.assertContains(page, "Africa (all)")
        html = page.content.decode()
        self.assertEqual(html.count('name="action" value="upgrade"'), 1)
        self.assertNotIn('name="tier"', html.split('mgl-scout-upgrade', 1)[1].split("</form>", 1)[0])
        self.assertEqual(html.count('name="action" value="dispatch"'), 3)
        self.assertNotContains(page, '<option value="France">')
        for pos in SCOUT_POSITIONS:
            self.assertContains(page, f'<option value="{pos}">{pos}</option>')

    def test_reports_are_private_and_mark_recruited(self):
        assignment = dispatch_scout(self.manager, "SILVER", "southern-europe", "CM")
        assignment.ready_at = timezone.now() - timedelta(minutes=1)
        assignment.save(update_fields=["ready_at"])
        self.client.login(username="page", password="test-pass-123")
        page = self.client.get(reverse("scouting"))
        self.assertContains(page, "Silver Scout Target")
        self.assertContains(page, "RECRUITED")
        self.assertContains(page, "BRONZE")
        self.assertContains(page, "Anywhere")
        self.client.login(username="other", password="test-pass-123")
        other_page = self.client.get(reverse("scouting"))
        self.assertNotContains(other_page, "Silver Scout Target")
        self.assertEqual(ScoutReport.objects.filter(manager=self.other).count(), 0)
