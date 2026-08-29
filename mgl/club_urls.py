"""Public club page slugs. Reuses Team; no extra model."""

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.text import slugify

from teams.models import Team


def club_slug(team):
    if team is None:
        return ""
    return slugify(team.name) or (team.short_name or "").lower()


def club_page_url(team):
    slug = club_slug(team)
    if not slug:
        return "#"
    return reverse("club_page", kwargs={"slug": slug})


def resolve_club(slug):
    slug = (slug or "").strip()
    if not slug:
        raise Http404("No club matches the given query.")
    qs = Team.objects.select_related("league", "manager")
    team = qs.filter(short_name__iexact=slug).first()
    if team:
        return team
    needle = slug.lower()
    for candidate in qs:
        if club_slug(candidate) == needle:
            return candidate
    return get_object_or_404(qs, short_name__iexact=slug)
