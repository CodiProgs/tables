# Создайте папки management/commands если их нет
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from main.models import SupplierDebtRepayment, ClientDebtRepayment, CashFlow, PaymentPurpose, Account
from users.models import User

class Command(BaseCommand):
    help = "Создать CashFlow записи из существующих SupplierDebtRepayment и ClientDebtRepayment"

    def handle(self, *args, **options):
        created = 0
        skipped = 0
        # Нахождение кассы "Наличные"
        cash_account = Account.objects.filter(name__iexact="Наличные").first()

        # SupplierDebtRepayment -> purpose "Возврат от поставщиков", amount положительный (как в коде)
        purpose_sup, _ = PaymentPurpose.objects.get_or_create(
            name="Возврат от поставщиков",
            defaults={"operation_type": PaymentPurpose.EXPENSE}
        )

        for rep in SupplierDebtRepayment.objects.all().order_by('created_at'):
            rep_dt = rep.created_at or timezone.now()
            window_start = rep_dt - timedelta(seconds=5)
            window_end = rep_dt + timedelta(seconds=5)
            exists = CashFlow.objects.filter(
                supplier=rep.supplier,
                purpose__name__iexact=purpose_sup.name,
                amount=rep.amount,
                created_at__range=(window_start, window_end)
            ).exists()
            if exists:
                skipped += 1
                continue

            if not cash_account:
                self.stdout.write(self.style.WARNING(f"Пропущено SupplierDebtRepayment id={rep.id}: счет 'Наличные' не найден"))
                skipped += 1
                continue

            cf = CashFlow.objects.create(
                account=cash_account,
                supplier=rep.supplier,
                amount=rep.amount,
                purpose=purpose_sup,
                comment=rep.comment or f"Возврат от поставщиков: {rep.supplier}",
                created_by=rep.created_by if isinstance(rep.created_by, User) else None,
            )
            # Принудительно записываем дату из репликации
            if rep.created_at:
                CashFlow.objects.filter(pk=cf.pk).update(created_at=rep.created_at)
            created += 1

        # ClientDebtRepayment -> purpose "Погашение долга клиента", amount отрицательный (как в коде)
        purpose_cli, _ = PaymentPurpose.objects.get_or_create(
            name="Погашение долга клиента",
            defaults={"operation_type": PaymentPurpose.EXPENSE}
        )

        for rep in ClientDebtRepayment.objects.all().order_by('created_at'):
            rep_dt = rep.created_at or timezone.now()
            window_start = rep_dt - timedelta(seconds=5)
            window_end = rep_dt + timedelta(seconds=5)
            # В коде выдачи клиенту amount записывался отрицательным в CashFlow
            expected_amount = -abs(Decimal(rep.amount or 0))
            exists = CashFlow.objects.filter(
                purpose__name__iexact=purpose_cli.name,
                amount=int(expected_amount),
                created_at__range=(window_start, window_end)
            ).exists()
            if exists:
                skipped += 1
                continue

            if not cash_account:
                self.stdout.write(self.style.WARNING(f"Пропущено ClientDebtRepayment id={rep.id}: счет 'Наличные' не найден"))
                skipped += 1
                continue

            cf = CashFlow.objects.create(
                account=cash_account,
                supplier=None,
                amount=int(expected_amount),
                purpose=purpose_cli,
                comment=rep.comment or (f"Погашение долга клиента {getattr(rep, 'client', '')}"),
                created_by=rep.created_by if isinstance(rep.created_by, User) else None,
            )
            if rep.created_at:
                CashFlow.objects.filter(pk=cf.pk).update(created_at=rep.created_at)
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Создано CashFlow: {created}, пропущено (существует/ошибка): {skipped}"))