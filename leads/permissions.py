"""CRM role helpers. Superusers always pass, even without an Admin profile."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404


def get_role(user):
    try:
        profile = getattr(user, "profile", None)
        return profile.role if profile else None
    except ObjectDoesNotExist:
        return None


def can_see_all_leads(user):
    return user.is_authenticated and (
        user.is_superuser or get_role(user) in ("supervisor", "admin")
    )


def is_admin_tier(user):
    return user.is_authenticated and (user.is_superuser or get_role(user) == "admin")


def role_label(user):
    """Short label for the sidebar (Sales / Supervisor / Admin)."""
    labels = {"sales": "Sales", "supervisor": "Supervisor", "admin": "Admin"}
    role = get_role(user)
    if role in labels:
        if user.is_superuser and role != "admin":
            return labels[role] + " · superuser"
        return labels[role]
    if getattr(user, "is_superuser", False):
        return "Superuser"
    return "Sales"


def visible_leads(request):
    """The one queryset that decides which leads a CRM user may see or act on."""
    from leads.models import Lead

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return Lead.objects.none()
    if can_see_all_leads(user):
        return Lead.objects.all()
    return Lead.objects.filter(assigned_to=user)


def get_visible_lead_or_404(request, pk):
    return get_object_or_404(visible_leads(request), pk=pk)


def owned_lead_ids(request, submitted_ids):
    """Keep only client-submitted lead IDs that ``visible_leads`` would return."""
    ids = []
    if submitted_ids is None:
        return []
    for x in submitted_ids:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    return list(visible_leads(request).filter(pk__in=ids).values_list("pk", flat=True))


def sales_assignee_users():
    """Active users with the Sales role — the only targets for Assign to…"""
    from leads.models import UserProfile

    User = get_user_model()
    return User.objects.filter(
        is_active=True,
        profile__role=UserProfile.ROLE_SALES,
    ).order_by("first_name", "last_name", "username")


def hunt_owner_for_request(request):
    """Sales hunts/creates assign to themselves; Supervisor/Admin leave unassigned."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if can_see_all_leads(user):
        return None
    return user
