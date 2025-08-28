from django.urls import path
from . import views

app_name = "main"

class SignedIntConverter:
    regex = '-?\d+'

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        return str(value)

from django.urls import register_converter
register_converter(SignedIntConverter, 'signed_int')

urlpatterns = [
	path("", views.index, name="index"),
	path("accounts/", views.accounts, name="accounts"),
	path("accounts/list/", views.account_list, name="account_list"),
	path('supplier-accounts/', views.supplier_accounts, name='supplier_accounts'),
	path("profit_distribution/", views.profit_distribution, name="profit_distribution"),
	path("money_transfers/", views.money_transfers, name="money_transfers"),
	path("money_transfers/collection/", views.money_transfer_collection, name="money_transfer_collection"),
	path("money_transfers/<int:pk>/", views.money_transfer_detail, name="money_transfer_detail"),
	path("money_transfers/add/", views.money_transfer_create, name="money_transfer_create"),
	path("money_transfers/edit/<int:pk>/", views.money_transfer_edit, name="money_transfer_edit"),
	path("money_transfers/delete/<int:pk>/", views.money_transfer_delete, name="money_transfer_delete"),
	path("payment_purposes/list/", views.payment_purpose_list, name="payment_purpose_list"),
    path('payment_purpose/types/', views.payment_purpose_types, name='payment_purpose_types'),
	path("cash_flow/", views.cash_flow, name="cash_flow"),
	path("cash_flow/<int:pk>/", views.cash_flow_detail, name="cash_flow_detail"),
	path("cash_flow/add/", views.cash_flow_create, name="cash_flow_create"),
	path("cash_flow/edit/<int:pk>/", views.cash_flow_edit, name="cash_flow_edit"),
	path("cash_flow/delete/<int:pk>/", views.cash_flow_delete, name="cash_flow_delete"),
	path("cash_flow/report/", views.cash_flow_report, name="cash_flow_report"),
	path("cash_flow/list/", views.cash_flow_list, name="cash_flow_list"),
	path("cash_flow/payment_stats/<int:supplier_id>/", views.cash_flow_payment_stats, name="cash_flow_payment_stats"),
	path("transactions/list/", views.transaction_list, name="transaction_list"),
	path("transactions/<int:pk>/", views.transaction_detail, name="transaction_detail"),
	path("transactions/add/", views.transaction_create, name="transaction_create"),
	path("transactions/edit/<int:pk>/", views.transaction_edit, name="transaction_edit"),
	path("transactions/payment/<int:pk>/", views.transaction_payment, name="transaction_payment"),
	path("transactions/delete/<int:pk>/", views.transaction_delete, name="transaction_delete"),
	path('transactions/modified/', views.get_modified_transactions, name='get_modified_transactions'),
    path('transactions/<int:pk>/mark-viewed/', views.mark_transaction_viewed, name='mark_transaction_viewed'),
	path('transactions/mark-all-viewed/', views.mark_all_transactions_viewed, name='mark_all_transactions_viewed'),
	path("clients/", views.clients, name="clients"),
	path("clients/list/", views.client_list, name="client_list"),
	path("clients/<int:pk>/", views.client_detail, name="client_detail"),
	path("clients/add/", views.client_create, name="client_create"),
	path("clients/edit/<int:pk>/", views.client_edit, name="client_edit"),
	path("clients/delete/<int:pk>/", views.client_delete, name="client_delete"),
	path("suppliers/", views.suppliers, name="suppliers"),
	path("suppliers/debtors/", views.debtors, name="debtors"),
	path(
		"suppliers/debtors/<str:type>/<pk>/",
		views.debtor_detail,
		name="debtor_detail"
	),
	path("suppliers/debtors/details/", views.debtor_details, name="debtor_details"),
	path("suppliers/list/", views.supplier_list, name="supplier_list"),
	path("suppliers/<int:pk>/", views.supplier_detail, name="supplier_detail"),
	path("suppliers/add/", views.supplier_create, name="supplier_create"),
	path("suppliers/edit/<int:pk>/", views.supplier_edit, name="supplier_edit"),
	path("suppliers/delete/<int:pk>/", views.supplier_delete, name="supplier_delete"),
	path("suppliers/settle-debt/<pk>/", views.settle_supplier_debt, name="settle_supplier_debt"),
    path("suppliers/repay-debt/<signed_int:pk>/", views.repay_supplier_debt, name="repay_supplier_debt"),
    path("suppliers/repay-debt/edit/<int:pk>/", views.edit_supplier_debt_repayment, name="edit_supplier_debt_repayment"),
	path("branches/list/", views.branch_list, name="branch_list"),
	path("company_balance_stats/", views.company_balance_stats, name="company_balance_stats"),
    path("company_balance_stats/by_month/", views.company_balance_stats_by_month, name="company_balance_stats_by_month"),
    path("clear_cache/", views.clear_cache_view, name="clear_cache"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/add/", views.user_create, name="user_create"),
    path("users/edit/<int:pk>/", views.user_edit, name="user_edit"),
    path("users/delete/<int:pk>/", views.user_delete, name="user_delete"),
    path("users/types/", views.user_types, name="user_types"),
    path("investors/list/", views.investor_list, name="investor_list"),
]
