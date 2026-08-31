from django.core.management.base import BaseCommand

from mgl.ufl_settings import UFL_MAX_OVR, UFL_MIN_OVR, UFL_SQUAD_SHAPE


class Command(BaseCommand):
    help = (
        "Dry-run the UFL 25-man / 64–69 starting shape. Never writes club "
        "assignments. Live 14×26 allocations stay untouched."
    )

    def handle(self, *args, **options):
        total = sum(count for _pos, count in UFL_SQUAD_SHAPE)
        self.stdout.write("UFL starting squad shape (dry-run only):")
        for position, count in UFL_SQUAD_SHAPE:
            self.stdout.write(f"  {count} × {position}")
        self.stdout.write(f"Total per club: {total}")
        self.stdout.write(f"OVR window: {UFL_MIN_OVR}–{UFL_MAX_OVR}")
        self.stdout.write("Owner preview lives at Control → Season → Starting Squads.")
        self.stdout.write(self.style.WARNING("No players were assigned."))
