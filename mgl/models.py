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
    season_number = models.PositiveIntegerField(default=1, db_index=True)
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
    stats_applied = models.BooleanField(default=False)

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
    tackles=models.PositiveSmallIntegerField(default=0,validators=[MaxValueValidator(50)])
    class Meta:
        constraints=[models.UniqueConstraint(fields=["team_stats","player"],name="unique_defender_rating")]

class GKSave(models.Model):
    team_stats=models.ForeignKey(TeamMatchStats,on_delete=models.CASCADE,related_name="gk_saves")
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="gk_saves")
    saves=models.PositiveSmallIntegerField(validators=[MinValueValidator(0),MaxValueValidator(20)])
    rating=models.DecimalField(max_digits=3,decimal_places=1,null=True,blank=True,validators=[MinValueValidator(Decimal("0.0")),MaxValueValidator(Decimal("10.0"))])
    class Meta:
        constraints=[models.UniqueConstraint(fields=["team_stats","player"],name="unique_gk_save")]

class PlayerMatchRating(models.Model):
    """Outfield (non-defender) match rating. One row per player per team sheet."""

    team_stats=models.ForeignKey(TeamMatchStats,on_delete=models.CASCADE,related_name="player_ratings")
    player=models.ForeignKey("players.Player",on_delete=models.CASCADE,related_name="match_ratings")
    rating=models.DecimalField(max_digits=3,decimal_places=1,validators=[MinValueValidator(Decimal("1.0")),MaxValueValidator(Decimal("10.0"))])
    class Meta:
        constraints=[models.UniqueConstraint(fields=["team_stats","player"],name="unique_player_match_rating")]

class PressConference(models.Model):
    MATCH = "MATCH"
    SIGNING = "SIGNING"
    APPOINTMENT = "APPOINTMENT"
    ODD_MATCHDAY = "ODD_MATCHDAY"
    DAILY = "DAILY"
    RELEASE = "RELEASE"
    TRIGGER_CHOICES = [
        (MATCH, "Match"),
        (SIGNING, "Signing"),
        (APPOINTMENT, "Appointment"),
        (ODD_MATCHDAY, "Odd matchday"),
        (DAILY, "Daily"),
        (RELEASE, "Release"),
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
    season_number=models.PositiveIntegerField(default=1,db_index=True)
    available_at=models.DateTimeField(null=True,blank=True,db_index=True)
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
    reference=models.CharField(max_length=120,blank=True,default="",db_index=True)
    balance_before=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    balance_after=models.DecimalField(max_digits=8,decimal_places=2,null=True,blank=True)
    created_by=models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="token_adjustments",
    )
    reverses=models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversed_by_rows",
    )
    reversed_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manager", "category", "reference"],
                condition=~models.Q(reference="") & models.Q(reversed_at__isnull=True),
                name="unique_reward_reference",
            )
        ]

class WeeklyAwardBatch(models.Model):
    EMPTY = "EMPTY"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STATUS_CHOICES = [
        (EMPTY, "No activity"),
        (PENDING_REVIEW, "Awaiting admin review"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
    ]

    week_start = models.DateField(unique=True)
    notes = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, blank=True, default="")
    has_ties = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weekly_award_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Weekly awards {self.week_start}"

    @property
    def needs_review(self):
        return self.status == self.PENDING_REVIEW and not self.completed


class MonthlyAwardBatch(models.Model):
    EMPTY = "EMPTY"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STATUS_CHOICES = [
        (EMPTY, "No activity"),
        (PENDING_REVIEW, "Awaiting admin review"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
    ]

    month_start = models.DateField(unique=True)
    notes = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, blank=True, default="")
    has_ties = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="monthly_award_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Monthly awards {self.month_start}"

    @property
    def needs_review(self):
        return self.status == self.PENDING_REVIEW and not self.completed


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
    details=models.JSONField(default=dict, blank=True)

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
    judging_ability = models.PositiveSmallIntegerField(default=2)
    judging_potential = models.PositiveSmallIntegerField(default=2)
    position_knowledge = models.PositiveSmallIntegerField(default=3)
    discovery_rate = models.PositiveSmallIntegerField(default=2)
    report_accuracy = models.PositiveSmallIntegerField(default=2)
    scouting_speed = models.PositiveSmallIntegerField(default=2)


class ScoutAssignment(models.Model):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    ELITE = "ELITE"
    TIER_CHOICES = [
        (BRONZE, "Bronze"),
        (SILVER, "Silver"),
        (GOLD, "Gold"),
        (ELITE, "Elite"),
    ]
    PENDING = "PENDING"
    READY = "READY"
    OPENED = "OPENED"
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
    club = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scout_assignments",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, default=PENDING)
    duration_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    token_cost = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    reveal_stage = models.CharField(max_length=12, default="HIDDEN")
    estimated_ovr_low = models.PositiveSmallIntegerField(null=True, blank=True)
    estimated_ovr_high = models.PositiveSmallIntegerField(null=True, blank=True)
    estimated_potential_low = models.PositiveSmallIntegerField(null=True, blank=True)
    estimated_potential_high = models.PositiveSmallIntegerField(null=True, blank=True)
    confidence = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["player"],
                condition=models.Q(status__in=["PENDING", "READY", "OPENED"])
                & models.Q(player__isnull=False),
                name="unique_active_scout_player",
            ),
            models.UniqueConstraint(
                fields=["manager"],
                condition=models.Q(status__in=["PENDING", "READY", "OPENED"]),
                name="unique_active_scout_per_manager",
            ),
        ]


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
    confidence = models.PositiveSmallIntegerField(null=True, blank=True)
    recommendation = models.CharField(max_length=40, blank=True)
    estimated_potential_low = models.PositiveSmallIntegerField(null=True, blank=True)
    estimated_potential_high = models.PositiveSmallIntegerField(null=True, blank=True)

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


class HistoricalSeason(models.Model):
    """One MGL season. Finalised rows are frozen snapshots and must not follow live data."""

    ACTIVE = "ACTIVE"
    FINALIZED = "FINALIZED"
    STATUS_CHOICES = [
        (ACTIVE, "Active"),
        (FINALIZED, "Finalized"),
    ]

    number = models.PositiveIntegerField(unique=True)
    year_label = models.CharField(max_length=32, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    clubs_count = models.PositiveIntegerField(default=0)
    games_played = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    is_locked = models.BooleanField(default=False)
    league = models.ForeignKey(
        "leagues.League",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historical_seasons",
    )
    league_winner = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_league_titles",
    )
    league_winner_name = models.CharField(max_length=120, blank=True)
    cup_winner = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_cup_titles",
    )
    cup_winner_name = models.CharField(max_length=120, blank=True)
    manager_of_season = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_manager_awards",
    )
    manager_of_season_name = models.CharField(max_length=120, blank=True)
    manager_of_season_club = models.CharField(max_length=120, blank=True)
    ballon_dor = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_ballon_dor",
    )
    ballon_dor_name = models.CharField(max_length=120, blank=True)
    top_scorer = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_golden_boots",
    )
    top_scorer_name = models.CharField(max_length=120, blank=True)
    top_scorer_goals = models.PositiveIntegerField(null=True, blank=True)
    top_assists_player = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_assist_awards",
    )
    top_assists_name = models.CharField(max_length=120, blank=True)
    top_assists_count = models.PositiveIntegerField(null=True, blank=True)
    young_player = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_young_player_awards",
    )
    young_player_name = models.CharField(max_length=120, blank=True)
    top_goalkeeper = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_gk_awards",
    )
    top_goalkeeper_name = models.CharField(max_length=120, blank=True)
    fair_play_team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_fair_play_awards",
    )
    fair_play_name = models.CharField(max_length=120, blank=True)
    biggest_win_home = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_biggest_win_home",
    )
    biggest_win_away = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_biggest_win_away",
    )
    biggest_win_home_name = models.CharField(max_length=120, blank=True)
    biggest_win_away_name = models.CharField(max_length=120, blank=True)
    biggest_win_home_goals = models.PositiveSmallIntegerField(null=True, blank=True)
    biggest_win_away_goals = models.PositiveSmallIntegerField(null=True, blank=True)
    unbeaten_team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_unbeaten_runs",
    )
    unbeaten_team_name = models.CharField(max_length=120, blank=True)
    unbeaten_games = models.PositiveIntegerField(null=True, blank=True)
    tots_formation = models.CharField(max_length=20, default="4-2-3-1")
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finalized_seasons",
    )

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"Season {self.number}"

    @property
    def is_active(self):
        return self.status == self.ACTIVE

    @property
    def is_finalized(self):
        return self.status == self.FINALIZED


class SeasonTableRow(models.Model):
    season = models.ForeignKey(
        HistoricalSeason,
        on_delete=models.CASCADE,
        related_name="table_rows",
    )
    position = models.PositiveSmallIntegerField()
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historical_table_rows",
    )
    team_name = models.CharField(max_length=120)
    played = models.PositiveSmallIntegerField(default=0)
    wins = models.PositiveSmallIntegerField(default=0)
    draws = models.PositiveSmallIntegerField(default=0)
    losses = models.PositiveSmallIntegerField(default=0)
    gf = models.PositiveSmallIntegerField(default=0)
    ga = models.PositiveSmallIntegerField(default=0)
    gd = models.SmallIntegerField(default=0)
    points = models.SmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["season", "position"], name="unique_season_table_position"),
        ]


class SeasonTotsPick(models.Model):
    season = models.ForeignKey(
        HistoricalSeason,
        on_delete=models.CASCADE,
        related_name="tots_picks",
    )
    slot = models.CharField(max_length=12)
    sort_order = models.PositiveSmallIntegerField(default=0)
    player = models.ForeignKey(
        "players.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="season_tots_picks",
    )
    player_name = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["season", "slot"], name="unique_season_tots_slot"),
        ]


class LeagueSettings(models.Model):
    """Singleton Owner/Admin UFL rules. Never hard-code these in frontend JS."""

    starting_tokens = models.DecimalField(max_digits=8, decimal_places=2, default=20)
    max_squad_size = models.PositiveSmallIntegerField(default=28)
    starting_squad_size = models.PositiveSmallIntegerField(default=25)
    max_active_listings = models.PositiveSmallIntegerField(default=5)
    listings_per_24h = models.PositiveSmallIntegerField(default=3)
    allow_manager_auctions = models.BooleanField(default=False)
    scout_can_recruit = models.BooleanField(
        default=False,
        help_text="Legacy scout-to-squad claim. Managers cannot use this. Owner/Admin only.",
    )
    scout_requires_tokens = models.BooleanField(default=False)
    max_scouts_per_club = models.PositiveSmallIntegerField(default=1)
    auction_durations = models.CharField(
        max_length=80,
        default="30,60,90,120",
    )
    scout_durations = models.CharField(
        max_length=80,
        default="1,3,6,12,24,48,72",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="league_settings_edits",
    )

    class Meta:
        verbose_name = "League settings"

    def __str__(self):
        return "UFL league settings"


class DiscordEvent(models.Model):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (SENT, "Sent"),
        (FAILED, "Failed"),
    ]

    event_type = models.CharField(max_length=40, db_index=True)
    channel_key = models.CharField(max_length=40, default="NEWS")
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    news_post = models.ForeignKey(
        NewsPost,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discord_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="mgl_disco_status_created_idx"),
        ]

    def __str__(self):
        return f"{self.event_type} {self.status}"


class PlayerReleaseRequest(models.Model):
    player = models.ForeignKey(
        "players.Player",
        on_delete=models.CASCADE,
        related_name="release_requests",
    )
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="release_requests")
    manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.CASCADE,
        related_name="release_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
        db_index=True,
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="player_releases_reviewed",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["player"],
                condition=models.Q(status="PENDING"),
                name="unique_pending_player_release",
            ),
        ]


class ScoutWatchlist(models.Model):
    manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.CASCADE,
        related_name="scout_watchlist",
    )
    player = models.ForeignKey(
        "players.Player",
        on_delete=models.CASCADE,
        related_name="watchlisted_by",
    )
    report = models.ForeignKey(
        ScoutReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="watchlist_rows",
    )
    notes = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["manager", "player"],
                name="unique_scout_watchlist_player",
            )
        ]


class StartingSquadProposal(models.Model):
    """Owner preview of a UFL starting allocation. Generation never writes ownership."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
        (SUPERSEDED, "Superseded"),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="starting_squad_proposals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    seed = models.BigIntegerField()
    include_free_agents = models.BooleanField(default=False)
    club_count = models.PositiveIntegerField(default=0)
    players_required = models.PositiveIntegerField(default=0)
    players_available = models.PositiveIntegerField(default=0)
    rating_min = models.PositiveSmallIntegerField(default=64)
    rating_max = models.PositiveSmallIntegerField(default=69)
    squad_size = models.PositiveSmallIntegerField(default=25)
    average_league_ovr = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    largest_avg_diff = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    max_allowed_avg_diff = models.DecimalField(max_digits=6, decimal_places=3, default=1.500)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=DRAFT)
    payload = models.JSONField(default=dict, blank=True)
    validation = models.JSONField(default=dict, blank=True)
    notes = models.JSONField(default=list, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="starting_squad_approvals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="starting_squad_rejections",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Starting proposal {self.pk} ({self.status})"


class StartingSquadLock(models.Model):
    """Records that official starting squads were applied for a season."""

    season = models.PositiveIntegerField(unique=True)
    proposal = models.OneToOneField(
        StartingSquadProposal,
        on_delete=models.PROTECT,
        related_name="season_lock",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="starting_squad_locks",
    )
    approved_at = models.DateTimeField()
    club_count = models.PositiveIntegerField(default=0)
    players_assigned = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-season"]

    def __str__(self):
        return f"Starting lock season {self.season}"
