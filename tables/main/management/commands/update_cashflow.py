from django.core.management.base import BaseCommand
from django.db import transaction
from main.models import CashFlow, PaymentPurpose

class Command(BaseCommand):
    help = "Обновить назначение на 'ДТ' для CashFlow с назначением 'Погашение долга клиента' и комментарием 'Выдача клиенту ДТ'"

    def handle(self, *args, **options):
        with transaction.atomic():
            # Найти или создать PaymentPurpose с названием "ДТ"
            dt_purpose, created = PaymentPurpose.objects.get_or_create(name="ДТ")

            # Фильтровать записи CashFlow
            cashflows = CashFlow.objects.filter(
                purpose__name="Погашение долга клиента",  # Используем правильное поле для назначения
                comment__icontains="Выдача клиенту ДТ"    # Используем правильное поле для комментария
            )

            # Обновить назначение
            updated_count = cashflows.update(purpose=dt_purpose)

            self.stdout.write(f"Обновлено записей: {updated_count}")