from django import template

from leads.permissions import role_label

register = template.Library()


@register.simple_tag(takes_context=True)
def user_role_label(context):
    request = context.get("request")
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    return role_label(user)
