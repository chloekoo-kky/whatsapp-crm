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
