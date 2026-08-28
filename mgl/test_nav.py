from decimal import Decimal

from django.db.models import Count
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_super_league_1
from managers.models import ManagerApplication
from mgl.nav import NAV_DROPDOWNS, nav_dropdowns_for_request
from mgl.templatetags.mgl_ui import card_name
from players.models import Player
from teams.models import Team


class NavigationDropdownTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.user = User.objects.create_user(
            username="navuser",
            password="test-pass-123",
        )
        ManagerApplication.objects.create(
            user=self.user,
            display_name="Nav User",
            gamertag="NAV1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("50.00"),
        )

    def test_every_dropdown_item_has_a_real_url(self):
        for menu in NAV_DROPDOWNS:
            for item in menu["items"]:
                url = reverse(item["url_name"], kwargs=item.get("url_kwargs") or None)
                self.assertTrue(url.startswith("/"), item)
                self.assertNotEqual(url, "#")

    def test_homepage_renders_all_dropdowns(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("core/js/mgl-nav.js", html)
        self.assertIn('data-nav-trigger', html)
        self.assertIn('data-nav-dropdown="my-team"', html)
        self.assertIn('data-nav-dropdown="market"', html)
        self.assertIn('data-nav-dropdown="leagues"', html)
        self.assertIn('data-nav-dropdown="stats"', html)
        self.assertContains(response, "MY TEAM")
        self.assertContains(response, "MARKET")
        self.assertContains(response, "LEAGUES")
        self.assertContains(response, "STATS &amp; HISTORY")
        self.assertContains(response, "TEAM MANAGEMENT")
        self.assertContains(response, "FIXTURES")
        self.assertContains(response, reverse("team_management"))
        self.assertContains(response, reverse("fixture_list"))
        self.assertContains(response, "TRANSFERS")
        self.assertContains(response, "TRANSFER MARKET")
        self.assertContains(response, "FREE AGENTS")
        self.assertContains(response, "RECRUITMENT DRIVE")
        self.assertContains(response, "SCOUTING")
        self.assertContains(response, "YOUTH ACADEMY")
        self.assertContains(response, "AUCTIONS")
        self.assertContains(response, "ALL PLAYERS")
        self.assertContains(response, reverse("transfer_history"))
        self.assertContains(response, reverse("transfer_market"))
        self.assertContains(response, reverse("free_agents"))
        self.assertContains(response, reverse("job_centre"))
        self.assertContains(response, reverse("scouting"))
        self.assertContains(response, reverse("youth_academy"))
        self.assertContains(response, reverse("live_auctions"))
        self.assertContains(response, reverse("player_database"))
        self.assertContains(response, "NEW")
        self.assertContains(response, "ALL LEAGUES")
        self.assertContains(response, "Premier League")
        self.assertContains(response, "Championship")
        self.assertContains(response, "League One")
        self.assertNotContains(response, reverse("competition_page", kwargs={"slug": "mls"}))
        self.assertNotContains(response, reverse("unassigned_players"))
        self.assertNotContains(response, "UNASSIGNED PLAYERS")
        self.assertContains(response, "CUPS")
        self.assertContains(response, "WAITING ROOM LEAGUE")
        self.assertContains(response, reverse("leagues_page"))
        self.assertContains(
            response, reverse("competition_page", kwargs={"slug": "premier-league"})
        )
        self.assertContains(
            response, reverse("competition_page", kwargs={"slug": "waiting-room"})
        )
        self.assertContains(response, "HISTORICAL LEAGUE TABLES")
        self.assertContains(response, "STATS HUB")
        self.assertContains(response, "HEAD TO HEAD")
        self.assertContains(response, "COMPARE")
        self.assertContains(response, "MANAGER SEARCH")
        self.assertContains(response, reverse("historical_tables"))
        self.assertContains(response, reverse("stats_page"))
        self.assertContains(response, reverse("head_to_head"))
        self.assertContains(response, reverse("compare_players"))
        self.assertContains(response, reverse("manager_search"))
        self.assertNotContains(response, "Super League 2")
        self.assertIn("mgl-nav-chevron", html)
        self.assertIn('aria-expanded="false"', html)

    def test_market_dropdown_highlights_current_page(self):
        response = self.client.get(reverse("transfer_market"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-nav-dropdown="market"')
        self.assertContains(response, "mgl-nav-trigger is-active")
        self.assertContains(response, "mgl-nav-item is-current")
        self.assertContains(response, reverse("free_agents"))

    def test_league_dropdown_highlights_competition(self):
        response = self.client.get(
            reverse("competition_page", kwargs={"slug": "premier-league"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Premier League")
        self.assertContains(response, "mgl-nav-item--sub is-current")
        self.assertNotContains(response, "Super League 1 is the only active league")
        self.assertNotContains(response, "Super League 2")

    def test_my_team_dropdown_highlights_when_logged_in(self):
        self.client.login(username="navuser", password="test-pass-123")
        response = self.client.get(reverse("team_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-nav-dropdown="my-team"')
        self.assertContains(response, reverse("fixture_list"))

    def test_stats_dropdown_pages_load(self):
        for name in (
            "historical_tables",
            "stats_page",
            "head_to_head",
            "compare_players",
            "manager_search",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, 'data-nav-dropdown="stats"')
            self.assertNotContains(response, "Super League 2")

    def test_context_marks_open_menu_for_request(self):
        factory = RequestFactory()
        request = factory.get(reverse("free_agents"))
        request.resolver_match = type(
            "Match",
            (),
            {"url_name": "free_agents", "kwargs": {}},
        )()
        menus = {menu["id"]: menu for menu in nav_dropdowns_for_request(request)}
        self.assertTrue(menus["market"]["is_current"])
        current_labels = [
            item["label"] for item in menus["market"]["items"] if item["is_current"]
        ]
        self.assertEqual(current_labels, ["FREE AGENTS"])
        self.assertFalse(menus["my-team"]["is_current"])

    def test_unassigned_players_nav_is_admin_only(self):
        anonymous = self.client.get("/")
        self.assertNotContains(anonymous, reverse("unassigned_players"))
        self.client.login(username="navuser", password="test-pass-123")
        manager = self.client.get("/")
        self.assertNotContains(manager, reverse("unassigned_players"))
        self.assertNotContains(manager, "UNASSIGNED PLAYERS")
        User.objects.create_user(
            username="navowner",
            password="test-pass-123",
            role=User.OWNER,
        )
        self.client.login(username="navowner", password="test-pass-123")
        owner = self.client.get("/")
        self.assertContains(owner, reverse("unassigned_players"))
        self.assertContains(owner, "UNASSIGNED PLAYERS")


class PlayerSearchAndCardNameTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_super_league_1()
        self.team = Team.objects.filter(short_name="LIV").first() or Team.objects.create(
            name="Liverpool",
            short_name="LIV",
            league=self.league,
        )
        self.user = User.objects.create_user(
            username="searchuser",
            password="test-pass-123",
        )
        ManagerApplication.objects.create(
            user=self.user,
            display_name="Search User",
            gamertag="SRCH",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("50.00"),
        )
        self.salah = Player.objects.create(
            name="Mohamed Salah",
            fc27_id="209331",
            position="RM",
            overall=91,
            is_free_agent=True,
        )
        self.mbappe = Player.objects.create(
            name="Kylian Mbappé",
            fc27_id="231747",
            position="ST",
            overall=91,
            is_free_agent=True,
        )
        self.hakimi = Player.objects.create(
            name="Achraf Hakimi",
            fc27_id="235212",
            position="RB",
            overall=89,
            is_free_agent=True,
        )
        self.vvd = Player.objects.create(
            name="Virgil van Dijk",
            fc27_id="203376",
            position="CB",
            overall=89,
            is_free_agent=True,
        )
        self.club_st = Player.objects.create(
            name="Club Striker",
            fc27_id="club-st",
            position="ST",
            overall=72,
            is_free_agent=False,
            mgl_team=self.team,
        )
        self.client.login(username="searchuser", password="test-pass-123")

    def test_card_name_uses_recognised_display_name(self):
        self.assertEqual(card_name(self.salah), "MOHAMED SALAH")
        self.assertEqual(card_name(self.mbappe), "KYLIAN MBAPPÉ")
        self.assertEqual(card_name(self.hakimi), "ACHRAF HAKIMI")
        self.assertEqual(card_name(self.vvd), "VIRGIL VAN DIJK")
        self.assertNotEqual(card_name(self.vvd), "DIJK")

    def test_free_agent_search_cases(self):
        cases = [
            ("Salah", "MOHAMED SALAH", self.salah.id),
            ("salah", "MOHAMED SALAH", self.salah.id),
            ("SALAH", "MOHAMED SALAH", self.salah.id),
            ("Mbappe", "KYLIAN MBAPPÉ", self.mbappe.id),
            ("Mbappé", "KYLIAN MBAPPÉ", self.mbappe.id),
            ("Hakimi", "ACHRAF HAKIMI", self.hakimi.id),
            ("van Dijk", "VIRGIL VAN DIJK", self.vvd.id),
        ]
        for query, expected, player_id in cases:
            response = self.client.get(reverse("free_agents"), {"search": query})
            self.assertEqual(response.status_code, 200, query)
            self.assertContains(response, 'placeholder="Search players..."')
            self.assertContains(response, expected)
            self.assertContains(response, reverse("player_profile", args=[player_id]))
            self.assertNotContains(response, "Ghaly")
            self.assertNotContains(response, "Lottin")
            self.assertNotContains(response, "Mouh")
            self.assertNotContains(response, "Club Striker")

    def test_all_players_search_and_filters(self):
        response = self.client.get(
            reverse("player_database"),
            {"search": "Mbappe", "position": "ST"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'placeholder="Search players..."')
        self.assertContains(response, "KYLIAN MBAPPÉ")
        self.assertContains(response, reverse("player_profile", args=[self.mbappe.id]))
        self.assertNotContains(response, "MOHAMED SALAH")
        self.assertNotContains(response, "CLUB STRIKER")

        missed = self.client.get(
            reverse("player_database"),
            {"search": "Mbappe", "position": "CB"},
        )
        self.assertContains(missed, "NO PLAYERS FOUND")
        self.assertNotContains(missed, "KYLIAN MBAPPÉ")

        accent = self.client.get(reverse("player_database"), {"search": "Mbappé"})
        self.assertContains(accent, "KYLIAN MBAPPÉ")

    def test_search_no_results(self):
        none_fa = self.client.get(reverse("free_agents"), {"search": "zzxqnotaplayer"})
        self.assertContains(none_fa, "NO PLAYERS FOUND")
        none_all = self.client.get(
            reverse("player_database"), {"search": "zzxqnotaplayer"}
        )
        self.assertContains(none_all, "NO PLAYERS FOUND")

    def test_search_pagination_keeps_query(self):
        for index in range(41):
            Player.objects.create(
                name=f"Cloneagent {index:02d}",
                fc27_id=f"clone-{index}",
                position="CM",
                overall=60,
                is_free_agent=True,
            )
        page_two = self.client.get(
            reverse("free_agents"),
            {"search": "Cloneagent", "page": "2"},
        )
        self.assertEqual(page_two.status_code, 200)
        self.assertContains(page_two, "Page 2 of")
        self.assertContains(page_two, "search=Cloneagent")
        self.assertContains(page_two, "CLONEAGENT")

        all_page = self.client.get(
            reverse("player_database"),
            {"search": "Cloneagent", "page": "2"},
        )
        self.assertEqual(all_page.status_code, 200)
        self.assertContains(all_page, "Page 2 of")
        self.assertContains(all_page, "search=Cloneagent")

    def test_free_agent_search_with_position_filter(self):
        response = self.client.get(
            reverse("free_agents"),
            {"search": "Mbappe", "position": "ST"},
        )
        self.assertContains(response, "KYLIAN MBAPPÉ")
        blocked = self.client.get(
            reverse("free_agents"),
            {"search": "Hakimi", "position": "ST"},
        )
        self.assertContains(blocked, "NO PLAYERS FOUND")

    def test_no_duplicate_player_records(self):
        duplicates = (
            Player.objects.exclude(fc27_id="")
            .values("fc27_id")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
        )
        self.assertFalse(list(duplicates))
        self.assertEqual(Player.objects.filter(fc27_id="231747").count(), 1)
        self.assertEqual(Player.objects.filter(name="Kylian Mbappé").count(), 1)

    def test_van_dijk_card_on_free_agents_page(self):
        response = self.client.get(reverse("free_agents"), {"search": "van Dijk"})
        self.assertContains(response, "VIRGIL VAN DIJK")
        self.assertNotContains(response, ">DIJK<")
