from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from mgl.scouting import (
    SQUAD_FULL_MESSAGE,
    TIER_RANGES,
    complete_ready_assignments,
    cooldown_hours,
    dispatch_scout,
    eligible_players,
    file_scout_report,
    get_or_create_scout_profile,
    manager_scout_level,
    open_scout_pack,
    send_scout_to_team,
    upgrade_scout,
)
from mgl.models import LeagueSettings, ManagerNotification, ScoutAssignment, ScoutProfile, ScoutReport, ScoutSquadException
from mgl.regions import (
    REGION_MENU,
    REGION_NATIONS,
    SCOUT_POSITIONS,
    mapping_count,
    nations_for_region,
    region_option_count,
    unique_mapped_nations,
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
        "is_free_agent": False,
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

    def test_level_2_to_4_use_requested_token_costs(self):
        self.manager.tokens = Decimal("80.00")
        self.manager.save(update_fields=["tokens"])
        club_tokens = self.club.tokens
        expected = [(2, "10.00"), (3, "18.00"), (4, "25.00")]
        for level, cost in expected:
            profile, nxt, paid = upgrade_scout(self.manager)
            self.assertEqual(nxt, level)
            self.assertEqual(paid, Decimal(cost))
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("27.00"))
        self.club.refresh_from_db()
        self.assertEqual(self.club.tokens, club_tokens)
        with self.assertRaises(ValueError):
            upgrade_scout(self.manager)

    def test_insufficient_tokens_prevents_upgrade_and_negative_balance(self):
        poor_user = _user("broke")
        poor = _manager(poor_user, tokens="9.00")
        with self.assertRaises(ValueError):
            upgrade_scout(poor)
        poor.refresh_from_db()
        self.assertEqual(poor.tokens, Decimal("9.00"))
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
            (1, "SILVER"): Decimal("16"),
            (1, "GOLD"): Decimal("32"),
            (1, "ELITE"): Decimal("48"),
            (2, "BRONZE"): Decimal("6"),
            (2, "SILVER"): Decimal("14"),
            (3, "BRONZE"): Decimal("4"),
            (4, "BRONZE"): Decimal("1"),
            (4, "GOLD"): Decimal("16"),
            (4, "ELITE"): Decimal("24"),
        }
        for (level, tier), hours in expected.items():
            self.assertEqual(cooldown_hours(tier, level), hours)
        self.assertEqual(TIER_RANGES["BRONZE"], (45, 60))
        self.assertEqual(TIER_RANGES["SILVER"], (60, 72))
        self.assertEqual(TIER_RANGES["GOLD"], (73, 81))
        self.assertEqual(TIER_RANGES["ELITE"], (82, 91))


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
            ["GK", "CB", "LB", "RB", "LWB", "RWB", "CDM", "CM", "CAM", "LM", "RM", "LW", "RW", "ST"],
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
        self.elite = _player(name="Elite Scout Target", position="ST", overall=85, nationality="France")

    def _discover(self, tier, region, position, expected):
        before = Player.objects.count()
        tokens_before = self.manager.tokens
        snapshot = (
            expected.name,
            expected.overall,
            expected.position,
            expected.nationality,
            expected.fc27_id,
        )
        assignment = dispatch_scout(self.manager, tier, region, position)
        self.assertIsNone(assignment.player_id)
        self.assertEqual(assignment.status, ScoutAssignment.PENDING)
        expected.refresh_from_db()
        self.assertIsNone(expected.mgl_team_id)
        ready, _notices = _finish(assignment)
        self.assertEqual(len(ready), 1)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, ScoutAssignment.COMPLETE)
        self.assertEqual(assignment.outcome, ScoutAssignment.OUTCOME_RECRUITED)
        report = ScoutReport.objects.get(assignment=assignment)
        expected.refresh_from_db()
        self.manager.refresh_from_db()
        self.assertEqual(report.player_id, expected.id)
        self.assertTrue(report.recruited)
        self.assertEqual(report.club_id, self.club.id)
        self.assertEqual(expected.mgl_team_id, self.club.id)
        self.assertFalse(expected.is_free_agent)
        self.assertEqual(self.manager.tokens, tokens_before)
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

    def test_bronze_silver_gold_elite_discover_existing_players(self):
        self._discover("BRONZE", "south-america", "ST", self.bronze)
        self._discover("SILVER", "southern-europe", "CM", self.silver)
        self._discover("GOLD", "western-europe", "CB", self.gold)
        self._discover("ELITE", "europe", "ST", self.elite)

    def test_region_and_position_combination(self):
        other = _player(name="Wrong Combo", position="ST", overall=50, nationality="France")
        report = self._discover("BRONZE", "south-america", "ST", self.bronze)
        self.assertEqual(report.region, "south-america")
        self.assertEqual(report.position, "ST")
        other.refresh_from_db()
        self.assertFalse(other.is_free_agent)
        self.assertIsNone(other.mgl_team_id)

    def test_manager_recruits_when_scout_returns(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        _finish(assignment)
        assignment.refresh_from_db()
        self.bronze.refresh_from_db()
        self.assertEqual(assignment.status, ScoutAssignment.COMPLETE)
        self.assertEqual(self.bronze.mgl_team_id, self.club.id)
        self.assertEqual(ScoutReport.objects.filter(assignment=assignment, recruited=True).count(), 1)

    def test_legacy_flag_cannot_disable_manager_recruit(self):
        LeagueSettings.objects.create(scout_can_recruit=False)
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        _finish(assignment)
        self.bronze.refresh_from_db()
        self.assertEqual(self.bronze.mgl_team_id, self.club.id)

    def test_owner_correction_still_assigns_when_needed(self):
        owner_user = _user("scout-owner", role=User.OWNER)
        owner_mgr = _manager(owner_user, tokens="50.00")
        owner_club = _club(owner_user, self.league, name="Office FC", short="OFF")
        open_club_spell(owner_mgr, owner_club)
        assignment = dispatch_scout(owner_mgr, "BRONZE", "south-america", "ST")
        _finish(assignment)
        assignment.refresh_from_db()
        self.bronze.refresh_from_db()
        self.assertEqual(self.bronze.mgl_team_id, owner_club.id)

    def test_dispatch_survives_reload_without_claiming_yet(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        ready_at = assignment.ready_at
        self.assertAlmostEqual(
            (assignment.ready_at - assignment.started_at).total_seconds(),
            8 * 3600,
            delta=3,
        )
        assignment.refresh_from_db()
        self.assertEqual(assignment.ready_at, ready_at)
        self.assertIsNone(assignment.player_id)
        self.assertIn(self.bronze, eligible_players("BRONZE", "south-america", "ST"))

    def test_two_managers_cannot_recruit_the_same_player(self):
        other_user = _user("rival")
        other_manager = _manager(other_user, tokens="50.00")
        other_club = _club(other_user, self.league, name="Rival FC", short="RIV")
        open_club_spell(other_manager, other_club)
        first = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        second = dispatch_scout(other_manager, "BRONZE", "south-america", "ST")
        _finish(first)
        _finish(second)
        self.bronze.refresh_from_db()
        owners = {
            first.manager_id: Player.objects.filter(mgl_team=self.club, pk=self.bronze.pk).exists(),
            second.manager_id: Player.objects.filter(mgl_team=other_club, pk=self.bronze.pk).exists(),
        }
        self.assertEqual(sum(1 for owned in owners.values() if owned), 1)

    def test_recruited_player_is_no_longer_unassigned(self):
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        _finish(assignment)
        self.bronze.refresh_from_db()
        self.assertEqual(self.bronze.mgl_team_id, self.club.id)
        with self.assertRaises(ValueError):
            dispatch_scout(self.manager, "BRONZE", "south-america", "ST")

    def test_notification_created_when_scout_returns(self):
        assignment = dispatch_scout(self.manager, "SILVER", "southern-europe", "CM")
        _finish(assignment)
        note = ManagerNotification.objects.get(source_key=f"scout-result-{assignment.id}")
        self.assertIn("RECRUITED", note.title)
        self.assertEqual(note.player_id, self.silver.id)

    def test_one_active_scout_blocks_every_other_tier(self):
        first = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        with self.assertRaisesMessage(ValueError, "already have an active scout"):
            dispatch_scout(self.manager, "SILVER", "southern-europe", "CM")
        with self.assertRaisesMessage(ValueError, "already have an active scout"):
            dispatch_scout(self.manager, "GOLD", "western-europe", "CB")
        self.assertEqual(ScoutAssignment.objects.filter(manager=self.manager).count(), 1)
        first.refresh_from_db()
        self.assertIsNone(first.player_id)
        self.assertEqual(first.status, ScoutAssignment.PENDING)


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

    def test_full_squad_can_still_scout(self):
        self._fill(28)
        assignment = dispatch_scout(self.manager, "BRONZE", "europe", "ST")
        ready, _notices = _finish(assignment)
        self.assertEqual(len(ready), 1)
        assignment.refresh_from_db()
        self.target.refresh_from_db()
        self.assertEqual(assignment.outcome, ScoutAssignment.OUTCOME_SQUAD_FULL)
        self.assertIsNone(self.target.mgl_team_id)
        self.assertTrue(ScoutSquadException.objects.filter(assignment=assignment, status="PENDING").exists())
        self.assertEqual(Player.objects.filter(mgl_team=self.club).count(), 28)
        self.assertEqual(Player.objects.filter(name="Last Recruit").count(), 1)

    def test_manager_recruits_when_squad_has_space(self):
        self._fill(27)
        assignment = dispatch_scout(self.manager, "BRONZE", "europe", "ST")
        _finish(assignment)
        self.target.refresh_from_db()
        self.assertEqual(self.target.mgl_team_id, self.club.id)
        self.assertEqual(Player.objects.filter(mgl_team=self.club).count(), 28)

    def test_admin_assign_still_respects_roster_limit(self):
        admin_user = _user("scout-admin", role=User.ADMIN)
        admin_mgr = _manager(admin_user, tokens="50.00")
        admin_club = _club(admin_user, self.league, name="Admin FC", short="ADM")
        open_club_spell(admin_mgr, admin_club)
        for i in range(28):
            _player(
                name=f"Admin Squad {i}",
                position="CM",
                overall=61,
                nationality="England",
                is_free_agent=False,
                mgl_team=admin_club,
            )
        assignment = dispatch_scout(admin_mgr, "BRONZE", "europe", "ST")
        _finish(assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.outcome, ScoutAssignment.OUTCOME_SQUAD_FULL)
        self.target.refresh_from_db()
        self.assertIsNone(self.target.mgl_team_id)
        self.assertTrue(ScoutSquadException.objects.filter(assignment=assignment).exists())


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
        self.assertContains(page, "LEVEL 1 / 4")
        self.assertContains(page, "SCOUT HEADQUARTERS")
        self.assertContains(page, "SEND YOUR SCOUT")
        self.assertContains(page, "ACTIVE SCOUTS")
        self.assertContains(page, "RECENT SCOUT REPORTS")
        self.assertContains(page, "UPGRADE (10 TOKENS)")
        self.assertContains(page, "8 Hours")
        self.assertContains(page, "16 Hours")
        self.assertContains(page, "32 Hours")
        self.assertContains(page, "48 Hours")
        self.assertContains(page, "ELITE")
        self.assertContains(page, 'optgroup label="Europe"')
        self.assertContains(page, "British Isles")
        self.assertContains(page, "North &amp; Central America")
        self.assertContains(page, "Africa (all)")
        html = page.content.decode()
        self.assertEqual(html.count('name="action" value="upgrade"'), 1)
        self.assertNotIn('name="tier"', html.split('mgl-scout-upgrade', 1)[1].split("</form>", 1)[0])
        self.assertEqual(html.count('name="action" value="dispatch"'), 4)
        self.assertNotContains(page, '<option value="France">')
        for pos in SCOUT_POSITIONS:
            self.assertContains(page, f'<option value="{pos}">{pos}</option>')

    def test_page_recruits_when_timer_elapses(self):
        assignment = dispatch_scout(self.manager, "SILVER", "southern-europe", "CM")
        assignment.ready_at = timezone.now() - timedelta(minutes=1)
        assignment.save(update_fields=["ready_at"])
        self.client.login(username="page", password="test-pass-123")
        page = self.client.get(reverse("scouting"))
        self.silver.refresh_from_db()
        self.assertEqual(self.silver.mgl_team.short_name, "SCF")
        self.assertContains(page, "Silver Scout Target")
        self.assertContains(page, "RECRUITED")

    def test_reports_are_private_and_mark_recruited(self):
        assignment = dispatch_scout(self.manager, "SILVER", "southern-europe", "CM")
        _finish(assignment)
        self.client.login(username="page", password="test-pass-123")
        page = self.client.get(reverse("scouting"))
        self.assertContains(page, "Silver Scout Target")
        self.assertContains(page, "RECRUITED")
        self.client.login(username="other", password="test-pass-123")
        other_page = self.client.get(reverse("scouting"))
        self.assertNotContains(other_page, "Silver Scout Target")
        self.assertEqual(ScoutReport.objects.filter(manager=self.other).count(), 0)

    def test_page_disables_all_dispatch_while_one_scout_is_active(self):
        _player(name="Bronze Page Target", position="ST", overall=50, nationality="Brazil")
        self.client.login(username="page", password="test-pass-123")
        idle = self.client.get(reverse("scouting"))
        self.assertNotContains(idle, "already on assignment")
        self.assertEqual(idle.content.decode().count('mgl-sc-dispatch" disabled'), 0)
        assignment = dispatch_scout(self.manager, "BRONZE", "south-america", "ST")
        busy = self.client.get(reverse("scouting"))
        self.assertContains(busy, "already on assignment")
        self.assertEqual(busy.content.decode().count('mgl-sc-dispatch" disabled'), 4)
        self.assertContains(busy, "BRONZE SCOUT")
        self.assertContains(busy, "IN PROGRESS")
        assignment.refresh_from_db()
        self.assertIsNone(assignment.player_id)

    def test_double_dispatch_post_creates_one_assignment(self):
        _player(name="Double Dispatch Target", position="ST", overall=51, nationality="Brazil")
        self.client.login(username="page", password="test-pass-123")
        payload = {
            "action": "dispatch",
            "tier": "BRONZE",
            "region": "south-america",
            "position": "ST",
        }
        first = self.client.post(reverse("scouting"), payload)
        second = self.client.post(reverse("scouting"), payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(ScoutAssignment.objects.filter(manager=self.manager).count(), 1)
        assignment = ScoutAssignment.objects.get(manager=self.manager)
        self.assertEqual(assignment.tier, "BRONZE")
        self.assertEqual(assignment.region, "south-america")
        self.assertEqual(assignment.position, "ST")
        self.assertIsNone(assignment.player_id)

    def test_assignment_survives_refresh_and_relogin(self):
        assignment = dispatch_scout(self.manager, "SILVER", "southern-europe", "CM")
        ready_at = assignment.ready_at
        self.client.login(username="page", password="test-pass-123")
        first = self.client.get(reverse("scouting"))
        self.assertContains(first, "SILVER SCOUT")
        self.assertNotContains(first, "Silver Scout Target")
        self.client.logout()
        self.client.login(username="page", password="test-pass-123")
        second = self.client.get(reverse("scouting"))
        assignment.refresh_from_db()
        self.assertIsNone(assignment.player_id)
        self.assertEqual(assignment.ready_at, ready_at)
        self.assertEqual(assignment.status, ScoutAssignment.PENDING)
        self.assertContains(second, "SILVER SCOUT")
        self.assertNotContains(second, "Silver Scout Target")

    def test_manager_http_cannot_manually_assign_another_player(self):
        assignment = dispatch_scout(self.manager, "SILVER", "southern-europe", "CM")
        tokens_before = self.manager.tokens
        self.client.login(username="page", password="test-pass-123")
        response = self.client.post(
            reverse("scouting"),
            {"action": "send_to_team", "assignment": str(assignment.id)},
        )
        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.manager.refresh_from_db()
        self.assertEqual(assignment.status, ScoutAssignment.PENDING)
        self.assertEqual(self.manager.tokens, tokens_before)
