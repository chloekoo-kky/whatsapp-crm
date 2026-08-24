from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from leads.models import Lead


class Command(BaseCommand):
    help = (
        "Assign every lead with no owner to the given username. "
        "Safe to re-run; already-owned leads are left unchanged."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--to",
            required=True,
            help="Username that should own currently unowned leads.",
        )

    def handle(self, *args, **options) -> None:
        username = (options.get("to") or "").strip()
        if not username:
            raise CommandError("--to is required (a username).")

        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"No user with username {username!r}.") from exc

        updated = Lead.objects.filter(assigned_to__isnull=True).update(assigned_to=user)
        self.stdout.write(
            self.style.SUCCESS(f"Assigned {updated} lead(s) to {username!r}.")
        )
