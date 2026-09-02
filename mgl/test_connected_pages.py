from django.test import Client, TestCase
from django.urls import reverse

from leagues.services import ensure_premier_league
from mgl.models import NewsPost
from mgl.page_links import page_links_for_news
from mgl.services import create_news
from players.models import Player
from teams.models import Team


class ConnectedPagesTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.team = Team.objects.filter(league=self.league).order_by("name").first()
        if self.team is None:
            self.team = Team.objects.create(
                name="Connected FC",
                short_name="CFC",
                league=self.league,
            )
        self.player = Player.objects.create(
            name="Connected Striker",
            position="ST",
            overall=80,
            goals=3,
            assists=1,
            mgl_team=self.team,
            is_free_agent=False,
        )

    def test_league_pages_use_live_table_and_leaders(self):
        for slug in ("premier-league", "championship", "league-one"):
            page = self.client.get(reverse("competition_page", kwargs={"slug": slug}))
            self.assertEqual(page.status_code, 200, slug)
        home = self.client.get(reverse("competition_page", kwargs={"slug": "premier-league"}))
        self.assertContains(home, "TOP SCORERS")
        self.assertContains(home, "TOP ASSISTS")
        self.assertContains(home, reverse("player_profile", args=[self.player.id]))
        self.assertContains(home, self.team.name)
        all_leagues = self.client.get(reverse("leagues_page"))
        self.assertContains(all_leagues, "Premier League")
        self.assertContains(all_leagues, "Championship")
        self.assertContains(all_leagues, "League One")
        self.assertContains(all_leagues, "Open league")
        self.assertEqual(self.client.get("/leagues/all/").status_code, 200)
        self.assertContains(self.client.get("/leagues/all/"), "Open league")

    def test_cup_pages_stay_empty_until_live(self):
        hub = self.client.get(reverse("competition_page", kwargs={"slug": "cups"}))
        self.assertContains(hub, "LIVE NOW")
        self.assertContains(hub, "RECENTLY WON")
        self.assertContains(hub, "UPCOMING")
        self.assertContains(hub, reverse("competition_page", kwargs={"slug": "phantom-cup"}))
        self.assertEqual(self.client.get("/cups/").status_code, 200)
        cl = self.client.get("/cups/champions-league/")
        self.assertEqual(cl.status_code, 200)
        self.assertContains(cl, "NO LIVE COMPETITION DATA")
        self.assertContains(cl, "GROUP STAGE")
        self.assertContains(cl, "KNOCKOUT")
        self.assertNotContains(cl, ">FIXTURES</a>")
        conference = self.client.get("/cups/conference-league/")
        self.assertContains(conference, ">TABLE</a>")
        self.assertContains(conference, ">CLUBS</a>")
        phantom = self.client.get("/cups/phantom-cup/")
        self.assertContains(phantom, ">BRACKET</a>")
        self.assertContains(phantom, "Knockout stages")

    def test_club_tabs_and_clickable_players(self):
        page = self.client.get(reverse("club_page", args=[self.team.short_name]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "OVERVIEW")
        self.assertContains(page, "SQUAD")
        self.assertContains(page, reverse("player_profile", args=[self.player.id]))
        squad = self.client.get(reverse("club_page", args=[self.team.short_name]), {"tab": "squad"})
        self.assertContains(squad, "mgl-player-card-grid")
        self.assertEqual(self.client.get(f"/teams/{self.team.short_name}/").status_code, 200)
        self.assertEqual(
            reverse("club_page", args=[self.team.short_name]),
            f"/teams/{self.team.short_name}/",
        )
        self.assertEqual(
            self.client.get(f"/clubs/{self.team.short_name}/").status_code,
            200,
        )

    def test_player_profile_has_no_recent_results(self):
        page = self.client.get(reverse("player_profile", args=[self.player.id]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "RECENT RESULTS")
        self.assertContains(page, "SEASON STATISTICS")
        self.assertContains(page, "TRANSFER HISTORY")
        alias = self.client.get(f"/players/{self.player.id}/")
        self.assertEqual(alias.status_code, 200)
        self.assertEqual(reverse("player_profile", args=[self.player.id]), f"/players/{self.player.id}/")
        self.assertEqual(
            self.client.get(f"/mgl/players/{self.player.id}/").status_code,
            200,
        )

    def test_job_centre_still_uses_existing_vacancies(self):
        page = self.client.get(reverse("job_centre"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "HOW IT WORKS")
        self.assertContains(page, "RECENTLY FILLED")

    def test_discord_payload_includes_existing_page_links(self):
        post = create_news(
            NewsPost.RESULTS,
            "Official result",
            "Approved.",
            team=self.team,
            details={"player_id": self.player.id},
        )
        links = {item["label"]: item["url"] for item in page_links_for_news(post)}
        self.assertIn("VIEW CLUB", links)
        self.assertEqual(links["VIEW PLAYER"], reverse("player_profile", args=[self.player.id]))
        self.assertTrue(links["VIEW PLAYER"].startswith("/players/"))
        self.assertTrue(links["VIEW CLUB"].startswith("/teams/"))
        self.assertIn("VIEW LEAGUE", links)
        event = post.discord_events.first()
        self.assertIsNotNone(event)
        self.assertIn("page_links", event.payload)
        self.assertEqual(event.status, "PENDING")

    def test_discord_links_cover_transfer_job_and_competition(self):
        transfer = create_news(
            NewsPost.TRANSFER,
            "Player sold",
            "Approved transfer.",
            team=self.team,
            details={"player_id": self.player.id, "competition_slug": "champions-league"},
        )
        transfer_links = {item["label"]: item["url"] for item in page_links_for_news(transfer)}
        self.assertEqual(transfer_links["VIEW TRANSFER"], reverse("public_transfers"))
        self.assertEqual(
            transfer_links["VIEW COMPETITION"],
            reverse("cups_detail", kwargs={"slug": "champions-league"}),
        )
        job = NewsPost(
            category="JOBS",
            title="Vacancy",
            body="Club available.",
            primary_team=self.team,
        )
        job.primary_team_id = self.team.id
        job_links = {item["label"]: item["url"] for item in page_links_for_news(job)}
        self.assertEqual(job_links["VIEW JOB"], reverse("job_centre"))
        self.assertEqual(transfer.discord_events.first().status, "PENDING")

    def test_signed_in_header_order_and_market_aliases(self):
        from decimal import Decimal

        from accounts.models import User
        from managers.models import ManagerApplication

        user = User.objects.create_user(username="pageorder", password="test-pass-123")
        ManagerApplication.objects.create(
            user=user,
            display_name="Page Order",
            gamertag="PGO1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("20.00"),
        )
        self.client.login(username="pageorder", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        nav = hub.content.decode().split('<nav class="mgl-nav"', 1)[1].split("</nav>", 1)[0]
        positions = [
            nav.find(">HOME<"),
            nav.find('data-nav-dropdown="career"'),
            nav.find('data-nav-dropdown="market"'),
            nav.find('data-nav-dropdown="leagues"'),
            nav.find("JOB CENTRE"),
            nav.find('data-nav-dropdown="stats"'),
            nav.find('data-nav-dropdown="history"'),
            nav.find('data-nav-dropdown="cups"'),
        ]
        self.assertTrue(all(index >= 0 for index in positions), positions)
        self.assertEqual(positions, sorted(positions))
        self.assertContains(hub, "All Players")
        self.assertContains(hub, reverse("player_database"))
        self.assertEqual(self.client.get("/market/players/").status_code, 200)
        self.assertEqual(self.client.get("/mgl/players/").status_code, 200)
