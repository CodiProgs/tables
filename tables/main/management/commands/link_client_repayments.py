from django.core.management.base import BaseCommand
from main.models import ClientDebtRepayment, CashFlow, PaymentPurpose
from datetime import timedelta

class Command(BaseCommand):
    help = 'Связывает существующие ClientDebtRepayment с CashFlow'

    def handle(self, *args, **options):
        # Получаем назначение "Погашение долга клиента"
        purpose = PaymentPurpose.objects.filter(name="Погашение долга клиента").first()
        if not purpose:
            self.stdout.write(self.style.ERROR('Назначение "Погашение долга клиента" не найдено'))
            return

        # Находим все ClientDebtRepayment без связи с CashFlow
        repayments = ClientDebtRepayment.objects.filter(cash_flow__isnull=True)
        linked_count = 0

        for repayment in repayments:
            # Ищем CashFlow по критериям:
            # 1. Назначение "Погашение долга клиента"
            # 2. Сумма совпадает (с учетом знака)
            # 3. Создан примерно в то же время (±5 секунд)
            # 4. Тот же пользователь
            # 5. Та же транзакция (если есть)
            
            time_from = repayment.created_at - timedelta(seconds=5)
            time_to = repayment.created_at + timedelta(seconds=5)
            
            cash_flow_query = CashFlow.objects.filter(
                purpose=purpose,
                amount=-abs(repayment.amount),
                created_at__gte=time_from,
                created_at__lte=time_to,
                created_by=repayment.created_by,
                client_debt_repayment__isnull=True  # Еще не связан
            )
            
            # Если есть транзакция, добавляем ее в фильтр
            if repayment.transaction:
                cash_flow_query = cash_flow_query.filter(transaction=repayment.transaction)
            
            cash_flow = cash_flow_query.first()
            
            if cash_flow:
                repayment.cash_flow = cash_flow
                repayment.save(update_fields=['cash_flow'])
                linked_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Связан ClientDebtRepayment #{repayment.id} с CashFlow #{cash_flow.id}'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(f'Успешно связано записей: {linked_count} из {repayments.count()}')
        )