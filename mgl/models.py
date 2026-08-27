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
    def __str__(self): return f"{self.home_team} vs {self.away_team}"

class MatchSubmission(models.Model):
    fixture = models.OneToOneField(Fixture, on_delete=models.CASCADE, related_name="submission")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="match_submissions")
    status = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_match_submissions")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True)

class TeamMatchStats(models.Model):
    submission = models.ForeignKey(MatchSubmission, on_delete=models.CASCADE, related_name="team_stats")
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="match_stats")
    goals = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(30)])
    shots = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    possession = models.PositiveSmallIntegerField(default=50, validators=[MaxValueValidator(100)])
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
    saves=models.PositiveSmallIntegerField(validators=[MinValueValidator(1),MaxValueValidator(20)])
    class Meta:
        constraints=[models.UniqueConstraint(fields=["team_stats","player"],name="unique_gk_save")]

class PressConference(models.Model):
    fixture=models.ForeignKey(Fixture,on_delete=models.CASCADE,related_name="press_conferences")
    manager=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="press_conferences")
    question=models.TextField()
    answer=models.TextField(blank=True)
    status=models.CharField(max_length=20,choices=ApprovalStatus.choices,default=ApprovalStatus.PENDING)
    reward=models.DecimalField(max_digits=6,decimal_places=2,default=Decimal("0.20"))
    created_at=models.DateTimeField(auto_now_add=True)
    approved_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["fixture","manager"],name="unique_fixture_manager_press")]

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
    CATEGORY_CHOICES=[(x,x.replace("_"," ").title()) for x in [RESULTS,TRANSFER,AUCTION,FREE_AGENT,REWARD,PRESS]]
    category=models.CharField(max_length=30,choices=CATEGORY_CHOICES)
    title=models.CharField(max_length=200)
    body=models.TextField()
    published=models.BooleanField(default=False)
    discord_sent=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)

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

class FixtureReleaseBatch(models.Model):
    name=models.CharField(max_length=100)
    batch_number=models.PositiveSmallIntegerField()
    released_at=models.DateTimeField(null=True,blank=True)
    deadline=models.DateTimeField(null=True,blank=True)
    is_released=models.BooleanField(default=False)
    class Meta:
        ordering=["batch_number"]
