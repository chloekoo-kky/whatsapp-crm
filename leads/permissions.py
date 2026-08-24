"""CRM role helpers. Superusers always pass, even without an Admin profile."""

from django.core.exceptions import ObjectDoesNotExist


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
