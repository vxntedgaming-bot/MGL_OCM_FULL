"""Owner/Admin Site Management views. Display-only edits; no player or fixture writes."""

from io import BytesIO

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from leagues.models import League
from mgl.models import SiteChangeLog
from mgl.permissions import site_manage_required
from mgl.site_cms import (
    actor_label,
    get_content,
    log_site_change,
    public_sections,
    save_content_fields,
    settings_fields,
)
from teams.models import Team

ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
ALLOWED_LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_LOGO_BYTES = 2 * 1024 * 1024


def _validate_logo_upload(uploaded):
    if not uploaded:
        return None
    name = (getattr(uploaded, "name", "") or "").lower()
    content_type = (getattr(uploaded, "content_type", "") or "").lower()
    suffix_ok = any(name.endswith(suffix) for suffix in ALLOWED_LOGO_SUFFIXES)
    type_ok = content_type in ALLOWED_LOGO_TYPES or (not content_type and suffix_ok)
    if not suffix_ok or not type_ok:
        raise ValidationError("Logo must be a PNG, JPEG, WebP or GIF image.")
    if getattr(uploaded, "size", 0) > MAX_LOGO_BYTES:
        raise ValidationError("Logo must be 2 MB or smaller.")
    try:
        from PIL import Image

        uploaded.seek(0)
        image = Image.open(BytesIO(uploaded.read()))
        image.verify()
        uploaded.seek(0)
    except Exception as exc:
        raise ValidationError("That file is not a valid image.") from exc
    return uploaded


def _posted_content(request, fields):
    return {field.key: request.POST.get(field.key, "") for field in fields}


@site_manage_required
def site_management(request):
    recent = SiteChangeLog.objects.select_related("user")[:12]
    return render(
        request,
        "mgl/site_manage/hub.html",
        {
            "recent_changes": recent,
            "content_sections": public_sections(),
        },
    )


@site_manage_required
def site_management_teams(request):
    teams = (
        Team.objects.select_related("league", "manager")
        .annotate(player_count=Count("players"))
        .order_by("name", "id")
    )
    return render(
        request,
        "mgl/site_manage/teams.html",
        {"teams": teams},
    )


@site_manage_required
@require_http_methods(["GET", "POST"])
def site_management_team_edit(request, team_id):
    team = get_object_or_404(
        Team.objects.select_related("league", "manager"),
        pk=team_id,
    )
    original_pk = team.pk
    errors = []
    preview = False
    form = {
        "name": team.name,
        "short_name": team.short_name,
        "description": team.description or "",
    }

    if request.method == "POST":
        action = request.POST.get("action") or "save"
        name = (request.POST.get("name") or "").strip()
        short_name = (request.POST.get("short_name") or "").strip()
        description = request.POST.get("description") or ""
        form = {"name": name, "short_name": short_name, "description": description}
        if not name:
            errors.append("Team name cannot be empty.")
        elif len(name) > 100:
            errors.append("Team name must be 100 characters or fewer.")
        if not short_name:
            errors.append("Short name cannot be empty.")
        elif len(short_name) > 20:
            errors.append("Short name must be 20 characters or fewer.")
        elif (
            Team.objects.exclude(pk=team.pk)
            .filter(short_name__iexact=short_name)
            .exists()
        ):
            errors.append("Another club already uses that short name.")
        logo_file = request.FILES.get("logo")
        try:
            logo_file = _validate_logo_upload(logo_file)
        except ValidationError as exc:
            errors.append(str(exc))
            logo_file = None

        if action == "preview":
            preview = True
        elif not errors:
            old_name = team.name
            old_short = team.short_name
            old_description = team.description or ""
            old_logo = team.logo.name if team.logo else ""
            team.name = name
            team.short_name = short_name
            team.description = description
            # Never write badge_code, league, manager, tokens or player FKs.
            update_fields = ["name", "short_name", "description"]
            if logo_file:
                team.logo = logo_file
                update_fields.append("logo")
            team.save(update_fields=update_fields)
            team.refresh_from_db()
            if team.pk != original_pk:
                raise ValidationError("Team primary key must not change.")
            if name != old_name:
                log_site_change(
                    request.user,
                    action="team.name",
                    object_type="Team",
                    object_id=team.pk,
                    object_label=team.name,
                    old_value=old_name,
                    new_value=name,
                    summary=f"{actor_label(request.user)} changed {old_name} display name to {name}.",
                )
            if short_name != old_short:
                log_site_change(
                    request.user,
                    action="team.short_name",
                    object_type="Team",
                    object_id=team.pk,
                    object_label=team.name,
                    old_value=old_short,
                    new_value=short_name,
                    summary=f"{actor_label(request.user)} changed {team.name} short name.",
                )
            if description != old_description:
                log_site_change(
                    request.user,
                    action="team.description",
                    object_type="Team",
                    object_id=team.pk,
                    object_label=team.name,
                    old_value=old_description,
                    new_value=description,
                    summary=f"{actor_label(request.user)} changed {team.name} description.",
                )
            if logo_file:
                log_site_change(
                    request.user,
                    action="team.logo",
                    object_type="Team",
                    object_id=team.pk,
                    object_label=team.name,
                    old_value=old_logo,
                    new_value=team.logo.name if team.logo else "",
                    summary=f"{actor_label(request.user)} changed {team.name} logo.",
                )
            messages.success(request, "Changes saved successfully.")
            return redirect("site_management_team_edit", team_id=team.pk)

    return render(
        request,
        "mgl/site_manage/team_edit.html",
        {
            "team": team,
            "form": form,
            "errors": errors,
            "preview": preview,
            "player_count": team.players.count(),
        },
    )


@site_manage_required
def site_management_content(request):
    return render(
        request,
        "mgl/site_manage/content.html",
        {"sections": public_sections()},
    )


@site_manage_required
@require_http_methods(["GET", "POST"])
def site_management_content_section(request, section):
    section_meta = next((row for row in public_sections() if row["id"] == section), None)
    if section_meta is None:
        raise Http404("Unknown content section")
    fields = section_meta["fields"]
    errors = []
    preview = False
    values = {field.key: get_content(field.key) for field in fields}

    if request.method == "POST":
        action = request.POST.get("action") or "save"
        values = _posted_content(request, fields)
        if action == "preview":
            preview = True
        else:
            save_content_fields(request.user, fields, values, action_prefix="content")
            messages.success(request, "Changes saved successfully.")
            return redirect("site_management_content_section", section=section)

    return render(
        request,
        "mgl/site_manage/content_section.html",
        {
            "section": section_meta,
            "fields": fields,
            "values": values,
            "errors": errors,
            "preview": preview,
        },
    )


@site_manage_required
@require_http_methods(["GET", "POST"])
def site_management_settings(request):
    fields = settings_fields()
    preview = False
    values = {field.key: get_content(field.key) for field in fields}

    if request.method == "POST":
        action = request.POST.get("action") or "save"
        values = _posted_content(request, fields)
        if action == "preview":
            preview = True
        else:
            save_content_fields(request.user, fields, values, action_prefix="settings")
            messages.success(request, "Changes saved successfully.")
            return redirect("site_management_settings")

    return render(
        request,
        "mgl/site_manage/settings.html",
        {
            "fields": fields,
            "values": values,
            "preview": preview,
        },
    )


@site_manage_required
def site_management_leagues(request):
    leagues = League.objects.annotate(team_count=Count("teams")).order_by(
        "display_order", "id"
    )
    return render(
        request,
        "mgl/site_manage/leagues.html",
        {"leagues": leagues},
    )


@site_manage_required
@require_http_methods(["GET", "POST"])
def site_management_league_edit(request, league_id):
    league = get_object_or_404(League, pk=league_id)
    original_pk = league.pk
    errors = []
    preview = False
    form = {
        "display_name": league.display_name or league.name,
        "description": league.description or "",
        "display_order": str(league.display_order or 0),
    }

    if request.method == "POST":
        action = request.POST.get("action") or "save"
        display_name = (request.POST.get("display_name") or "").strip()
        description = request.POST.get("description") or ""
        order_raw = (request.POST.get("display_order") or "0").strip()
        form = {
            "display_name": display_name,
            "description": description,
            "display_order": order_raw,
        }
        if not display_name:
            errors.append("League display name cannot be empty.")
        elif len(display_name) > 100:
            errors.append("League display name must be 100 characters or fewer.")
        try:
            display_order = int(order_raw)
            if display_order < 0 or display_order > 999:
                raise ValueError
        except ValueError:
            display_order = league.display_order or 0
            errors.append("Display order must be a whole number between 0 and 999.")
        logo_file = request.FILES.get("logo")
        try:
            logo_file = _validate_logo_upload(logo_file)
        except ValidationError as exc:
            errors.append(str(exc))
            logo_file = None

        if action == "preview":
            preview = True
        elif not errors:
            old_display = league.display_name or ""
            old_description = league.description or ""
            old_order = league.display_order
            old_logo = league.logo.name if league.logo else ""
            league.display_name = display_name
            league.description = description
            league.display_order = display_order
            update_fields = ["display_name", "description", "display_order"]
            if logo_file:
                league.logo = logo_file
                update_fields.append("logo")
            league.save(update_fields=update_fields)
            league.refresh_from_db()
            if league.pk != original_pk:
                raise ValidationError("League primary key must not change.")
            if display_name != old_display:
                log_site_change(
                    request.user,
                    action="league.display_name",
                    object_type="League",
                    object_id=league.pk,
                    object_label=league.public_name,
                    old_value=old_display or league.name,
                    new_value=display_name,
                    summary=f"{actor_label(request.user)} changed {league.name} display name to {display_name}.",
                )
            if description != old_description:
                log_site_change(
                    request.user,
                    action="league.description",
                    object_type="League",
                    object_id=league.pk,
                    object_label=league.public_name,
                    old_value=old_description,
                    new_value=description,
                    summary=f"{actor_label(request.user)} changed {league.public_name} description.",
                )
            if display_order != old_order:
                log_site_change(
                    request.user,
                    action="league.display_order",
                    object_type="League",
                    object_id=league.pk,
                    object_label=league.public_name,
                    old_value=old_order,
                    new_value=display_order,
                    summary=f"{actor_label(request.user)} changed {league.public_name} display order.",
                )
            if logo_file:
                log_site_change(
                    request.user,
                    action="league.logo",
                    object_type="League",
                    object_id=league.pk,
                    object_label=league.public_name,
                    old_value=old_logo,
                    new_value=league.logo.name if league.logo else "",
                    summary=f"{actor_label(request.user)} changed {league.public_name} logo.",
                )
            messages.success(request, "Changes saved successfully.")
            return redirect("site_management_league_edit", league_id=league.pk)

    return render(
        request,
        "mgl/site_manage/league_edit.html",
        {
            "league": league,
            "form": form,
            "errors": errors,
            "preview": preview,
            "team_count": league.teams.count(),
        },
    )
