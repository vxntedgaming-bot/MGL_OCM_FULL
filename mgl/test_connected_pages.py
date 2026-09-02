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
        self.assertEqual(self.client.get("/leagues/all/").status_code, 302)

    def test_cup_pages_stay_empty_until_live(self):
        hub = self.client.get(reverse("competition_page", kwargs={"slug": "cups"}))
        self.assertContains(hub, "LIVE NOW")
        self.assertContains(hub, "RECENTLY WON")
        self.assertContains(hub, "UPCOMING")
        self.assertContains(hub, reverse("competition_page", kwargs={"slug": "phantom-cup"}))
        self.assertEqual(self.client.get("/cups/").status_code, 302)
        cl = self.client.get("/cups/champions-league/", follow=True)
        self.assertContains(cl, "NO LIVE COMPETITION DATA")
        self.assertContains(cl, "GROUP STAGE")
        self.assertContains(cl, "KNOCKOUT")

    def test_club_tabs_and_clickable_players(self):
        page = self.client.get(reverse("club_page", args=[self.team.short_name]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "OVERVIEW")
        self.assertContains(page, "SQUAD")
        self.assertContains(page, reverse("player_profile", args=[self.player.id]))
        squad = self.client.get(reverse("club_page", args=[self.team.short_name]), {"tab": "squad"})
        self.assertContains(squad, "mgl-player-card-grid")
        self.assertEqual(self.client.get(f"/teams/{self.team.short_name}/").status_code, 302)

    def test_player_profile_has_no_recent_results(self):
        page = self.client.get(reverse("player_profile", args=[self.player.id]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "RECENT RESULTS")
        self.assertContains(page, "SEASON STATISTICS")
        self.assertContains(page, "TRANSFER HISTORY")
        alias = self.client.get(f"/players/{self.player.id}/")
        self.assertEqual(alias.status_code, 302)

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
        event = post.discord_events.first()
        self.assertIsNotNone(event)
        self.assertIn("page_links", event.payload)
        self.assertEqual(event.status, "PENDING")
