"""Press conference questions on the existing PressConference model."""

from __future__ import annotations

import random
from datetime import timedelta

from django.utils import timezone

from mgl.models import ApprovalStatus, NewsPost, PressConference
from mgl.services import create_news, manager_for_user
from teams.models import Team

QUESTION_BANK = {
    "performance": [
        ("perf_pleased", "How pleased were you with the performance?"),
        ("perf_positive", "What was the biggest positive from today's match?"),
        ("perf_wrong", "What do you think went wrong today?"),
        ("perf_goals", "Your team scored plenty today. What pleased you most?"),
        ("perf_defence", "How do you assess the defensive performance?"),
        ("perf_player", "Which player made the difference for you today?"),
        ("perf_reaction", "How did the dressing room react to that result?"),
        ("perf_standard", "Was that the standard you demand from this squad?"),
    ],
    "tactics": [
        ("tac_change", "What tactical change made the difference?"),
        ("tac_opponent", "Were you surprised by your opponent's approach?"),
        ("tac_shape", "Did you get the shape you wanted from the first whistle?"),
        ("tac_plan", "How closely did the match follow the game plan?"),
        ("tac_press", "How important was the press in today's result?"),
        ("tac_width", "Did you want more width, or was the compact shape deliberate?"),
    ],
    "transfers": [
        ("tr_happy", "Are you happy with the latest signing?"),
        ("tr_bring", "What does this player bring to your squad?"),
        ("tr_business", "You've strengthened the squad this week. Are you happy with the business you've done?"),
        ("tr_horizon", "Are you building for immediate success or the long term?"),
        ("tr_fit", "How quickly do you expect the new signing to fit the system?"),
        ("tr_more", "Is the recruitment window finished, or are you still looking?"),
    ],
    "squad": [
        ("sq_impressed", "Which player has impressed you most recently?"),
        ("sq_depth", "How important has your squad depth become?"),
        ("sq_group", "How is the dressing room looking after that result?"),
        ("sq_minutes", "How are you managing minutes across the squad?"),
        ("sq_young", "How much trust are you placing in the younger players?"),
    ],
    "league": [
        ("lg_climb", "You're climbing the table. Can you maintain this form?"),
        ("lg_ambition", "What are your ambitions for the rest of the season?"),
        ("lg_position", "How do you assess the league position after that match?"),
        ("lg_title", "Are you thinking about the top of the table, or taking it game by game?"),
        ("lg_drop", "How do you lift the group after a result like that?"),
    ],
    "rivalries": [
        ("rv_important", "How important was today's result against a league rival?"),
        ("rv_message", "What message does that result send to the rest of the division?"),
        ("rv_respect", "Did you give the opponent enough respect today?"),
    ],
    "new_manager": [
        ("nm_priorities", "You've just taken charge. What are your first priorities as the new manager?"),
        ("nm_football", "What kind of football do you want your team to play?"),
        ("nm_squad", "What did you make of the squad you have inherited?"),
        ("nm_start", "How quickly do you want to put your stamp on this club?"),
        ("nm_fans", "What do you want the supporters to see from day one?"),
    ],
    "upcoming": [
        ("up_expect", "What are you expecting from your next opponent?"),
        ("up_prepare", "How do you prepare the group for the next fixture?"),
        ("up_focus", "Is the next match a chance to prove a point?"),
        ("up_rotate", "Will you rotate, or keep the same spine?"),
    ],
}

MATCH_CATEGORY_BY_RESULT = {
    "WIN": ("performance", "tactics", "league", "rivalries", "squad"),
    "DRAW": ("performance", "tactics", "upcoming", "squad"),
    "LOSS": ("performance", "tactics", "league", "upcoming"),
}


def _pick_question(categories, manager, used_keys=None):
    used_keys = set(used_keys or [])
    pending_keys = set(
        PressConference.objects.filter(
            manager=manager,
            status=ApprovalStatus.PENDING,
        ).exclude(question_key="").values_list("question_key", flat=True)
    )
    used_keys |= pending_keys
    options = []
    for category in categories:
        for key, question in QUESTION_BANK.get(category, ()):
            if key not in used_keys:
                options.append((category, key, question))
    if not options:
        for category in categories:
            for key, question in QUESTION_BANK.get(category, ()):
                options.append((category, key, question))
    if not options:
        return "performance", "perf_pleased", "How pleased were you with the performance?"
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
):
    if manager is None:
        return None
    if trigger == PressConference.MATCH and getattr(fixture, "id", None):
        if PressConference.objects.filter(fixture_id=fixture.id, manager=manager).exists():
            return None
    if question_key and _has_pending(manager, question_key=question_key):
        return None
    if _has_pending(manager, trigger=trigger, fixture=fixture):
        return None
    return PressConference.objects.create(
        fixture=fixture,
        team=team,
        manager=manager,
        trigger=trigger,
        category=category,
        question_key=question_key,
        question=question,
        status=ApprovalStatus.PENDING,
        matchweek=matchweek,
    )


def create_match_press_questions(fixture, home_stats, away_stats):
    created = []
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
        category, key, question = _pick_question(categories, team.manager)
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
    recent_ids = list(
        PressConference.objects.filter(trigger=PressConference.ODD_MATCHDAY)
        .order_by("-created_at")
        .values_list("manager_id", flat=True)[:12]
    )
    managers = list(
        Team.objects.filter(manager__isnull=False, league=fixture.league)
        .exclude(manager_id__in=recent_ids)
        .values_list("manager_id", flat=True)
    )
    if not managers:
        managers = list(
            Team.objects.filter(manager__isnull=False, league=fixture.league)
            .values_list("manager_id", flat=True)
        )
    if not managers:
        return None
    from accounts.models import User

    manager = User.objects.filter(pk=random.choice(managers)).first()
    if not manager:
        return None
    team = _club_for_user(manager)
    category, key, question = _pick_question(
        ("league", "upcoming", "squad", "performance"),
        manager,
    )
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
    category, key, question = _pick_question(("new_manager",), user)
    club = team.name if team else "the club"
    question = question.replace("You've just taken charge.", f"You've just taken charge of {club}.")
    if "You've just taken charge of" not in question:
        question = f"You've just taken charge of {club}. What are your first priorities as the new manager?"
        key = "nm_priorities"
        category = "new_manager"
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
    week_ago = timezone.now() - timedelta(days=7)
    recent = NewsPost.objects.filter(
        published=True,
        category__in=[NewsPost.SIGNING, NewsPost.TRANSFER],
        created_at__gte=week_ago,
        body__icontains=team.name,
    ).count()
    if recent < 2:
        return None
    category, key, question = _pick_question(("transfers",), user)
    return create_press_question(
        manager=user,
        team=team,
        question=question,
        question_key=key,
        category=category,
        trigger=PressConference.SIGNING,
    )


def publish_press_answer(press, answer):
    answer = (answer or "").strip()
    if not answer:
        raise ValueError("Please answer the question.")
    if press.answer and press.status == ApprovalStatus.APPROVED:
        raise ValueError("This interview has already been submitted.")
    press.answer = answer
    press.status = ApprovalStatus.APPROVED
    press.approved_at = timezone.now()
    press.save(update_fields=["answer", "status", "approved_at"])
    manager_name = press.manager.username
    application = manager_for_user(press.manager)
    if application:
        manager_name = application.display_name
    club = press.team.name if press.team_id else "MGL"
    create_news(
        NewsPost.PRESS,
        f"{manager_name} | {club} press conference",
        f"Q: {press.question}\n\nA: {press.answer}",
    )
    return press


def published_press():
    return (
        PressConference.objects.filter(status=ApprovalStatus.APPROVED)
        .exclude(answer="")
        .select_related("manager", "team", "team__league", "fixture")
        .order_by("-approved_at", "-created_at")
    )
