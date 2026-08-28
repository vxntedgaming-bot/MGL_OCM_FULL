"""Accent-insensitive player search helpers."""

from django.db.models import Q

from players.fc26_names import name_matches_query
from players.models import Player


def matching_player_ids(query: str) -> list[int]:
    """Return primary keys whose display name contains query, ignoring accents."""
    query = (query or "").strip()
    if not query:
        return []
    return [
        pk
        for pk, name in Player.objects.values_list("id", "name")
        if name_matches_query(name, query)
    ]


def apply_player_search(queryset, search: str, extra_fields=None):
    """Filter a Player queryset by recognised name plus optional related fields."""
    search = (search or "").strip()
    if not search:
        return queryset
    query = Q(pk__in=matching_player_ids(search))
    for field in extra_fields or ():
        query |= Q(**{f"{field}__icontains": search})
    return queryset.filter(query)
