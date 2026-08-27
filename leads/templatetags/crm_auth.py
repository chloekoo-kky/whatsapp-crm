from django import template

from leads.permissions import can_see_all_leads as _can_see_all_leads
from leads.permissions import role_label

register = template.Library()


@register.simple_tag(takes_context=True)
def user_role_label(context):
    request = context.get("request")
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    return role_label(user)


@register.filter(name="can_see_all_leads")
def can_see_all_leads_filter(user):
    """``{% if request.user|can_see_all_leads %}`` — Supervisor/Admin/superuser."""
    if user is None:
        return False
    return _can_see_all_leads(user)
