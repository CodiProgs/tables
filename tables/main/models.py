from django.db import models
from decimal import Decimal
import math

class Client(models.Model):
    name = models.CharField(max_length=255, verbose_name="Клиент")
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=0.0,
        verbose_name="Процент"
    )
    comment = models.TextField(
        blank=True,
        null=True,
        verbose_name="Комментарий"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"

class Branch(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Филиал")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Филиал"
        verbose_name_plural = "Филиалы"
        ordering = ['name']

class Supplier(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название")
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.SET_NULL,
        verbose_name="Филиал",
        related_name="suppliers",
        null=True,
        blank=True
    )
    cost_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=0.0,
        verbose_name="%"
    )
    default_account = models.ForeignKey(
        'Account',
        on_delete=models.SET_NULL,
        verbose_name="Расчетный счет",
        related_name="default_suppliers",
        null=True,  
        blank=True
    )
    user = models.OneToOneField(
        "users.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        unique=True,
        related_name="supplier_profile"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Поставщик"
        verbose_name_plural = "Поставщики"

class Transaction(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата")
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        verbose_name="Клиент",
        null=True,
        blank=True
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        verbose_name="Поставщик",
        null=True,
        blank=True
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        verbose_name="Сумма"
    )
    client_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        verbose_name="%"
    )
    bonus_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        verbose_name="%"
    )
    supplier_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        verbose_name="%"
    )
    paid_amount = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        verbose_name="Оплачено",
        null=True,
        blank=True
    )
    documents = models.BooleanField(
        default=False,
        verbose_name="Документы"
    )
    returned_by_supplier = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        verbose_name="Возвращено",
        null=True,
        blank=True
    )
    returned_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата возврата"
    )

    returned_bonus = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Возвращено бонуса",
        null=True,
        blank=True
    )
    returned_to_client = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Возвращено клиенту",
        null=True,
        blank=True
    )

    modified_by_accountant = models.BooleanField(default=False, verbose_name="Изменено бухгалтером")
    viewed_by_admin = models.BooleanField(default=False, verbose_name="Просмотрено администратором")

    class Meta:
        default_permissions = ()
        verbose_name = "Транзакция"
        verbose_name_plural = "Транзакции"

    @property
    def remaining_amount(self):
        """Сумма после вычета процента клиента"""
        result = math.floor(self.amount * (100 - self.client_percentage) / 100)
        return Decimal(result)

    @property
    def bonus(self):
        """Бонус в денежном выражении"""
        result = math.floor(self.amount * self.bonus_percentage / 100)
        return Decimal(result)

    @property
    def profit(self):
        """Прибыль = (процент клиента - процент поставщика - бонус) в деньгах"""
        client_fee = math.floor(self.amount * self.client_percentage / 100)
        supplier_fee = math.floor(self.amount * self.supplier_percentage / 100)
        bonus = math.floor(self.amount * self.bonus_percentage / 100)
        
        return Decimal(client_fee - supplier_fee - bonus)

    @property
    def debt(self):
        """Задолженность = общая сумма - оплаченная сумма"""
        debt = self.paid_amount - self.amount

        return {
            "amount": debt,
            "currency": " р."
        }
    
    @property
    def supplier_debt(self):
        """
        Долг поставщика = оплаченная сумма - сумма по проценту поставщика
        """
        paid = self.paid_amount or Decimal(0)
        supplier_fee = Decimal(math.floor(float(self.amount) * float(self.supplier_percentage) / 100))
        return paid - supplier_fee - self.returned_by_supplier
    
    @property
    def client_debt(self):
        """
        Долг клиента = оставшаяся сумма - возвращенная клиенту
        """
        return self.remaining_amount - self.returned_to_client

    @property
    def bonus_debt(self):
        """
        Долг по бонусам = бонус - возвращенный бонус
        """
        return self.bonus - self.returned_bonus

    @property
    def client_debt_paid(self):
        """
        Долг клиента, рассчитанный от оплаченной суммы
        """
        result = math.floor(self.paid_amount * (100 - self.client_percentage) / 100)
        return Decimal(result) - self.returned_to_client

class AccountType(models.Model):
    name = models.CharField(max_length=100, verbose_name="Тип счета")
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Тип счета"
        verbose_name_plural = "Типы счетов"
        ordering = ['name']

class Account(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название")
    account_type = models.ForeignKey(
        AccountType,
        on_delete=models.PROTECT,
        verbose_name="Тип счета",
        related_name="accounts",
        null=True,
        blank=True
    )
    suppliers = models.ManyToManyField(
        Supplier,
        through='SupplierAccount',
        verbose_name="Поставщики",
        related_name="accounts",
        blank=True
    )
    balance = models.DecimalField(
        max_digits=15, 
        decimal_places=0,
        default=0,
        verbose_name="Баланс"
    )

    def __str__(self):
        return f"{self.name}"
    
    class Meta:
        verbose_name = "Счет"
        verbose_name_plural = "Счета"
        ordering = ['-balance', 'name']

class PaymentPurpose(models.Model):
    INCOME = 'income'
    EXPENSE = 'expense'
    
    TYPE_CHOICES = [
        (INCOME, 'Приход'),
        (EXPENSE, 'Расход'),
    ]

    name = models.CharField(max_length=255, verbose_name="Название")
    operation_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default=EXPENSE,
        verbose_name="Тип операции"
    )
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Назначение платежа"
        verbose_name_plural = "Назначения платежей"
        ordering = ['name']

class CashFlow(models.Model):
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        verbose_name    ="Счет",
        related_name="cash_flows"
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        verbose_name="Поставщик",
        related_name="cash_flows",
        null=True,
        blank=True
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        verbose_name="Сумма"
    )
    purpose = models.ForeignKey(
        PaymentPurpose,
        on_delete=models.PROTECT,
        verbose_name="Назначение платежа",
        related_name="cash_flows"
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        verbose_name="Связанная транзакция",
        related_name="cash_flows",
        null=True,
        blank=True
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Дата операции"
    )
    
    @property
    def formatted_amount(self):
        """Возвращает сумму с форматированием и суффиксом 'р.'"""
        from locale import format_string
        formatted = format_string("%.0f", float(self.amount), grouping=True)
        return f"{formatted} р."

    @property
    def operation_type(self):
        """Возвращает тип операции (приход/расход)"""
        return self.purpose.operation_type if self.purpose else None

    def __str__(self):
        return f"{self.purpose}: {self.amount} р. ({self.account})"
    
    class Meta:
        verbose_name = "Движение ДС"
        verbose_name_plural = "Движение ДС"
        ordering = ['id']

class SupplierAccount(models.Model):
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        verbose_name="Поставщик",
        related_name="supplier_accounts"
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        verbose_name="Счет",
        related_name="supplier_accounts"
    )
    balance = models.DecimalField(
        max_digits=15, 
        decimal_places=0,
        default=0,
        verbose_name="Баланс поставщика"
    )
    
    def __str__(self):
        return f"{self.supplier.name} - {self.account.name}"
    
    class Meta:
        verbose_name = "Счет поставщика"
        verbose_name_plural = "Счета поставщиков"
        unique_together = ('supplier', 'account')

class MoneyTransfer(models.Model):
    source_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        verbose_name="Счет отправителя",
        related_name="outgoing_transfers"
    )
    source_supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        verbose_name="Отправитель",
        related_name="outgoing_transfers",
        null=True,
        blank=True
    )
    
    destination_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        verbose_name="Счет получателя",
        related_name="incoming_transfers"
    )
    destination_supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        verbose_name="Получатель",
        related_name="incoming_transfers",
        null=True, 
        blank=True
    )
    
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        verbose_name="Сумма перевода"
    )
    transfer_date = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата перевода"
    )
    
    def __str__(self):
        source = f"{self.source_supplier.name} - " if self.source_supplier else ""
        source += self.source_account.name
        
        dest = f"{self.destination_supplier.name} - " if self.destination_supplier else ""
        dest += self.destination_account.name
        
        return f"Перевод {self.amount} р. от {source} к {dest}"
    
    class Meta:
        verbose_name = "Перевод средств"
        verbose_name_plural = "Переводы средств"
        ordering = ['id']

class SupplierDebtRepayment(models.Model):
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        verbose_name="Поставщик",
        related_name="debt_repayments"
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        verbose_name="Транзакция",
        related_name="debt_repayments",
        null=True,
        blank=True
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Сумма погашения"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата и время создания"
    )

    def __str__(self):
        return f"{self.supplier.name}: {self.amount} р. ({self.created_at:%d.%m.%Y %H:%M})"

    class Meta:
        verbose_name = "Погашение долга поставщика"
        verbose_name_plural = "Погашения долгов поставщиков"
        ordering = ['created_at']

class Investor(models.Model):
    name = models.CharField(max_length=255, verbose_name="Инвестор")
    balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name="Сумма"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Инвестор"
        verbose_name_plural = "Инвесторы"
        ordering = ['name']

class InvestorDebtOperation(models.Model):
    OPERATION_TYPES = [
        ("deposit", "Внесение"),
        ("withdrawal", "Забор"),
    ]

    investor = models.ForeignKey(
        Investor,
        on_delete=models.CASCADE,
        verbose_name="Инвестор",
        related_name="debt_operations"
    )
    operation_type = models.CharField(
        max_length=10,
        choices=OPERATION_TYPES,
        verbose_name="Тип операции"
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Сумма операции"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата и время создания"
    )

    def __str__(self):
        return f"{self.investor.name}: {self.get_operation_type_display()} {self.amount} р. ({self.created_at:%d.%m.%Y %H:%M})"

    class Meta:
        verbose_name = "Операция с долгом инвестора"
        verbose_name_plural = "Операции с долгами инвесторов"
        ordering = ['created_at']

class Equipment(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name="Название"
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        verbose_name="Сумма"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Оборудование"
        verbose_name_plural = "Оборудование"
        ordering = ['name']