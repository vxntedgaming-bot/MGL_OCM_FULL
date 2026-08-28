from django.core.management.base import BaseCommand

from mgl.starting_pool import build_starting_pool, format_plan_report


class Command(BaseCommand):
    help = (
        "Dry-run a 14×26 balanced starting auction pool from unassigned 64–70 OVR "
        "players. Never writes Player rows, auctions, or tokens."
    )

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=None)
        parser.add_argument("--attempts", type=int, default=120)
        parser.add_argument("--output", type=str, default="")

    def handle(self, *args, **options):
        plan = build_starting_pool(seed=options["seed"], max_attempts=options["attempts"])
        report = format_plan_report(plan)
        self.stdout.write(report)
        output = options["output"]
        if output:
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(report)
                handle.write("\n")
            self.stdout.write(self.style.SUCCESS(f"Wrote {output}"))
        if not plan.exact:
            self.stderr.write(self.style.ERROR("Exact equal totals were not produced. No data was written."))
            return
        self.stdout.write(self.style.SUCCESS("DRY RUN ONLY — no players were assigned and no auctions were created."))
