from django.utils import timezone

from .models import ManagerClubSpell


def open_club_spell(manager, team):
    ManagerClubSpell.objects.filter(
        manager=manager,
        ended_at__isnull=True,
    ).update(ended_at=timezone.now())
    return ManagerClubSpell.objects.create(manager=manager, team=team)


def close_club_spell_for_user(user, team):
    if not user:
        return
    ManagerClubSpell.objects.filter(
        manager__user=user,
        team=team,
        ended_at__isnull=True,
    ).update(ended_at=timezone.now())
