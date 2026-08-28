from django.core.management.base import BaseCommand
from django.db import transaction
from players.models import Player
from teams.models import Team
from leagues.models import League
from managers.models import ManagerApplication
from auctions.models import PlayerAuction, AuctionBid, TokenTransaction
from mgl.models import *

class Command(BaseCommand):
    help="Reset MGL competition data while keeping the FC player database and user accounts."
    @transaction.atomic
    def handle(self,*args,**opts):
        for model in [GoalEvent,AssistEvent,DefenderRating,GKSave,TeamMatchStats,MatchSubmission,PressConference,RewardTransaction,TOTWSelection,TeamOfTheWeek,ManagerWeek,Fixture,NewsPost,PackReward,PackOpening,Pack,ApprovalRequest]: model.objects.all().delete()
        AuctionBid.objects.all().delete(); PlayerAuction.objects.all().delete(); TokenTransaction.objects.all().delete()
        Player.objects.update(mgl_team=None,is_free_agent=False,appearances=0,goals=0,assists=0,average_rating=0,released_at=None)
        Team.objects.update(manager=None,budget=0)
        ManagerApplication.objects.update(tokens=50)
        Team.objects.all().delete(); League.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("MGL reset complete. FC players remain UNASSIGNED. Create leagues/teams through Admin."))
