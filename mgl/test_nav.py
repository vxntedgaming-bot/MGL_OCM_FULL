from decimal import Decimal

from django.db.models import Count
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_super_league_1
from managers.models import ManagerApplication
from mgl.nav import NAV_DROPDOWNS, SIGNED_IN_NAV_DROPDOWNS, nav_dropdowns_for_request
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
        for source in (NAV_DROPDOWNS, SIGNED_IN_NAV_DROPDOWNS):
            for menu in source:
                for item in menu["items"]:
                    if item.get("href"):
                        self.assertTrue(item["href"].startswith("/"), item)
                        continue
                    url = reverse(item["url_name"], kwargs=item.get("url_kwargs") or None)
                    self.assertTrue(url.startswith("/"), item)
                    self.assertNotEqual(url, "#")

    def test_homepage_renders_all_dropdowns(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("core/js/mgl-nav.js", html)
        self.assertIn('data-nav-trigger', html)
        self.assertNotIn('data-nav-dropdown="my-team"', html)
        self.assertNotIn('data-nav-dropdown="market"', html)
        self.assertIn('data-nav-dropdown="leagues"', html)
        self.assertIn('data-nav-dropdown="stats"', html)
        self.assertIn('data-nav-dropdown="news"', html)
        self.assertNotIn('data-nav-dropdown="about"', html)
        self.assertContains(response, "Pressroom")
        self.assertContains(response, "Live Activity")
        self.assertNotContains(response, "About MGL")
        self.assertNotContains(response, "How It Works")
        self.assertNotContains(response, "#mgl-about")
        self.assertNotContains(response, "#mgl-how")
        self.assertNotContains(response, "ABOUT MGL")
        self.assertNotContains(response, "Latest News")
        self.assertNotContains(response, "Official News")
        self.assertNotContains(response, "MY TEAM")
        self.assertNotContains(response, "TRANSFERS")
        self.assertContains(response, "TABLES")
        self.assertContains(response, "STATISTICS")
        self.assertContains(response, "JOBS")
        self.assertContains(response, "LOGIN")
        self.assertContains(response, "SIGN UP")
        self.assertNotContains(response, ">JOIN<")
        self.assertNotContains(response, "Team Management")
        self.assertNotContains(response, ">TEAMS<")
        self.assertNotContains(response, reverse("team_management"))
        self.assertNotContains(response, "Transfer Market")
        self.assertNotContains(response, "Recruitment Drive")
        self.assertNotContains(response, "Youth Academy")
        self.assertNotContains(response, reverse("transfer_history"))
        self.assertNotContains(response, reverse("transfer_market"))
        self.assertNotContains(response, reverse("free_agents"))
        self.assertContains(response, reverse("job_centre"))
        self.assertNotContains(response, reverse("scouting"))
        self.assertNotContains(response, "/market/youth-academy/")
        self.assertNotContains(response, reverse("live_auctions"))
        self.assertNotContains(response, reverse("player_database"))
        self.assertContains(response, "All Leagues")
        self.assertContains(response, "Premier League")
        self.assertContains(response, "Championship")
        self.assertContains(response, "League One")
        self.assertNotContains(response, reverse("competition_page", kwargs={"slug": "mls"}))
        self.assertNotContains(response, reverse("unassigned_players"))
        self.assertNotContains(response, "UNASSIGNED PLAYERS")
        self.assertContains(response, "Cups")
        self.assertNotContains(response, "WAITING ROOM")
        self.assertNotContains(response, "WAITING ROOM LEAGUE")
        self.assertContains(response, reverse("leagues_page"))
        self.assertContains(
            response, reverse("competition_page", kwargs={"slug": "premier-league"})
        )
        self.assertNotContains(
            response, reverse("competition_page", kwargs={"slug": "waiting-room"})
        )
        self.assertContains(response, "Premier League Stats")
        self.assertContains(response, "Championship Stats")
        self.assertContains(response, "League One Stats")
        self.assertContains(
            response, reverse("league_stats", kwargs={"slug": "premier-league"})
        )
        self.assertContains(
            response, reverse("league_stats", kwargs={"slug": "championship"})
        )
        self.assertContains(
            response, reverse("league_stats", kwargs={"slug": "league-one"})
        )
        self.assertNotContains(response, "STATS HUB")
        self.assertNotContains(response, "COMPARE")
        self.assertNotContains(response, reverse("compare_players"))
        self.assertNotContains(response, reverse("historical_tables"))
        self.assertNotContains(response, "/stats/head-to-head/")
        self.assertNotContains(response, "Head To Head")
        self.assertNotContains(response, reverse("manager_search"))
        self.assertNotContains(response, "Super League 2")
        self.assertIn("mgl-nav-chevron", html)
        self.assertIn('aria-expanded="false"', html)
        self.assertEqual(self.client.get(reverse("job_centre")).status_code, 200)
        self.assertEqual(self.client.get(reverse("fixture_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("clubs_index")).status_code, 200)

    def test_public_nav_omits_private_destinations(self):
        response = self.client.get("/")
        html = response.content.decode()
        nav = html.split('<nav class="mgl-nav"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("HOME", nav)
        self.assertIn("TABLES", nav)
        self.assertIn("STATISTICS", nav)
        self.assertIn("JOBS", nav)
        self.assertIn("NEWS", nav)
        self.assertNotIn("ABOUT", nav)
        self.assertIn("LOGIN", nav)
        self.assertIn("SIGN UP", nav)
        self.assertNotIn("FIXTURES", nav)
        self.assertNotIn("TEAMS", nav)
        self.assertNotIn("TRANSFERS", nav)
        self.assertNotIn("MY TEAM", nav)
        self.assertNotIn("MY CLUB", nav)
        self.assertNotIn("MARKET", nav)
        self.assertNotIn("COMMUNITY", nav)
        self.assertNotIn("CONTROL", nav)
        self.assertNotIn("ACCOUNT", nav)

    def test_market_dropdown_highlights_current_page(self):
        self.client.login(username="navuser", password="test-pass-123")
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

    def test_my_club_dropdown_highlights_when_logged_in(self):
        self.client.login(username="navuser", password="test-pass-123")
        response = self.client.get(reverse("team_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-nav-dropdown="my-club"')
        self.assertContains(response, reverse("fixture_list"))
        self.assertContains(response, "ACCOUNT")
        self.assertContains(response, "data-notify-dropdown")
        self.assertNotContains(response, "ACTION REQUIRED")
        self.assertNotContains(response, 'data-nav-dropdown="my-team"')
        self.assertNotContains(response, reverse("control_centre"))

    def test_stats_dropdown_pages_load(self):
        for slug in ("premier-league", "championship", "league-one"):
            response = self.client.get(
                reverse("league_stats", kwargs={"slug": slug})
            )
            self.assertEqual(response.status_code, 200, slug)
            self.assertContains(response, 'data-nav-dropdown="stats"')
            self.assertContains(response, "mgl-nav-item--sub is-current")
            self.assertNotContains(response, "WAITING ROOM")
            self.assertNotContains(response, "COMPARE")
            self.assertNotContains(response, "Super League 2")
        hub = self.client.get(reverse("stats_page"))
        self.assertEqual(hub.status_code, 200)
        self.assertContains(hub, "PREMIER LEAGUE STATS")

    def test_waiting_room_and_compare_are_gone(self):
        waiting = self.client.get(
            reverse("competition_page", kwargs={"slug": "waiting-room"})
        )
        self.assertEqual(waiting.status_code, 404)
        compare = self.client.get(reverse("compare_players"))
        self.assertEqual(compare.status_code, 404)
        home = self.client.get("/")
        self.assertNotContains(home, "WAITING ROOM")
        self.assertNotContains(home, reverse("compare_players"))

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
        self.assertEqual(current_labels, ["Free Agents"])
        self.assertFalse(menus["my-team"]["is_current"])

    def test_unassigned_players_nav_is_admin_only(self):
        anonymous = self.client.get("/")
        self.assertNotContains(anonymous, reverse("unassigned_players"))
        self.client.login(username="navuser", password="test-pass-123")
        manager = self.client.get("/")
        self.assertNotContains(manager, reverse("unassigned_players"))
        self.assertNotContains(manager, "Unassigned Players")
        User.objects.create_user(
            username="navowner",
            password="test-pass-123",
            role=User.OWNER,
        )
        self.client.login(username="navowner", password="test-pass-123")
        owner = self.client.get("/")
        self.assertContains(owner, reverse("control_centre"))
        self.assertContains(owner, "CONTROL")
        self.assertNotContains(owner, reverse("unassigned_players"))
        self.assertNotContains(owner, "Unassigned Players")

    def test_assigned_manager_gets_manager_nav(self):
        league = ensure_super_league_1()
        team = Team.objects.filter(short_name="LIV").first() or Team.objects.create(
            name="Liverpool",
            short_name="LIV",
            league=league,
        )
        team.manager = self.user
        team.save(update_fields=["manager"])
        self.client.login(username="navuser", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        self.assertEqual(hub.status_code, 200)
        html = hub.content.decode()
        self.assertIn('data-nav-dropdown="my-club"', html)
        self.assertIn('data-nav-dropdown="market"', html)
        self.assertIn('data-nav-dropdown="community"', html)
        self.assertIn('data-nav-dropdown="news"', html)
        self.assertContains(hub, "MY CLUB")
        self.assertContains(hub, "MARKET")
        self.assertContains(hub, "Scouting")
        self.assertNotContains(hub, "Academy")
        self.assertNotContains(hub, "Head To Head")
        self.assertContains(hub, "History")
        self.assertContains(hub, "Live Activity")
        self.assertContains(hub, "Pressroom")
        self.assertNotContains(hub, 'data-nav-dropdown="about"')
        self.assertNotContains(hub, "About MGL")
        self.assertContains(hub, reverse("scouting"))
        self.assertNotContains(hub, "/market/youth-academy/")
        self.assertNotContains(hub, "/stats/head-to-head/")
        self.assertContains(hub, reverse("live_activity"))
        self.assertContains(hub, reverse("pressroom"))
        self.assertContains(hub, reverse("historical_tables"))
        self.assertContains(hub, reverse("manager_notifications"))
        self.assertContains(hub, "JOBS")
        self.assertContains(hub, reverse("job_centre"))
        self.assertContains(hub, "data-notify-dropdown")
        self.assertNotContains(hub, "ACTION REQUIRED")
        self.assertNotContains(hub, "Propose Transfer")
        self.assertNotContains(hub, "Recruitment Drive")
        self.assertContains(hub, "TABLES")
        self.assertContains(hub, "STATISTICS")
        self.assertContains(hub, "Premier League Stats")
        self.assertContains(hub, reverse("leagues_page"))
        self.assertContains(
            hub, reverse("league_stats", kwargs={"slug": "premier-league"})
        )
        self.assertIn('data-nav-dropdown="leagues"', html)
        self.assertIn('data-nav-dropdown="stats"', html)
        self.assertNotContains(hub, "WAITING ROOM")
        self.assertNotContains(hub, reverse("compare_players"))
        self.assertNotContains(hub, reverse("control_centre"))
        self.assertNotContains(hub, "UNASSIGNED PLAYERS")
        self.assertNotContains(hub, reverse("unassigned_players"))
        self.assertNotContains(hub, 'data-nav-dropdown="my-team"')
        self.assertNotContains(hub, 'data-nav-dropdown="transfers"')
        self.assertNotContains(hub, 'data-nav-dropdown="recruitment"')

    def test_signed_in_nav_shows_tables_and_stats_for_every_role(self):
        User.objects.create_user(
            username="navadmin",
            password="test-pass-123",
            role=User.ADMIN,
        )
        User.objects.create_user(
            username="navowner2",
            password="test-pass-123",
            role=User.OWNER,
        )
        tables = reverse("leagues_page")
        stats = reverse("league_stats", kwargs={"slug": "premier-league"})
        for username in ("navuser", "navadmin", "navowner2"):
            self.client.logout()
            self.client.login(username=username, password="test-pass-123")
            page = self.client.get("/")
            self.assertEqual(page.status_code, 200, username)
            nav = page.content.decode().split('<nav class="mgl-nav"', 1)[1].split(
                "</nav>", 1
            )[0]
            self.assertIn("HOME", nav)
            self.assertIn("MY CLUB", nav)
            self.assertIn("MARKET", nav)
            self.assertIn("COMMUNITY", nav)
            self.assertIn("TABLES", nav)
            self.assertIn("STATISTICS", nav)
            self.assertIn("NEWS", nav)
            self.assertIn("JOBS", nav)
            self.assertNotIn("ABOUT", nav)
            self.assertNotIn('data-nav-dropdown="about"', nav)
            self.assertIn(tables, nav)
            self.assertIn(stats, nav)
            self.assertIn('data-nav-dropdown="leagues"', nav)
            self.assertIn('data-nav-dropdown="stats"', nav)
            tables_page = self.client.get(tables)
            self.assertEqual(tables_page.status_code, 200, username)
            self.assertContains(tables_page, "ALL LEAGUE")
            stats_page = self.client.get(stats)
            self.assertEqual(stats_page.status_code, 200, username)
            self.assertContains(stats_page, "PREMIER LEAGUE STATS")
        self.client.logout()
        public = self.client.get("/")
        public_nav = public.content.decode().split('<nav class="mgl-nav"', 1)[1].split(
            "</nav>", 1
        )[0]
        self.assertIn("TABLES", public_nav)
        self.assertIn("STATISTICS", public_nav)
        self.assertNotIn("MY CLUB", public_nav)
        self.assertNotIn("MARKET", public_nav)
        self.assertNotIn("COMMUNITY", public_nav)


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

    def test_free_agents_page_uses_table_layout_and_group_filters(self):
        public = self.client.get(reverse("free_agents"))
        self.assertContains(public, "core/css/mgl-free-agents.css")
        self.assertContains(public, "DEFENDERS")
        self.assertContains(public, "MIDFIELDERS")
        self.assertContains(public, "ATTACKERS")
        self.assertContains(public, "MIN OVR")
        self.assertContains(public, ">PLAYER</span>")
        self.assertContains(public, ">ACTION</span>")
        self.assertContains(public, "VIEW PLAYER")
        self.assertNotContains(public, "SIGN FOR 0 TKN")
        self.assertNotContains(public, "REQUEST TO SIGN")
        self.assertNotContains(public, "Ander Guevara")

        defenders = self.client.get(reverse("free_agents"), {"position": "DEFENDERS"})
        self.assertContains(defenders, "VIRGIL VAN DIJK")
        self.assertContains(defenders, "ACHRAF HAKIMI")
        self.assertNotContains(defenders, "KYLIAN MBAPPÉ")
        self.assertNotContains(defenders, "MOHAMED SALAH")

        attackers = self.client.get(reverse("free_agents"), {"position": "ATTACKERS"})
        self.assertContains(attackers, "KYLIAN MBAPPÉ")
        self.assertNotContains(attackers, "VIRGIL VAN DIJK")

        club = Team.objects.create(
            name="Search Club",
            short_name="SCH",
            league=self.league,
            manager=self.user,
        )
        signed_in = self.client.get(reverse("free_agents"))
        self.assertContains(signed_in, ">BUY</button>")
        self.assertNotContains(signed_in, "SIGN FOR 0 TKN")
        self.assertContains(signed_in, reverse("sign_free_agent", args=[self.vvd.id]))

        self.client.logout()
        guest = self.client.get(reverse("free_agents"))
        self.assertEqual(guest.status_code, 302)
        self.assertIn("/login/", guest["Location"])
