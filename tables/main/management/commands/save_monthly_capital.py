from django.core.management.base import BaseCommand
from django.utils import timezone
from main.views import calculate_and_save_monthly_capital

class Command(BaseCommand):
    help = "Сохраняет капитал на последний день текущего месяца"

    def handle(self, *args, **options):
        today = timezone.now().date()
        year, month = today.year, today.month

        calculate_and_save_monthly_capital(year, month)

        self.stdout.write(self.style.SUCCESS(
            f"Capital calculated and saved for {year}-{month}"
        ))