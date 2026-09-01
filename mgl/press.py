"""Press conference questions on the existing PressConference model."""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from mgl.models import ApprovalStatus, NewsPost, PressConference
from mgl.press_questions import (
    APPOINTMENT_CATEGORIES,
    MATCH_CATEGORY_BY_RESULT,
    MULTI_SIGNING_CATEGORIES,
    ODD_MATCHDAY_CATEGORIES,
    QUESTION_BANK,
    RELEASE_CATEGORIES,
    RECENT_QUESTION_LIMIT,
    SIGNING_CATEGORIES,
)
from mgl.services import create_news, manager_for_user
from teams.models import Team


def _season_number(fixture=None):
    if fixture is not None and getattr(fixture, "season_number", None):
        return fixture.season_number
    try:
        from mgl.season_history import current_season_number

        return current_season_number()
    except Exception:
        return 1


def _format_question(question, team=None, extra=None):
    club = team.name if team is not None else "the club"
    question = question.replace("{club}", club)
    for key, value in (extra or {}).items():
        question = question.replace("{" + key + "}", str(value or ""))
    return question


def _used_keys_for_manager(manager):
    recent = list(
        PressConference.objects.filter(manager=manager)
        .exclude(question_key="")
        .order_by("-created_at")
        .values_list("question_key", flat=True)[:RECENT_QUESTION_LIMIT]
    )
    pending_own = PressConference.objects.filter(
        manager=manager,
        status=ApprovalStatus.PENDING,
    ).exclude(question_key="")
    return set(recent) | set(pending_own.values_list("question_key", flat=True))


def _globally_pending_keys(exclude_manager=None):
    qs = PressConference.objects.filter(status=ApprovalStatus.PENDING).exclude(
        question_key=""
    )
    if exclude_manager is not None:
        qs = qs.exclude(manager=exclude_manager)
    return set(qs.values_list("question_key", flat=True))


def _collect_options(categories, blocked):
    options = []
    for category in categories:
        for key, question in QUESTION_BANK.get(category, ()):
            if key not in blocked:
                options.append((category, key, question))
    return options


def _pick_question(categories, manager, extra_blocked=None):
    blocked = _used_keys_for_manager(manager)
    blocked |= _globally_pending_keys()
    blocked |= set(extra_blocked or [])
    options = _collect_options(categories, blocked)
    if not options:
        options = _collect_options(categories, _globally_pending_keys())
    if not options:
        options = _collect_options(categories, _used_keys_for_manager(manager))
    if not options:
        options = _collect_options(categories, set())
    if not options:
        return "post_match", "pm_pleased", "What pleased you most about the performance?"
    return random.choice(options)


def _club_for_user(user):
    return Team.objects.filter(manager=user).select_related("league").first()


def _has_pending(manager, trigger=None, fixture=None, question_key=None):
    qs = PressConference.objects.filter(manager=manager, status=ApprovalStatus.PENDING)
    if trigger:
        qs = qs.filter(trigger=trigger)
    if fixture is not None:
        qs = qs.filter(fixture=fixture)
    if question_key:
        qs = qs.filter(question_key=question_key)
    return qs.exists()


def create_press_question(
    *,
    manager,
    team,
    question,
    question_key,
    category,
    trigger,
    fixture=None,
    matchweek=None,
    available_at=None,
    allow_multiple=False,
):
    if manager is None:
        return None
    if trigger == PressConference.MATCH and getattr(fixture, "id", None):
        if PressConference.objects.filter(fixture_id=fixture.id, manager=manager).exists():
            return None
    if question_key and _has_pending(manager, question_key=question_key):
        return None
    if question_key and PressConference.objects.filter(
        question_key=question_key,
        status=ApprovalStatus.PENDING,
    ).exclude(manager=manager).exists():
        return None
    if not allow_multiple and _has_pending(manager, trigger=trigger, fixture=fixture):
        return None
    from mgl.ufl_settings import press_per_24h

    window = timezone.now() - timedelta(hours=24)
    recent = PressConference.objects.filter(manager=manager, created_at__gte=window).count()
    if recent >= press_per_24h():
        return None
    return PressConference.objects.create(
        fixture=fixture,
        team=team,
        manager=manager,
        trigger=trigger,
        category=category,
        question_key=question_key,
        question=_format_question(question, team),
        status=ApprovalStatus.PENDING,
        matchweek=matchweek,
        season_number=_season_number(fixture),
        available_at=available_at,
        reward=Decimal("0.50"),
    )


def create_match_press_questions(fixture, home_stats, away_stats):
    created = []
    used_this_event = set()
    home_goals = home_stats.goals
    away_goals = away_stats.goals
    sides = (
        (fixture.home_team, home_goals, away_goals),
        (fixture.away_team, away_goals, home_goals),
    )
    for team, scored, conceded in sides:
        if not team.manager_id:
            continue
        if scored > conceded:
            result = "WIN"
        elif scored == conceded:
            result = "DRAW"
        else:
            result = "LOSS"
        categories = MATCH_CATEGORY_BY_RESULT[result]
        opponent = fixture.away_team if team.id == fixture.home_team_id else fixture.home_team
        category, key, question = _pick_question(
            categories,
            team.manager,
            extra_blocked=used_this_event,
        )
        if result == "WIN":
            question = (
                f"You've secured an important victory against {opponent.name} "
                f"({scored}–{conceded}). What pleased you most about the performance?"
            )
        elif result == "LOSS":
            question = (
                f"Your team suffered a difficult defeat to {opponent.name} "
                f"({scored}–{conceded}). What went wrong and how do you respond?"
            )
        else:
            question = (
                f"You shared the points with {opponent.name} at {scored}–{conceded}. "
                f"Is that a fair reflection of the contest?"
            )
        row = create_press_question(
            manager=team.manager,
            team=team,
            question=question,
            question_key=key,
            category=category,
            trigger=PressConference.MATCH,
            fixture=fixture,
            matchweek=fixture.matchweek,
        )
        if row:
            used_this_event.add(key)
            created.append(row)
    return created


def maybe_create_odd_matchday_interview(fixture):
    if not fixture.matchweek or fixture.matchweek % 2 == 0:
        return None
    already = PressConference.objects.filter(
        trigger=PressConference.ODD_MATCHDAY,
        matchweek=fixture.matchweek,
        status__in=[ApprovalStatus.PENDING, ApprovalStatus.APPROVED],
    )
    if already.exists():
        return None
    last_odd = (
        PressConference.objects.filter(trigger=PressConference.ODD_MATCHDAY)
        .order_by("-created_at")
        .values_list("manager_id", flat=True)
        .first()
    )
    played_ids = {
        manager_id
        for manager_id in (fixture.home_team.manager_id, fixture.away_team.manager_id)
        if manager_id
    }
    match_this_week = set(
        PressConference.objects.filter(
            trigger=PressConference.MATCH,
            matchweek=fixture.matchweek,
        ).values_list("manager_id", flat=True)
    )
    excluded = set()
    if last_odd:
        excluded.add(last_odd)
    excluded |= played_ids
    excluded |= match_this_week
    managers = list(
        Team.objects.filter(manager__isnull=False, league=fixture.league)
        .exclude(manager_id__in=excluded)
        .values_list("manager_id", flat=True)
    )
    if not managers:
        managers = list(
            Team.objects.filter(manager__isnull=False, league=fixture.league)
            .exclude(manager_id=last_odd)
            .exclude(manager_id__in=played_ids)
            .values_list("manager_id", flat=True)
        )
    if not managers:
        return None
    from accounts.models import User

    manager = User.objects.filter(pk=random.choice(managers)).first()
    if not manager:
        return None
    team = _club_for_user(manager)
    category, key, question = _pick_question(ODD_MATCHDAY_CATEGORIES, manager)
    return create_press_question(
        manager=manager,
        team=team,
        question=question,
        question_key=key,
        category=category,
        trigger=PressConference.ODD_MATCHDAY,
        fixture=None,
        matchweek=fixture.matchweek,
    )


def create_appointment_press(user, team):
    category, key, question = _pick_question(APPOINTMENT_CATEGORIES, user)
    question = _format_question(question, team)
    if team is not None and team.name not in question:
        question = f"You've just taken charge of {team.name}. {question}"
    return create_press_question(
        manager=user,
        team=team,
        question=question,
        question_key=key,
        category=category,
        trigger=PressConference.APPOINTMENT,
    )


def maybe_create_signing_press(user, team):
    if user is None or team is None:
        return None
    if _has_pending(user, trigger=PressConference.SIGNING):
        return None
    cooldown = timezone.now() - timedelta(days=14)
    if PressConference.objects.filter(
        manager=user,
        trigger=PressConference.SIGNING,
        created_at__gte=cooldown,
    ).exists():
        return None
    week_ago = timezone.now() - timedelta(days=7)
    recent = NewsPost.objects.filter(
        published=True,
        category__in=[NewsPost.SIGNING, NewsPost.TRANSFER],
        created_at__gte=week_ago,
        body__icontains=team.name,
    ).count()
    if recent < 1:
        return None
    categories = MULTI_SIGNING_CATEGORIES if recent >= 3 else SIGNING_CATEGORIES
    category, key, question = _pick_question(categories, user)
    latest = (
        NewsPost.objects.filter(
            published=True,
            category__in=[NewsPost.SIGNING, NewsPost.TRANSFER],
            created_at__gte=week_ago,
            body__icontains=team.name,
        )
        .order_by("-created_at")
        .first()
    )
    if latest and latest.title:
        question = (
            f"You've strengthened the squad with a new signing. {latest.title.rstrip('.')}. "
            f"What does he bring to your team?"
        )
    return create_press_question(
        manager=user,
        team=team,
        question=question,
        question_key=key,
        category=category,
        trigger=PressConference.SIGNING,
    )


def create_release_press(user, team, player=None):
    if user is None or team is None:
        return None
    if _has_pending(user, trigger=PressConference.RELEASE):
        return None
    category, key, question = _pick_question(RELEASE_CATEGORIES, user)
    if player is not None and player.name and player.name not in question:
        question = (
            f"You've decided to release {player.name}. What led to the decision?"
        )
    return create_press_question(
        manager=user,
        team=team,
        question=question,
        question_key=key,
        category=category,
        trigger=PressConference.RELEASE,
    )


def submit_press_answer(press, answer):
    """Store a manager's answer. Public Pressroom waits for Admin approval."""
    answer = (answer or "").strip()
    if not answer:
        raise ValueError("Please answer the question.")
    if press.status == ApprovalStatus.APPROVED and press.answer:
        raise ValueError("This interview has already been published.")
    if press.status == ApprovalStatus.REJECTED:
        raise ValueError("This interview was rejected.")
    if press.answer and press.status == ApprovalStatus.PENDING:
        raise ValueError("This interview is already awaiting Admin approval.")
    press.answer = answer
    press.status = ApprovalStatus.PENDING
    press.save(update_fields=["answer", "status"])
    from mgl.notifications import mark_action_complete, notify_user

    mark_action_complete(press.manager, f"press-{press.pk}")
    notify_user(
        press.manager,
        source_key=f"press-submitted-{press.pk}",
        notification_type="PRESS",
        title="PRESS CONFERENCE SUBMITTED",
        message="Your answer is waiting for league-office approval.",
        actor="UFL Press Room",
        team=press.team,
    )
    return press


def publish_press_answer(press, answer):
    """Managers submit answers. Admin approval publishes to Pressroom."""
    return submit_press_answer(press, answer)


def _press_news_copy(press):
    manager_name = press.manager.username
    application = manager_for_user(press.manager)
    if application:
        manager_name = application.display_name
    club = press.team.name if press.team_id else "UFL"
    return (
        f"{manager_name} | {club} press conference",
        f"Q: {press.question}\n\nA: {press.answer}",
    )


PRESS_DAILY_TOKEN_CAP = Decimal("2.00")


def press_tokens_earned_last_24h(manager, now=None):
    """Approved press credits in the rolling 24-hour window."""
    from django.db.models import Sum

    from mgl.models import RewardTransaction

    now = now or timezone.now()
    earned = (
        RewardTransaction.objects.filter(
            manager=manager,
            category="PRESS",
            created_at__gte=now - timedelta(hours=24),
            reversed_at__isnull=True,
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    return Decimal(str(earned))


def approve_press_conference(press, reviewer=None):
    if press.status == ApprovalStatus.APPROVED and (press.answer or "").strip():
        return press
    if press.status == ApprovalStatus.REJECTED:
        raise ValueError("This interview was rejected.")
    if not (press.answer or "").strip():
        raise ValueError("This interview has no answer to approve.")
    press.status = ApprovalStatus.APPROVED
    press.approved_at = timezone.now()
    press.save(update_fields=["status", "approved_at"])
    title, body = _press_news_copy(press)
    create_news(
        NewsPost.PRESS,
        title,
        body,
        team=press.team,
        discord_idempotency_key=f"press.approve:{press.pk}",
    )
    from mgl.services import credit_manager, manager_for_user as reward_manager
    from mgl.ufl_settings import press_reward

    application = reward_manager(press.manager)
    if application:
        reward = press_reward()
        earned = press_tokens_earned_last_24h(application)
        if earned + reward <= PRESS_DAILY_TOKEN_CAP:
            credit_manager(
                application,
                reward,
                "Press Conference Approved",
                "PRESS",
                fixture=press.fixture,
                reference=f"press:{press.pk}",
            )
            from mgl.notifications import notify_user

            notify_user(
                press.manager,
                source_key=f"press-reward-{press.pk}",
                notification_type="REWARD",
                title="PRESS CONFERENCE APPROVED",
                message=f"+{reward} TOKENS have been added to your balance.",
                actor="UFL Press Room",
                team=press.team,
            )
    return press


def reject_press_conference(press, reviewer=None):
    if press.status == ApprovalStatus.APPROVED:
        raise ValueError("This interview is already published.")
    if press.status == ApprovalStatus.REJECTED:
        return press
    press.status = ApprovalStatus.REJECTED
    press.save(update_fields=["status"])
    return press


def pending_press_reviews():
    return (
        PressConference.objects.filter(status=ApprovalStatus.PENDING)
        .exclude(answer="")
        .select_related("manager", "team", "fixture")
        .order_by("-created_at")
    )


def published_press():
    return (
        PressConference.objects.filter(status=ApprovalStatus.APPROVED)
        .exclude(answer="")
        .select_related("manager", "team", "team__league", "fixture")
        .order_by("-approved_at", "-created_at")
    )
