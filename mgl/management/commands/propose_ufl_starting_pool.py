from django.core.management.base import BaseCommand

from mgl.ufl_settings import UFL_MAX_OVR, UFL_MIN_OVR, UFL_SQUAD_SHAPE


class Command(BaseCommand):
    help = (
        "Print the official UFL 25-player starting structure. Never writes "
        "club assignments. Live squads stay untouched."
    )

    def handle(self, *args, **options):
        total = sum(count for _pos, count in UFL_SQUAD_SHAPE)
        self.stdout.write("Official UFL 25-player starting squad (preview only):")
        for position, count in UFL_SQUAD_SHAPE:
            self.stdout.write(f"  {position} {count} / {count}")
        self.stdout.write(f"TOTAL {total} / {total}")
        self.stdout.write(f"OVR window: {UFL_MIN_OVR}–{UFL_MAX_OVR}")
        self.stdout.write("Owner preview lives at Control → Season → Starting Squads.")
        self.stdout.write(self.style.WARNING("No players were assigned."))
