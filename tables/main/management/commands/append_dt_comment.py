from django.core.management.base import BaseCommand
from django.db import transaction
from main.models import Client, ClientDebtRepayment, CashFlow


class Command(BaseCommand):
    help = "Добавить в конец комментария 'Погашение долга клиента ДТ' для погашений клиента 'ДТ' и связанных движений ДС"

    def handle(self, *args, **options):
        try:
            dt = Client.objects.get(name="ДТ")
        except Client.DoesNotExist:
            self.stdout.write("Клиент 'ДТ' не найден")
            return

        suffix = "Погашение долга клиента ДТ"
        repayments = ClientDebtRepayment.objects.filter(client=dt).select_related('cash_flow')
        updated_repayments = 0
        updated_cashflows = 0

        for rep in repayments:
            with transaction.atomic():
                rep_comment = rep.comment or ""
                if suffix not in rep_comment:
                    if rep_comment.strip():
                        trimmed = rep_comment.rstrip()
                        if not trimmed.endswith('.'):
                            trimmed += '.'
                        rep.comment = f"{trimmed}\n{suffix}"
                    else:
                        rep.comment = suffix
                    rep.save(update_fields=['comment'])
                    updated_repayments += 1

                cf = rep.cash_flow
                if cf:
                    cf_comment = cf.comment or ""
                    if suffix not in cf_comment:
                        if cf_comment.strip():
                            trimmed_cf = cf_comment.rstrip()
                            if not trimmed_cf.endswith('.'):
                                trimmed_cf += '.'
                            cf.comment = f"{trimmed_cf}\n{suffix}"
                        else:
                            cf.comment = suffix
                        cf.save(update_fields=['comment'])
                        updated_cashflows += 1

        self.stdout.write(f"Найдено погашений: {repayments.count()}. Обновлено погашений: {updated_repayments}. Обновлено движений ДС: {updated_cashflows}.")