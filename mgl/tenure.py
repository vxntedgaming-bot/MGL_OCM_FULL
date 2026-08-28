from django.db import transaction
from django.utils import timezone

from teams.models import Team

from .market import club_for_user
from .models import ManagerClubSpell


def open_club_spell(manager, team):
    ManagerClubSpell.objects.filter(
        manager=manager,
        ended_at__isnull=True,
    ).update(ended_at=timezone.now(), end_reason=ManagerClubSpell.REASSIGNED)
    return ManagerClubSpell.objects.create(manager=manager, team=team)


def close_club_spell_for_user(user, team, reason=""):
    if not user:
        return 0
    qs = ManagerClubSpell.objects.filter(
        manager__user=user,
        team=team,
        ended_at__isnull=True,
    )
    updates = {"ended_at": timezone.now()}
    if reason:
        updates["end_reason"] = reason
    return qs.update(**updates)


@transaction.atomic
def resign_manager_from_club(manager):
    if manager is None:
        raise ValueError("You must be an approved manager to resign.")
    user = manager.user
    team = club_for_user(user)
    if not team:
        raise ValueError("You do not currently manage a club.")
    team = Team.objects.select_for_update().select_related("league").get(pk=team.pk)
    if team.manager_id != user.id:
        raise ValueError("You can only resign from a club you currently manage.")
    team.manager = None
    team.save(update_fields=["manager"])
    close_club_spell_for_user(user, team, reason=ManagerClubSpell.RESIGNED)
    return team
