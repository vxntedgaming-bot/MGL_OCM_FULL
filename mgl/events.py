"""Official UFL event engine.

Approved database work happens first. News, activity, notifications, and
Discord queue entries are side effects and must never undo the football
transaction.
"""

from mgl.discord_queue import queue_from_news
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
):
    post = _create_news(
        category,
        title,
        body,
        publish=publish,
        team=team,
        secondary_team=secondary_team,
        details=details,
    )
    try:
        queue_from_news(post)
    except Exception:
        # Discord is a notification layer. Never roll back official state.
        pass
    return post
