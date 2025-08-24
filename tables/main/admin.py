from django.contrib import admin

from .models import (
    Transaction,
	Client,
	Supplier,
	Account,
	AccountType,
	CashFlow,
	SupplierAccount,
	PaymentPurpose,
	MoneyTransfer,
	Branch,
	SupplierDebtRepayment,
	Investor,
	InvestorDebtOperation,
	Equipment
)


admin.site.register(Transaction)
admin.site.register(Client)
admin.site.register(Supplier)
admin.site.register(Account)
admin.site.register(AccountType)
admin.site.register(CashFlow)
admin.site.register(SupplierAccount)
admin.site.register(PaymentPurpose)
admin.site.register(MoneyTransfer)
admin.site.register(Branch)
admin.site.register(SupplierDebtRepayment)
admin.site.register(Investor)
admin.site.register(InvestorDebtOperation)
admin.site.register(Equipment)