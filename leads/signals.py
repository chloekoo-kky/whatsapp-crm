from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from leads.models import CategoryRule, Tag, UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, created, **kwargs):
    if not created:
        return
    UserProfile.objects.get_or_create(
        user=instance,
        defaults={"role": UserProfile.ROLE_SALES},
    )


@receiver(post_delete, sender=CategoryRule)
def reseed_tag_match_rule_if_none_remain(sender, instance, **kwargs):
    """A non-system tag must always have at least one CategoryRule (label as phrase)."""
    slug = (instance.category or "").strip()
    if not slug:
        return
    if CategoryRule.objects.filter(category=slug).exists():
        return
    tag = Tag.objects.filter(slug=slug).first()
    if tag is None:
        return
    tag.ensure_default_match_rule()


@receiver(post_delete, sender=Tag)
def delete_match_rules_for_deleted_tag(sender, instance, **kwargs):
    CategoryRule.objects.filter(category=instance.slug).delete()

