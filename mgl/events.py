"""Official UFL event engine.

Approved database work happens first. News, activity, notifications, and
Discord queue entries are side effects and must never undo the football
transaction.
"""

from mgl.services import create_news as _create_news


def emit_official_event(
    category,
    title,
    body,
    *,
    publish=True,
    team=None,
    secondary_team=None,
    details=None,
    discord_idempotency_key=None,
):
    return _create_news(
        category,
        title,
        body,
        publish=publish,
        team=team,
        secondary_team=secondary_team,
        details=details,
        discord_idempotency_key=discord_idempotency_key,
    )
