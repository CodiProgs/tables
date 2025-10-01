from django.core.management.base import BaseCommand
from tables.main.views import calculate_and_save_monthly_capital
from datetime import datetime

class Command(BaseCommand):
    help = "Сохраняет капитал за текущий месяц"

    def handle(self, *args, **kwargs):
        now = datetime.now()
        year = now.year
        month = now.month
        calculate_and_save_monthly_capital(year, month)
        self.stdout.write(self.style.SUCCESS(f"Капитал за {month}.{year} сохранён"))