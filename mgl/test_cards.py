from decimal import Decimal
from pathlib import Path

from django.template import Context, Template
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.services import ensure_super_league_1
from managers.models import ManagerApplication
from mgl.models import PlayerListing
from mgl.templatetags.mgl_ui import card_name, player_tier
from players.models import Player
from teams.badges import static_badge_path
from teams.models import Team


class PlayerCardAndBadgeTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_super_league_1()
        self.team = Team.objects.filter(short_name="ARS").first() or Team.objects.create(
            name="Arsenal",
            short_name="ARS",
            league=self.league,
        )
        self.gold = Player.objects.create(
            name="Gold Striker",
            position="ST",
            overall=80,
            pace=81,
            shooting=82,
            passing=70,
            dribbling=75,
            defending=40,
            physical=72,
            nationality="England",
            mgl_team=self.team,
            is_free_agent=False,
        )
        now = timezone.now()
        self.silver = Player.objects.create(
            name="Silver Mid",
            position="CM",
            overall=70,
            is_free_agent=True,
            released_at=now,
        )
        self.bronze = Player.objects.create(
            name="Bronze Back",
            position="CB",
            overall=60,
            is_free_agent=True,
            released_at=now,
        )
        self.user = User.objects.create_user(
            username="carduser",
            password="test-pass-123",
        )
        self.manager = ManagerApplication.objects.create(
            user=self.user,
            display_name="Card User",
            gamertag="CU1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("50.00"),
        )

    def test_official_badge_path_uses_frozen_badge_code(self):
        self.assertEqual(self.team.badge_code, "ARS")
        self.assertEqual(static_badge_path(self.team), "core/img/clubs/ARS.svg")
        self.assertEqual(static_badge_path(None), "")
        self.team.short_name = "XXX"
        self.assertEqual(static_badge_path(self.team), "core/img/clubs/ARS.svg")

    def test_homepage_renders_club_badges(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "core/img/clubs/ARS.svg")
        self.assertContains(response, "Arsenal")

    def test_player_profile_uses_reusable_card_and_free_agent_copy(self):
        self.client.login(username="carduser", password="test-pass-123")
        gold = self.client.get(reverse("player_profile", args=[self.gold.id]))
        self.assertEqual(gold.status_code, 200)
        self.assertContains(gold, "mgl/cards/gold_card.png")
        self.assertContains(gold, "Arsenal")
        self.assertContains(gold, "PAC")
        self.assertContains(gold, "NO DATA YET")

        silver = self.client.get(reverse("player_profile", args=[self.silver.id]))
        self.assertContains(silver, "mgl/cards/silver_card.png")
        self.assertContains(silver, "FREE AGENT")
        self.assertNotContains(silver, "core/img/clubs/")

        bronze = self.client.get(reverse("player_profile", args=[self.bronze.id]))
        self.assertContains(bronze, "mgl/cards/bronze_card.png")

        self.gold.player_face_url = "https://cdn.sofifa.net/players/209/331/26_120.png"
        self.gold.fc27_id = "209331"
        self.gold.save(update_fields=["player_face_url", "fc27_id"])
        gold_face = self.client.get(reverse("player_profile", args=[self.gold.id]))
        self.assertContains(gold_face, reverse("player_face_image", args=[self.gold.id]))
        self.assertContains(gold_face, "mgl-player-face")
        self.assertContains(gold_face, "Arsenal")

        self.silver.player_face_url = "https://cdn.sofifa.net/players/231/747/26_120.png"
        self.silver.save(update_fields=["player_face_url"])
        silver_face = self.client.get(reverse("player_profile", args=[self.silver.id]))
        self.assertContains(silver_face, reverse("player_face_image", args=[self.silver.id]))
        self.assertContains(silver_face, "FREE AGENT")
        self.assertContains(silver_face, "onerror=")

    def test_player_database_filters_and_cards(self):
        self.assertEqual(self.client.get(reverse("player_database")).status_code, 302)
        self.client.login(username="carduser", password="test-pass-123")
        response = self.client.get(reverse("player_database"), {"tier": "GOLD"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GOLD STRIKER")
        self.assertContains(response, "mgl/cards/gold_card.png")
        self.assertNotContains(response, "Bronze Back")

        free = self.client.get(reverse("player_database"), {"free": "1"})
        self.assertContains(free, "SILVER MID")
        self.assertNotContains(free, "GOLD STRIKER")

    def test_market_and_squad_keep_permissions(self):
        self.team.manager = self.user
        self.team.save(update_fields=["manager"])
        listing = PlayerListing.objects.create(
            player=self.gold,
            team=self.team,
            seller=self.manager,
            asking_price=Decimal("12.00"),
            status=PlayerListing.LIVE,
        )
        self.assertEqual(self.client.get(reverse("transfer_market")).status_code, 200)
        self.client.login(username="carduser", password="test-pass-123")
        market = self.client.get(reverse("transfer_market"))
        self.assertEqual(market.status_code, 200)
        self.assertContains(market, "Gold Striker")
        self.assertContains(market, "12")
        self.assertNotContains(market, "BUY NOW")

        self.client.login(username="carduser", password="test-pass-123")
        squad = self.client.get(reverse("team_management"))
        self.assertEqual(squad.status_code, 200)
        self.assertContains(squad, "GOLD STRIKER")
        self.assertContains(squad, "mgl-squad-table")
        self.assertContains(squad, "TRANSFER LISTED")
        self.assertContains(squad, "WITHDRAW")
        self.assertNotContains(squad, "SELL A PLAYER")
        self.assertNotContains(squad, "LIST FOR SALE")
        self.assertNotContains(squad, "TOKEN ASKING PRICE")
        return listing

    def test_card_stats_put_abbreviation_above_value_in_six_columns(self):
        from pathlib import Path

        css = Path("core/static/core/css/mgl.css").read_text(encoding="utf-8")
        layout = css[css.rfind("PLAYER CARD TYPOGRAPHY") :]
        self.assertIn("grid-template-columns: repeat(6, 1fr)", layout)
        self.assertIn("container-type: inline-size", layout)

        self.client.login(username="carduser", password="test-pass-123")
        gold = self.client.get(reverse("player_profile", args=[self.gold.id]))
        self.assertContains(gold, "<span>PAC</span><strong>81</strong>", html=False)
        self.assertContains(gold, "<span>SHO</span><strong>82</strong>", html=False)
        self.assertContains(gold, "<span>PHY</span><strong>72</strong>", html=False)
        self.assertContains(gold, "mgl-player-card--gold")
        self.assertContains(gold, "mgl-player-card--large")

        silver = self.client.get(reverse("player_profile", args=[self.silver.id]))
        self.assertContains(silver, "mgl-player-card--silver")
        self.assertContains(silver, "FREE AGENT")

        bronze = self.client.get(reverse("player_profile", args=[self.bronze.id]))
        self.assertContains(bronze, "mgl-player-card--bronze")
        self.assertContains(bronze, "CB")
        self.assertContains(bronze, "mgl-card-identity")


def render_player_card(player, size="standard"):
    return Template(
        "{% load mgl_ui %}{% player_card player size linked=False %}"
    ).render(Context({"player": player, "size": size}))


class PlayerCardQaTests(TestCase):
    def setUp(self):
        self.league = ensure_super_league_1()
        self.team = Team.objects.filter(short_name="ARS").first() or Team.objects.create(
            name="Arsenal",
            short_name="ARS",
            league=self.league,
        )

    def test_css_keeps_overlays_inside_shield_with_even_stat_columns(self):
        css = Path("core/static/core/css/mgl.css").read_text(encoding="utf-8")
        layout = css[css.rfind("PLAYER CARD COORDINATE SYSTEM") :]
        self.assertIn("aspect-ratio: 1107 / 1536", layout)
        self.assertIn("overflow: hidden", layout)
        self.assertIn("grid-template-columns: repeat(6, 1fr)", layout)
        self.assertIn("align-items: end", layout)
        self.assertIn("text-overflow: ellipsis", layout)
        self.assertIn("white-space: nowrap", layout)
        self.assertIn("bottom: 14%", layout)
        self.assertNotIn("position: fixed", layout)

    def test_tier_artwork_ovr_and_sizes(self):
        gold = Player(name="High Gold", position="ST", overall=91, mgl_team=self.team)
        silver = Player(name="Mid Silver", position="CM", overall=70)
        bronze = Player(name="Low Bronze", position="GK", overall=48)
        self.assertEqual(player_tier(gold), "GOLD")
        self.assertEqual(player_tier(silver), "SILVER")
        self.assertEqual(player_tier(bronze), "BRONZE")

        gold_html = render_player_card(gold, "large")
        silver_html = render_player_card(silver, "standard")
        bronze_html = render_player_card(bronze, "small")

        self.assertIn("mgl/cards/gold_card.png", gold_html)
        self.assertIn("mgl-player-card--gold", gold_html)
        self.assertIn("mgl-player-card--large", gold_html)
        self.assertIn("<strong>91</strong>", gold_html)
        self.assertIn("<span>OVR</span>", gold_html)
        self.assertIn("mgl-card-position", gold_html)
        self.assertIn(">ST<", gold_html)
        self.assertIn(">ARS<", gold_html)
        self.assertIn("core/img/clubs/ARS.svg", gold_html)

        self.assertIn("mgl/cards/silver_card.png", silver_html)
        self.assertIn("mgl-player-card--silver", silver_html)
        self.assertIn("mgl-player-card--standard", silver_html)
        self.assertIn("<strong>70</strong>", silver_html)
        self.assertIn("UNASSIGNED", silver_html)
        self.assertNotIn("FREE AGENT", silver_html)
        self.assertNotIn("core/img/clubs/", silver_html)
        self.assertNotIn("mgl-team-logo", silver_html)

        self.assertIn("mgl/cards/bronze_card.png", bronze_html)
        self.assertIn("mgl-player-card--bronze", bronze_html)
        self.assertIn("mgl-player-card--small", bronze_html)
        self.assertIn("<strong>48</strong>", bronze_html)
        self.assertIn("UNASSIGNED", bronze_html)
        self.assertNotIn("FREE AGENT", bronze_html)
        self.assertNotIn("core/img/clubs/", bronze_html)

    def test_names_positions_and_stat_order(self):
        self.assertEqual(card_name(Player(name="Pele")), "PELE")
        self.assertEqual(card_name(Player(name="N'Golo Kanté")), "N'GOLO KANTÉ")
        self.assertEqual(card_name(Player(name="Mohamed Salah")), "MOHAMED SALAH")
        self.assertEqual(card_name(Player(name="Kylian Mbappé")), "KYLIAN MBAPPÉ")
        self.assertEqual(card_name(Player(name="Achraf Hakimi")), "ACHRAF HAKIMI")

        salah_html = render_player_card(
            Player(name="Mohamed Salah", position="RM", overall=91)
        )
        self.assertIn("MOHAMED SALAH", salah_html)
        self.assertNotIn("GHALY", salah_html)
        mbappe_html = render_player_card(
            Player(name="Kylian Mbappé", position="ST", overall=91)
        )
        self.assertIn("KYLIAN MBAPPÉ", mbappe_html)
        self.assertNotIn("LOTTIN", mbappe_html)
        self.assertEqual(card_name(Player(name="Virgil van Dijk")), "VIRGIL VAN DIJK")
        self.assertNotEqual(card_name(Player(name="Virgil van Dijk")), "DIJK")
        self.assertEqual(card_name(Player(name="Kevin De Bruyne")), "KEVIN DE BRUYNE")
        self.assertNotEqual(card_name(Player(name="Kevin De Bruyne")), "BRUYNE")
        vvd_html = render_player_card(
            Player(name="Virgil van Dijk", position="CB", overall=89)
        )
        self.assertIn("VIRGIL VAN DIJK", vvd_html)
        self.assertNotIn(">DIJK<", vvd_html)

        long_name = (
            "Elijah Anuoluwapo Oluwaferanmi Oluwatomi Oluwalana Ayomikulehin Adebayo"
        )
        self.assertEqual(card_name(Player(name=long_name)), long_name.upper())
        self.assertNotEqual(card_name(Player(name=long_name)), "ADEBAYO")

        long_html = render_player_card(
            Player(
                name=long_name,
                position="ST",
                overall=72,
            )
        )
        self.assertIn(long_name.upper(), long_html)
        self.assertIn("mgl-card-identity", long_html)
        self.assertIn("text-overflow: ellipsis", Path("core/static/core/css/mgl.css").read_text(encoding="utf-8"))

        accent_html = render_player_card(
            Player(name="N'Golo Kanté", position="CDM", overall=86)
        )
        self.assertIn("N&#x27;GOLO KANTÉ", accent_html)
        self.assertIn("mgl-player-card--gold", accent_html)

        for position in (
            "CB",
            "LB",
            "RB",
            "CM",
            "CDM",
            "CAM",
            "LM",
            "RM",
            "LW",
            "RW",
            "ST",
        ):
            html = render_player_card(
                Player(name=f"Pos {position}", position=position, overall=64)
            )
            self.assertIn(f">{position}<", html)
            self.assertIn("mgl-player-card--bronze", html)
            self.assertIn("<span>PAC</span>", html)
            self.assertIn("<span>SHO</span>", html)
            self.assertIn("<span>PAS</span>", html)
            self.assertIn("<span>DRI</span>", html)
            self.assertIn("<span>DEF</span>", html)
            self.assertIn("<span>PHY</span>", html)
            self.assertNotIn("<span>DIV</span>", html)
            self.assertLess(html.find("<span>PAC</span>"), html.find("<span>PHY</span>"))
            self.assertEqual(html.count('class="mgl-card-stat"'), 6)

        gk_html = render_player_card(
            Player(
                name="Robin Risser",
                position="GK",
                overall=71,
                pace=40,
                shooting=20,
                passing=30,
                dribbling=25,
                defending=18,
                physical=50,
                fc_gk_diving=71,
                fc_gk_handling=72,
                fc_gk_kicking=64,
                fc_gk_reflexes=71,
                fc_gk_speed=39,
                fc_gk_positioning=67,
            )
        )
        self.assertIn(">GK<", gk_html)
        self.assertIn("<span>DIV</span><strong>71</strong>", gk_html)
        self.assertIn("<span>HAN</span><strong>72</strong>", gk_html)
        self.assertIn("<span>KIC</span><strong>64</strong>", gk_html)
        self.assertIn("<span>REF</span><strong>71</strong>", gk_html)
        self.assertIn("<span>SPE</span><strong>39</strong>", gk_html)
        self.assertIn("<span>POS</span><strong>67</strong>", gk_html)
        self.assertNotIn("<span>PAC</span>", gk_html)
        self.assertNotIn("<span>SHO</span>", gk_html)
        self.assertNotIn("<span>PAS</span>", gk_html)
        self.assertNotIn("<span>DRI</span>", gk_html)
        self.assertNotIn("<span>DEF</span>", gk_html)
        self.assertNotIn("<span>PHY</span>", gk_html)
        self.assertEqual(gk_html.count('class="mgl-card-stat"'), 6)
