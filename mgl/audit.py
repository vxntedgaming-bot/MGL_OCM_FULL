"""Owner/Admin action log. Reuses SiteChangeLog so there is not a second audit table."""

from mgl.site_cms import log_site_change


def log_ocm_action(
    user,
    *,
    action,
    object_type,
    object_id="",
    object_label="",
    old_value="",
    new_value="",
    summary="",
):
    log_site_change(
        user,
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_label=object_label,
        old_value=old_value,
        new_value=new_value,
        summary=summary,
    )
