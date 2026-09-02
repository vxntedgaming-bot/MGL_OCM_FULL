import random
from django.db import transaction
from players.models import Player
from .models import PackOpening,PackReward
from .market import assert_roster_space
from .services import player_tier,assign_player

@transaction.atomic
def open_pack(manager,pack,team):
    if manager.tokens < pack.cost: raise ValueError("Not enough UFL Coins")
    needed = 7 if pack.pack_type == "ELITE" else 1
    assert_roster_space(team, extra=needed)
    owned=set(Player.objects.filter(mgl_team=team).values_list("id",flat=True))
    def pick(tier, exclude):
        qs=[p for p in Player.objects.filter(is_free_agent=False, mgl_team__isnull=True).order_by("id") if player_tier(p.overall)==tier and p.id not in exclude]
        if not qs: raise ValueError(f"No unreleased {tier.lower()} players remain")
        return random.choice(qs)
    manager.tokens -= pack.cost; manager.save(update_fields=["tokens"])
    opening=PackOpening.objects.create(manager=manager,pack=pack)
    picks=[]
    if pack.pack_type in ["GOLD","SILVER","BRONZE"]: picks=[pick(pack.pack_type,owned)]
    elif pack.pack_type=="YOUTH":
        qs=[p for p in Player.objects.filter(is_free_agent=False, mgl_team__isnull=True) if p.age and p.age<20 and player_tier(p.overall)=="GOLD" and p.id not in owned]
        if not qs: raise ValueError("No eligible youth academy player remains")
        picks=[random.choice(qs)]
    elif pack.pack_type=="ELITE":
        for tier in ["GOLD","GOLD","SILVER","SILVER","SILVER","BRONZE","BRONZE"]: picks.append(pick(tier,owned|{x.id for x in picks}))
    for p in picks:
        assign_player(p,team,source="PACK",reference=str(opening.id)); PackReward.objects.create(opening=opening,player=p,assigned_team=team)
    return opening
