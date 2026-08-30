from decimal import Decimal
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

class ApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"

class Fixture(models.Model):
    league = models.ForeignKey("leagues.League", on_delete=models.CASCADE, related_name="mgl_fixtures")
    home_team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="home_fixtures")
    away_team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="away_fixtures")
    matchweek = models.PositiveIntegerField(default=1)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    lineup_deadline = models.DateTimeField(null=True, blank=True)
    release_batch = models.PositiveSmallIntegerField(default=1)
    is_released = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default="SCHEDULED", choices=[("SCHEDULED","Scheduled"),("LIVE","Live"),("COMPLETED","Completed"),("CANCELLED","Cancelled")])
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=["matchweek","scheduled_at","id"]
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.home_team_id and self.away_team_id and self.home_team_id == self.away_team_id:
            raise ValidationError("A club cannot be scheduled against itself.")
    def __str__(self): return f"{self.home_team} vs {self.away_team}"

class MatchSubmission(models.Model):
    fixture = models.OneToOneField(Fixture, on_delete=models.CASCADE, related_name="submission")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="match_submissions")
    status = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_match_submissions")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True)
    opponent_response = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        blank=True,
        default="",
    )
    opponent_responded_at = models.DateTimeField(null=True, blank=True)
    opponent_responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opponent_match_responses",
    )

class TeamMatchStats(models.Model):
    submission = models.ForeignKey(MatchSubmission, on_delete=models.CASCADE, related_name="team_stats")
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="match_stats")
    goals = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(30)])
    shots = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    possession = models.PositiveSmallIntegerField(default=50, validators=[MaxValueValidator(100)])
    yellow_cards = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(11)])
    red_cards = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(11)])
    class Meta:
        constraints=[models.UniqueConstraint(fields=["submission","team"], name="unique_submission_team_stats")]

class GoalEvent(models.Model):
    team_stats=models.ForeignKey(TeamMatchStats,on_delete=models.CASCADE,related_name="goal_events")
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="goal_events")
    minute=models.PositiveSmallIntegerField(null=True,blank=True,validators=[MaxValueValidator(130)])

class AssistEvent(models.Model):
    team_stats=models.ForeignKey(TeamMatchStats,on_delete=models.CASCADE,related_name="assist_events")
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="assist_events")
    minute=models.PositiveSmallIntegerField(null=True,blank=True,validators=[MaxValueValidator(130)])

class DefenderRating(models.Model):
    team_stats=models.ForeignKey(TeamMatchStats,on_delete=models.CASCADE,related_name="defender_ratings")
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="defender_ratings")
    rating=models.DecimalField(max_digits=3,decimal_places=1,validators=[MinValueValidator(Decimal("0.0")),MaxValueValidator(Decimal("10.0"))])
    class Meta:
        constraints=[models.UniqueConstraint(fields=["team_stats","player"],name="unique_defender_rating")]

class GKSave(models.Model):
    team_stats=models.ForeignKey(TeamMatchStats,on_delete=models.CASCADE,related_name="gk_saves")
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="gk_saves")
    saves=models.PositiveSmallIntegerField(validators=[MinValueValidator(0),MaxValueValidator(20)])
    class Meta:
        constraints=[models.UniqueConstraint(fields=["team_stats","player"],name="unique_gk_save")]

class PressConference(models.Model):
    MATCH = "MATCH"
    SIGNING = "SIGNING"
    APPOINTMENT = "APPOINTMENT"
    ODD_MATCHDAY = "ODD_MATCHDAY"
    TRIGGER_CHOICES = [
        (MATCH, "Match"),
        (SIGNING, "Signing"),
        (APPOINTMENT, "Appointment"),
        (ODD_MATCHDAY, "Odd matchday"),
    ]

    fixture=models.ForeignKey(Fixture,on_delete=models.CASCADE,related_name="press_conferences",null=True,blank=True)
    team=models.ForeignKey("teams.Team",on_delete=models.SET_NULL,null=True,blank=True,related_name="press_conferences")
    manager=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="press_conferences")
    trigger=models.CharField(max_length=20,choices=TRIGGER_CHOICES,default=MATCH)
    category=models.CharField(max_length=40,default="performance")
    question_key=models.CharField(max_length=80,blank=True)
    question=models.TextField()
    answer=models.TextField(blank=True)
    status=models.CharField(max_length=20,choices=ApprovalStatus.choices,default=ApprovalStatus.PENDING)
    reward=models.DecimalField(max_digits=6,decimal_places=2,default=Decimal("0.20"))
    matchweek=models.PositiveIntegerField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    approved_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=["fixture","manager"],
                condition=models.Q(fixture__isnull=False),
                name="unique_fixture_manager_press",
            ),
            models.UniqueConstraint(
                fields=["manager","question_key"],
                condition=models.Q(status="PENDING") & ~models.Q(question_key=""),
                name="unique_pending_press_question",
            ),
        ]

class RewardTransaction(models.Model):
    manager=models.ForeignKey("managers.ManagerApplication",on_delete=models.CASCADE,related_name="rewards")
    amount=models.DecimalField(max_digits=8,decimal_places=2)
    reason=models.CharField(max_length=255)
    category=models.CharField(max_length=40,default="OTHER")
    fixture=models.ForeignKey(Fixture,on_delete=models.SET_NULL,null=True,blank=True,related_name="rewards")
    created_at=models.DateTimeField(auto_now_add=True)

class TeamOfTheWeek(models.Model):
    week_start=models.DateField()
    formation=models.CharField(max_length=20,default="4-2-3-1")
    approved=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["week_start"],name="unique_totw_week")]

class TOTWSelection(models.Model):
    totw=models.ForeignKey(TeamOfTheWeek,on_delete=models.CASCADE,related_name="selections")
    slot=models.CharField(max_length=10)
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="totw_selections")
    manager_reward=models.DecimalField(max_digits=6,decimal_places=2,default=Decimal("0.20"))
    class Meta:
        constraints=[models.UniqueConstraint(fields=["totw","slot"],name="unique_totw_slot"),models.UniqueConstraint(fields=["totw","player"],name="unique_totw_player")]

class ManagerWeek(models.Model):
    week_start=models.DateField()
    manager=models.ForeignKey("managers.ManagerApplication",on_delete=models.CASCADE,related_name="manager_weeks")
    wins=models.PositiveSmallIntegerField(default=0)
    reward=models.DecimalField(max_digits=6,decimal_places=2,default=Decimal("0.50"))
    approved=models.BooleanField(default=False)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["week_start","manager"],name="unique_manager_week")]

class NewsPost(models.Model):
    RESULTS="RESULTS"; TRANSFER="TRANSFER"; AUCTION="AUCTION"; FREE_AGENT="FREE_AGENT"; REWARD="REWARD"; PRESS="PRESS"
    MANAGER="MANAGER"; SIGNING="SIGNING"; SCOUTING="SCOUTING"
    CATEGORY_CHOICES=[(x,x.replace("_"," ").title()) for x in [RESULTS,TRANSFER,AUCTION,FREE_AGENT,REWARD,PRESS,MANAGER,SIGNING,SCOUTING]]
    category=models.CharField(max_length=30,choices=CATEGORY_CHOICES)
    title=models.CharField(max_length=200)
    body=models.TextField()
    published=models.BooleanField(default=False)
    discord_sent=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    primary_team=models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="news_as_primary",
    )
    secondary_team=models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="news_as_secondary",
    )

class Pack(models.Model):
    GOLD="GOLD"; SILVER="SILVER"; BRONZE="BRONZE"; ELITE="ELITE"; YOUTH="YOUTH"
    TYPE_CHOICES=[(x,x.title()) for x in [GOLD,SILVER,BRONZE,ELITE,YOUTH]]
    name=models.CharField(max_length=40)
    pack_type=models.CharField(max_length=10,choices=TYPE_CHOICES,unique=True)
    cost=models.DecimalField(max_digits=8,decimal_places=2,default=0)
    active=models.BooleanField(default=True)
    def __str__(self): return self.name

class PackOpening(models.Model):
    manager=models.ForeignKey("managers.ManagerApplication",on_delete=models.CASCADE,related_name="pack_openings")
    pack=models.ForeignKey(Pack,on_delete=models.PROTECT,related_name="openings")
    created_at=models.DateTimeField(auto_now_add=True)

class PackReward(models.Model):
    opening=models.ForeignKey(PackOpening,on_delete=models.CASCADE,related_name="rewards")
    player=models.ForeignKey("players.Player",on_delete=models.PROTECT,related_name="pack_rewards")
    assigned_team=models.ForeignKey("teams.Team",on_delete=models.SET_NULL,null=True,blank=True,related_name="pack_rewards")

class ApprovalRequest(models.Model):
    kind=models.CharField(max_length=50)
    object_id=models.PositiveBigIntegerField()
    submitted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,related_name="approval_requests")
    status=models.CharField(max_length=20,choices=ApprovalStatus.choices,default=ApprovalStatus.PENDING)
    payload=models.JSONField(default=dict,blank=True)
    notes=models.TextField(blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    reviewed_at=models.DateTimeField(null=True,blank=True)
    reviewed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="approval_requests_reviewed")


class PlayerOwnershipHistory(models.Model):
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="ownership_history")
    team=models.ForeignKey("teams.Team",on_delete=models.SET_NULL,null=True,blank=True,related_name="ownership_history")
    manager=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="player_ownership_history")
    source=models.CharField(max_length=30)
    reference=models.CharField(max_length=100,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

class ManagerCareerStat(models.Model):
    manager=models.OneToOneField("managers.ManagerApplication",on_delete=models.CASCADE,related_name="career")
    wins=models.PositiveIntegerField(default=0)
    draws=models.PositiveIntegerField(default=0)
    losses=models.PositiveIntegerField(default=0)
    trophies=models.PositiveIntegerField(default=0)
    league_titles=models.PositiveIntegerField(default=0)
    cup_titles=models.PositiveIntegerField(default=0)
    golden_boots=models.PositiveIntegerField(default=0)
    manager_of_week=models.PositiveIntegerField(default=0)

class Trophy(models.Model):
    manager=models.ForeignKey("managers.ManagerApplication",on_delete=models.CASCADE,related_name="trophies")
    name=models.CharField(max_length=100)
    season=models.CharField(max_length=50,blank=True)
    awarded_at=models.DateTimeField(auto_now_add=True)

class AuctionRequest(models.Model):
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="auction_requests")
    manager=models.ForeignKey("managers.ManagerApplication",on_delete=models.CASCADE,related_name="auction_requests")
    status=models.CharField(max_length=20,choices=ApprovalStatus.choices,default=ApprovalStatus.PENDING)
    submitted_at=models.DateTimeField(auto_now_add=True)
    reviewed_at=models.DateTimeField(null=True,blank=True)
    reviewed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="auction_requests_reviewed")


class PlayerListing(models.Model):
    PENDING = "PENDING"
    LIVE = "LIVE"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    OFFER = "OFFER"

    STATUS_CHOICES = [
        (PENDING, "Pending approval"),
        (LIVE, "Live"),
        (SOLD, "Sold"),
        (CANCELLED, "Cancelled"),
        (REJECTED, "Rejected"),
        (OFFER, "Waiting for selling manager"),
    ]

    player = models.ForeignKey("players.Player", on_delete=models.CASCADE, related_name="listings")
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="player_listings")
    seller = models.ForeignKey("managers.ManagerApplication", on_delete=models.CASCADE, related_name="player_listings")
    asking_price = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="listings_reviewed")
    sold_to = models.ForeignKey("managers.ManagerApplication", on_delete=models.SET_NULL, null=True, blank=True, related_name="players_bought")
    sold_at = models.DateTimeField(null=True, blank=True)
    reserved_buyer = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfer_offers",
    )
    offered_player = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="listings_as_swap_offer",
    )
    offered_players = models.ManyToManyField(
        "players.Player",
        blank=True,
        related_name="listings_offered_in",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.player.name} listed for {self.asking_price}"


class MarketTransaction(models.Model):
    AUCTION = "AUCTION"
    SALE = "SALE"
    BID_RESERVE = "BID_RESERVE"
    BID_REFUND = "BID_REFUND"
    ADMIN_ASSIGN = "ADMIN_ASSIGN"

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

    TYPE_CHOICES = [
        (AUCTION, "Auction"),
        (SALE, "Sale"),
        (BID_RESERVE, "Bid reserve"),
        (BID_REFUND, "Bid refund"),
        (ADMIN_ASSIGN, "Admin assignment"),
    ]
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (COMPLETED, "Completed"),
        (REJECTED, "Rejected"),
        (CANCELLED, "Cancelled"),
    ]

    player = models.ForeignKey("players.Player", on_delete=models.SET_NULL, null=True, blank=True, related_name="market_transactions")
    seller = models.ForeignKey("managers.ManagerApplication", on_delete=models.SET_NULL, null=True, blank=True, related_name="sales")
    buyer = models.ForeignKey("managers.ManagerApplication", on_delete=models.SET_NULL, null=True, blank=True, related_name="purchases")
    from_team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="tokens_spent_transfers")
    to_team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="tokens_received_transfers")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=COMPLETED)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="market_transactions_approved")
    auction = models.ForeignKey("auctions.PlayerAuction", on_delete=models.SET_NULL, null=True, blank=True, related_name="market_transactions")
    listing = models.ForeignKey("mgl.PlayerListing", on_delete=models.SET_NULL, null=True, blank=True, related_name="market_transactions")
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class ClubApplication(models.Model):
    manager = models.ForeignKey("managers.ManagerApplication", on_delete=models.CASCADE, related_name="club_applications")
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="club_applications")
    message = models.TextField(blank=True)
    gamertag = models.CharField(max_length=64, blank=True)
    discord_username = models.CharField(max_length=64, blank=True)
    games_per_week = models.CharField(max_length=8, blank=True)
    referred_by = models.CharField(max_length=64, blank=True)
    new_gen_confirmed = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="club_applications_reviewed")

    class Meta:
        ordering = ["-created_at"]

class FixtureReleaseBatch(models.Model):
    name=models.CharField(max_length=100)
    batch_number=models.PositiveSmallIntegerField()
    released_at=models.DateTimeField(null=True,blank=True)
    deadline=models.DateTimeField(null=True,blank=True)
    is_released=models.BooleanField(default=False)
    class Meta:
        ordering=["batch_number"]


class ManagerClubSpell(models.Model):
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"
    REASSIGNED = "REASSIGNED"
    END_REASON_CHOICES = [
        (RESIGNED, "Resigned"),
        (REMOVED, "Removed"),
        (REASSIGNED, "Reassigned"),
    ]

    manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.CASCADE,
        related_name="club_spells",
    )
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="manager_spells")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, blank=True, choices=END_REASON_CHOICES)

    class Meta:
        ordering = ["-started_at"]


class ScoutProfile(models.Model):
    manager = models.OneToOneField(
        "managers.ManagerApplication",
        on_delete=models.CASCADE,
        related_name="scout_profile",
    )
    scout_level = models.PositiveSmallIntegerField(default=1)


class ScoutAssignment(models.Model):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    TIER_CHOICES = [
        (BRONZE, "Bronze"),
        (SILVER, "Silver"),
        (GOLD, "Gold"),
    ]
    PENDING = "PENDING"
    READY = "READY"
    COMPLETE = "COMPLETE"

    manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.CASCADE,
        related_name="scout_assignments",
    )
    tier = models.CharField(max_length=10, choices=TIER_CHOICES)
    level = models.PositiveSmallIntegerField(default=1)
    region = models.CharField(max_length=100, blank=True)
    position = models.CharField(max_length=10, blank=True)
    player = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scout_assignments",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, default=PENDING)

    class Meta:
        ordering = ["-started_at"]


class ScoutReport(models.Model):
    manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.CASCADE,
        related_name="scout_reports",
    )
    player = models.ForeignKey(
        "players.Player",
        on_delete=models.CASCADE,
        related_name="scout_reports",
    )
    assignment = models.ForeignKey(
        ScoutAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    tier = models.CharField(max_length=10)
    level = models.PositiveSmallIntegerField(default=0)
    region = models.CharField(max_length=100, blank=True)
    position = models.CharField(max_length=10, blank=True)
    recruited = models.BooleanField(default=False)
    club = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scout_recruits",
    )
    discovered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-discovered_at"]


class SiteContent(models.Model):
    """Reusable website copy and site settings. One row per unique key."""

    section = models.CharField(max_length=40)
    key = models.CharField(max_length=80, unique=True)
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_content_edits",
    )

    class Meta:
        ordering = ["section", "key"]

    def __str__(self):
        return self.key


class SiteChangeLog(models.Model):
    """Audit trail for Site Management edits. Separate from ApprovalRequest."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_change_logs",
    )
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=40, blank=True)
    object_label = models.CharField(max_length=200, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    summary = models.CharField(max_length=400)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.summary


class ManagerNotification(models.Model):
    """Per-manager inbox row. Ownership is always the recipient user."""

    NONE = ""
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RESPONSE_CHOICES = [
        (NONE, "None"),
        (PENDING, "Pending"),
        (ACCEPTED, "Accepted"),
        (REJECTED, "Rejected"),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="manager_notifications",
    )
    source_key = models.CharField(max_length=120)
    notification_type = models.CharField(max_length=40)
    title = models.CharField(max_length=160)
    message = models.TextField()
    actor = models.CharField(max_length=160, blank=True)
    action_url = models.CharField(max_length=400, blank=True)
    action_label = models.CharField(max_length=40, blank=True)
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_notifications",
    )
    player = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_notifications",
    )
    fixture = models.ForeignKey(
        "mgl.Fixture",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_notifications",
    )
    listing = models.ForeignKey(
        "mgl.PlayerListing",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_notifications",
    )
    details = models.JSONField(default=dict, blank=True)
    response_status = models.CharField(
        max_length=20,
        choices=RESPONSE_CHOICES,
        default=NONE,
        blank=True,
    )
    actioned_at = models.DateTimeField(null=True, blank=True)
    is_action = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "source_key"],
                name="unique_manager_notification_key",
            )
        ]
        indexes = [
            models.Index(
                fields=["recipient", "read_at"],
                name="mgl_manager_recipie_419c8c_idx",
            ),
            models.Index(
                fields=["recipient", "created_at"],
                name="mgl_manager_recipie_d6cbf7_idx",
            ),
        ]

    def __str__(self):
        return f"{self.recipient_id}:{self.source_key}"

    @property
    def is_unread(self):
        return self.read_at is None

    @property
    def is_pending_response(self):
        return self.response_status == self.PENDING

    @property
    def is_actioned(self):
        return self.response_status in {self.ACCEPTED, self.REJECTED}
