from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from tables.utils import get_model_fields
from django.db import transaction, models
from .models import Transaction, Client, Supplier, Account, CashFlow, SupplierAccount, PaymentPurpose, MoneyTransfer, Branch, SupplierDebtRepayment, Investor, InvestorDebtOperation, BalanceData, MonthlyCapital, ShortTermLiability, Credit, InventoryItem, ClientDebtRepayment
from django.http import JsonResponse
from django.forms.models import model_to_dict
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
import locale
import json
from decimal import Decimal
from django.db.models import Sum, F, ExpressionWrapper, DecimalField, Value
from collections import defaultdict
from functools import wraps
from django.core.exceptions import PermissionDenied
from datetime import datetime
from calendar import monthrange
from django.core.cache import cache
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from users.models import User, UserType, HiddenRows
import math
from django.db.models import F, ExpressionWrapper, IntegerField, Value
from django.db.models.functions import Floor
import logging
logger = logging.getLogger(__name__)

locale.setlocale(locale.LC_ALL, "ru_RU.UTF-8")
locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")


def forbid_supplier(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if hasattr(request.user, 'user_type') and getattr(request.user.user_type, 'name', None) == 'Поставщик' or getattr(request.user.user_type, 'name', None) == 'Филиал':
            from django.shortcuts import redirect
            return redirect('main:debtors')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def parse_datetime_string(dt_str):
    dt_str = dt_str.strip()
    if "T" in dt_str:
        try:
            return timezone.make_aware(datetime.strptime(dt_str, "%Y-%m-%dT%H:%M"))
        except ValueError:
            pass
    if " " in dt_str:
        try:
            return timezone.make_aware(datetime.strptime(dt_str, "%d.%m.%Y %H:%M"))
        except ValueError:
            try:
                return timezone.make_aware(datetime.strptime(dt_str, "%Y-%m-%d %H:%M"))
            except ValueError:
                pass
    if "." in dt_str:
        return timezone.make_aware(datetime.strptime(dt_str, "%d.%m.%Y"))
    elif "-" in dt_str:
        return timezone.make_aware(datetime.strptime(dt_str, "%Y-%m-%d"))
    return None


class BankAccountData:
    def __init__(self, name, balance):
        self.name = name
        self.balance = balance

def format_currency(amount: float) -> str:
    sum = locale.format_string("%.2f", amount, grouping=True)
    return sum

def clean_currency(value):
    if isinstance(value, str):
        value = value.replace(" р.", "").replace("р.", "").strip()
        value = value.replace(",", ".")
        value = value.replace(" ", "")
    return value

def clean_percentage(value):
    if isinstance(value, str):
        value = value.replace("%", "").strip()
        value = value.replace(",", ".")
        value = value.replace(" ", "")
    return value

def strip_cents(value):
    try:
        return int(Decimal(str(value or 0)))
    except Exception:
        return 0

@login_required
def index(request):
    user_type = getattr(getattr(request.user, 'user_type', None), 'name', None)
    if user_type == 'Поставщик' or user_type == 'Филиал':
        return redirect('main:debtors')

    is_accountant = user_type == 'Бухгалтер'
    is_assistant = user_type == 'Ассистент'

    fields = get_transaction_fields(is_accountant, is_assistant)

    transactions_qs = Transaction.objects.select_related('client', 'supplier').all().order_by('-created_at')
    if is_assistant:
        transactions_qs = transactions_qs.filter(supplier__visible_for_assistant=True)

    paginator = Paginator(transactions_qs, 200)
    page_number = request.GET.get('page', 1)
    page = paginator.get_page(page_number)

    changed_cells = {}
    for t in page.object_list:
        client_changed = t.client and t.client_percentage != t.client.percentage
        supplier_changed = t.supplier and t.supplier_percentage != t.supplier.cost_percentage

        if client_changed or supplier_changed:
            changed_cells[t.id] = {
                'client_percentage': client_changed,
                'supplier_percentage': supplier_changed
            }

    is_admin = user_type == 'Администратор'

    supplier_debts = [
        strip_cents(getattr(t, 'supplier_debt', 0))
        for t in page.object_list
    ]

    client_debts = [
        strip_cents(getattr(t, 'client_debt', 0))
        for t in page.object_list
    ]

    bonus_debts = [
        strip_cents(Decimal(str(t.amount or 0)) * Decimal(str(t.bonus_percentage or 0)) / Decimal('100') - Decimal(str(t.returned_bonus or 0)))
        for t in page.object_list
    ]

    investor_debts = [
        strip_cents(getattr(t, 'investor_debt', 0))
        for t in page.object_list
    ]

    context = {
        "fields": fields,
        "data": page.object_list,
        "data_ids": [t.id for t in page.object_list],
        "changed_cells": changed_cells,
        "total_pages": paginator.num_pages,
        "current_page": page.number,
        "is_admin": is_admin,
        "supplier_debts": supplier_debts,
        "debts": {
            "supplier_debts": supplier_debts,
            "client_debt": client_debts,
            "bonus_debt": bonus_debts,
            "investor_debt": investor_debts,
        },
    }

    return render(request, "main/main.html", context)

def get_transaction_fields(is_accountant, is_assistant=False):
    excluded = [
        "id", "amount", "client_percentage", "bonus_percentage",
        "supplier_percentage", "paid_amount", "modified_by_accountant",
        "viewed_by_admin", "returned_date", "returned_by_supplier", "returned_bonus", "returned_to_client", "returned_to_investor",
    ]

    field_order = [
        "created_at", "client", "supplier", "account", "amount", "client_percentage",
        "remaining_amount", "bonus_percentage", "bonus", "supplier_percentage", "profit",
        "paid_amount", "debt", "documents"
    ]

    if is_assistant:
        field_order = [
            "created_at", "client", "supplier", "account", "amount", "paid_amount", "documents"
        ]

    fields = get_model_fields(
        Transaction,
        excluded_fields=excluded,
        field_order=field_order,
    )

    insertions = [
        (4, {"name": "amount", "verbose_name": "Сумма", "is_amount": True, }),
        (5, {"name": "client_percentage", "verbose_name": "%", "is_percent": True, }),
        (6, {"name": "remaining_amount", "verbose_name": "Выдать", "is_amount": True }),
        (7, {"name": "bonus_percentage", "verbose_name": "%", "is_percent": True, }),
        (8, {"name": "bonus", "verbose_name": "Бонус", "is_amount": True}),
        (9, {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True, }),
        (10, {"name": "profit", "verbose_name": "Прибыль", "is_amount": True}),
        (11, {"name": "paid_amount", "verbose_name": "Оплачено", "is_amount": True}),
        (12, {"name": "debt", "verbose_name": "Долг", "is_amount": True}),
    ]

    if is_assistant:
        insertions = [
            (4, {"name": "amount", "verbose_name": "Сумма", "is_amount": True, }),
            (5, {"name": "paid_amount", "verbose_name": "Оплачено", "is_amount": True}),
        ]

    for pos, field in insertions:
        fields.insert(pos, field)

    return fields

@forbid_supplier
@login_required
def transaction_detail(request, pk: int):
    transaction = get_object_or_404(Transaction, id=pk)
    data = model_to_dict(transaction)
    if data.get("paid_amount", 0) == 0:
        data["paid_amount"] = data.get("amount", 0)
    return JsonResponse({"data": data})

@forbid_supplier
@login_required
def client_list(request):
    clients_data = Client.objects.values('id', 'name')
    return JsonResponse(list(clients_data), safe=False)

@forbid_supplier
@login_required
def supplier_list(request):
    suppliers_data = Supplier.objects.values('id', 'name')
    result = [
        {
            'id': s['id'],
            'name': s['name']
        }
        for s in suppliers_data
    ]
    return JsonResponse(result, safe=False)

@forbid_supplier
@login_required
def other_suppliers(request):
    suppliers_data = Supplier.objects.filter(visible_for_assistant=False).values('id', 'name')
    result = [
        {
            'id': s['id'],
            'name': s['name']
        }
        for s in suppliers_data
    ]
    return JsonResponse(result, safe=False)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def transaction_create(request):
    try:
        with transaction.atomic():
            client_id = request.POST.get("client")
            supplier_id = request.POST.get("supplier")
            amount = clean_currency(request.POST.get("amount"))
            client_percentage = clean_percentage(request.POST.get("client_percentage"))
            bonus_percentage = clean_percentage(request.POST.get("bonus_percentage", "0"))
            supplier_percentage = clean_percentage(request.POST.get("supplier_percentage"))
            account_supplier_id = request.POST.get("account")

            if not all([client_id, supplier_id, amount, account_supplier_id]):
                return JsonResponse(
                    {"status": "error", "message": "Все обязательные поля должны быть заполнены"},
                    status=400,
                )

            try:
                amount_float = float(amount)
                if amount_float <= 0:
                    return JsonResponse(
                        {"status": "error", "message": "Сумма должна быть больше нуля"},
                        status=400,
                    )
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Некорректное значение суммы"},
                    status=400,
                )

            client = get_object_or_404(Client, id=client_id)
            supplier = get_object_or_404(Supplier, id=supplier_id)
            account_supplier = get_object_or_404(Account, id=account_supplier_id)

            client_percentage = client_percentage or client.percentage
            supplier_percentage = supplier_percentage or supplier.cost_percentage

            if not bonus_percentage:
                bonus_percentage = 0

            is_accountant = request.user.user_type.name == 'Бухгалтер' if hasattr(request.user, 'user_type') else False
            is_assistant = request.user.user_type.name == 'Ассистент' if hasattr(request.user, 'user_type') else False

            trans = Transaction.objects.create(
                client=client,
                supplier=supplier,
                amount=int(float(amount)),
                client_percentage=float(client_percentage),
                bonus_percentage=float(bonus_percentage),
                supplier_percentage=float(supplier_percentage),
                modified_by_accountant=is_accountant,
                viewed_by_admin=not is_accountant,
                account=account_supplier
            )

            client_changed = trans.client and trans.client_percentage != trans.client.percentage
            supplier_changed = trans.supplier and trans.supplier_percentage != trans.supplier.cost_percentage
            changed_cells = {
                trans.id: {
                    'client_percentage': client_changed,
                    'supplier_percentage': supplier_changed
                }
            }

            def debt_value(debt, base):
                return -1 if base == 0 or base == "0" or base == 0.0 else debt

            debts = {
                "supplier_debt": debt_value(getattr(trans, "supplier_debt", 0), getattr(trans, "paid_amount", 0)),
                "client_debt": debt_value(getattr(trans, "client_debt", 0), getattr(trans, "remaining_amount", 0)),
                "bonus_debt": debt_value(getattr(trans, "bonus_debt", 0), getattr(trans, "bonus", 0)),
                "investor_debt": debt_value(getattr(trans, "investor_debt", 0), getattr(trans, "profit", 0)),
            }

            context = {
                "item": trans,
                "fields": get_transaction_fields(is_accountant, is_assistant),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": trans.id,
                "changed_cells": changed_cells,
                "debts": debts,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def transaction_edit(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID транзакции не указан"},
                    status=400,
                )

            trans = get_object_or_404(Transaction, id=pk)

            client_id = request.POST.get("client")
            supplier_id = request.POST.get("supplier")
            amount = clean_currency(request.POST.get("amount"))
            client_percentage = clean_percentage(request.POST.get("client_percentage"))
            bonus_percentage = clean_percentage(request.POST.get("bonus_percentage", "0"))
            supplier_percentage = clean_percentage(request.POST.get("supplier_percentage"))
            account_supplier_id = request.POST.get("account")

            if not all([client_id, supplier_id, amount, account_supplier_id]):
                return JsonResponse(
                    {"status": "error", "message": "Все обязательные поля должны быть заполнены"},
                    status=400,
                )

            try:
                amount_float = float(amount)
                if amount_float <= 0:
                    return JsonResponse(
                        {"status": "error", "message": "Сумма должна быть больше нуля"},
                        status=400,
                    )
                if amount_float < trans.paid_amount:
                    return JsonResponse(
                        {"status": "error", "message": "Сумма не может быть меньше уже оплаченной суммы"},
                        status=400,
                    )
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Некорректное значение суммы"},
                    status=400,
                )
            

            client = get_object_or_404(Client, id=client_id)
            supplier = get_object_or_404(Supplier, id=supplier_id)
            account_supplier = get_object_or_404(Account, id=account_supplier_id)

            new_client_percentage = Decimal(str(client_percentage or client.percentage))
            new_bonus_percentage = Decimal(str(bonus_percentage or 0))
            new_supplier_percentage = Decimal(str(supplier_percentage or supplier.cost_percentage))
            new_amount = Decimal(str(amount_float))

            new_bonus = Decimal(math.floor(float(new_amount * new_bonus_percentage / Decimal('100'))))
            if trans.returned_bonus > new_bonus:
                return JsonResponse(
                    {"status": "error", "message": "Возвращено бонуса больше, чем новый бонус по проценту. Измените процент или уменьшите возврат."},
                    status=400,
                )

            new_remaining_amount = Decimal(math.floor(float(new_amount * (Decimal('100') - new_client_percentage) / Decimal('100'))))
            if trans.returned_to_client > new_remaining_amount:
                return JsonResponse(
                    {"status": "error", "message": "Возвращено клиенту больше, чем новая сумма по проценту клиента. Измените процент или уменьшите возврат."},
                    status=400,
                )

            new_supplier_fee = Decimal(math.floor(float(new_amount * new_supplier_percentage / Decimal('100'))))
            limit = Decimal(trans.paid_amount) - new_supplier_fee
            if limit >= 0 and Decimal(trans.returned_by_supplier) > limit:
                return JsonResponse(
                    {"status": "error", "message": "Возвращено поставщику больше, чем новый долг поставщика. Измените процент или уменьшите возврат."},
                    status=400,
                )

            client_percentage = client_percentage or client.percentage
            supplier_percentage = supplier_percentage or supplier.cost_percentage

            if not bonus_percentage:
                bonus_percentage = 0

            old_account = trans.account
            old_supplier = trans.supplier
            old_paid_amount = trans.paid_amount

            account_changed = old_account.id != account_supplier.id if old_account else True
            supplier_changed = old_supplier.id != supplier.id if old_supplier else True

            if (account_changed or supplier_changed) and old_paid_amount > 0:
                if old_supplier and old_account:
                    old_supplier_account, _created = SupplierAccount.objects.get_or_create(
                        supplier=old_supplier,
                        account=old_account,
                        defaults={'balance': 0}
                    )
                    old_supplier_account.balance = Decimal(old_supplier_account.balance) - Decimal(old_paid_amount)
                    old_supplier_account.save()

                new_supplier_account, _ = SupplierAccount.objects.get_or_create(
                    supplier=supplier,
                    account=account_supplier,
                    defaults={'balance': 0}
                )
                new_supplier_account.balance = Decimal(new_supplier_account.balance) + Decimal(old_paid_amount)
                new_supplier_account.save()

            if account_changed or supplier_changed:
                cashflows = CashFlow.objects.filter(transaction=trans)
                for cf in cashflows:
                    cf.account = account_supplier
                    cf.supplier = supplier
                    cf.save()

            trans.client = client
            trans.supplier = supplier
            trans.amount = int(float(amount))
            trans.client_percentage = float(client_percentage)
            trans.bonus_percentage = float(bonus_percentage)
            trans.supplier_percentage = float(supplier_percentage)
            trans.account = account_supplier

            is_accountant = request.user.user_type.name == 'Бухгалтер' if hasattr(request.user, 'user_type') else False
            is_assistant = request.user.user_type.name == 'Ассистент' if hasattr(request.user, 'user_type') else False

            if is_accountant:
                trans.modified_by_accountant = True
                trans.viewed_by_admin = False
            trans.save()

            client_changed = trans.client and trans.client_percentage != trans.client.percentage
            supplier_changed = trans.supplier and trans.supplier_percentage != trans.supplier.cost_percentage
            changed_cells = {
                trans.id: {
                    'client_percentage': client_changed,
                    'supplier_percentage': supplier_changed
                }
            }

            def debt_value(debt, base):
                return -1 if base == 0 or base == "0" or base == 0.0 else debt

            debts = {
                "supplier_debt": debt_value(getattr(trans, "supplier_debt", 0), getattr(trans, "paid_amount", 0)),
                "client_debt": debt_value(getattr(trans, "client_debt", 0), getattr(trans, "remaining_amount", 0)),
                "bonus_debt": debt_value(getattr(trans, "bonus_debt", 0), getattr(trans, "bonus", 0)),
                "investor_debt": debt_value(getattr(trans, "investor_debt", 0), getattr(trans, "profit", 0)),
            }

            context = {
                "item": trans,
                "fields": get_transaction_fields(is_accountant, is_assistant),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": trans.id,
                "changed_cells": changed_cells,
                "debts": debts,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def transaction_payment(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID транзакции не указан"},
                    status=400,
                )

            trans = get_object_or_404(Transaction, id=pk)

            is_assistant = request.user.user_type.name == 'Ассистент' if hasattr(request.user, 'user_type') else False

            if not is_assistant:
                paid_amount = clean_currency(request.POST.get("paid_amount"))

                if paid_amount is None or paid_amount == "":
                    return JsonResponse(
                        {"status": "error", "message": "Сумма оплаты не может быть пустой"},
                        status=400,
                    )

                try:
                    amount_float = float(paid_amount)
                    if amount_float < 0:
                        return JsonResponse(
                            {"status": "error", "message": "Сумма должна быть неотрицательной"},
                            status=400,
                        )
                    if amount_float > trans.amount:
                        return JsonResponse(
                            {"status": "error", "message": "Сумма оплаты не может превышать общую сумму транзакции"},
                            status=400,
                        )
                except ValueError:
                    return JsonResponse(
                        {"status": "error", "message": "Некорректное значение суммы"},
                        status=400,
                    )
            else:
                paid_amount = trans.paid_amount

            documents = request.POST.get("documents") == "on"

            previous_paid_amount = trans.paid_amount or 0
            new_paid_amount = int(float(paid_amount))

            payment_difference = new_paid_amount - previous_paid_amount

            if payment_difference < 0 and trans.supplier:
                if not trans.account:
                    return JsonResponse(
                        {"status": "error", "message": "У транзакции не указан счет для проведения оплаты"},
                        status=400,
                    )
                account = trans.account

                supplier_account, _ = SupplierAccount.objects.get_or_create(
                    supplier=trans.supplier,
                    account=account,
                    defaults={'balance': 0}
                )

                cashflows = CashFlow.objects.filter(transaction=trans, purpose__name="Оплата").order_by('created_at')
                to_remove = abs(payment_difference)
                for cf in cashflows:
                    if to_remove <= 0:
                        break
                    cf_amount = cf.amount
                    if to_remove >= cf_amount:
                        supplier_account.balance = Decimal(supplier_account.balance) - Decimal(cf_amount)
                        supplier_account.save()
                        cf.delete()
                        to_remove -= cf_amount
                    else:
                        supplier_account.balance = Decimal(supplier_account.balance) - Decimal(to_remove)
                        supplier_account.save()
                        cf.amount = cf.amount - to_remove
                        cf.save()
                        to_remove = 0

            if payment_difference > 0 and trans.supplier:
                if not trans.account:
                    return JsonResponse(
                        {"status": "error", "message": "У транзакции не указан счет для проведения оплаты"},
                        status=400,
                    )

                account = trans.account

                supplier_account, _created = SupplierAccount.objects.get_or_create(
                    supplier=trans.supplier,
                    account=account,
                    defaults={'balance': 0}
                )
                supplier_account.balance = Decimal(supplier_account.balance) + Decimal(payment_difference)
                supplier_account.save()

                payment_purpose, _ = PaymentPurpose.objects.get_or_create(
                    name="Оплата",
                    defaults={"operation_type": PaymentPurpose.EXPENSE}
                )

                CashFlow.objects.create(
                    account=account,
                    amount=payment_difference,
                    purpose=payment_purpose,
                    supplier=trans.supplier,
                    transaction=trans,
                    created_by=request.user
                )

            if new_paid_amount == 0 and previous_paid_amount > 0 and trans.supplier and trans.account:
                account = trans.account
                supplier_account, _ = SupplierAccount.objects.get_or_create(
                    supplier=trans.supplier,
                    account=account,
                    defaults={'balance': 0}
                )
                cashflows = CashFlow.objects.filter(transaction=trans, purpose__name="Оплата")
                for cf in cashflows:
                    supplier_account.balance = Decimal(supplier_account.balance) - Decimal(cf.amount)
                    supplier_account.save()
                    cf.delete()

            trans.paid_amount = new_paid_amount
            trans.documents = documents
            is_accountant = request.user.user_type.name == 'Бухгалтер' if hasattr(request.user, 'user_type') else False
            is_assistant = request.user.user_type.name == 'Ассистент' if hasattr(request.user, 'user_type') else False

            if is_accountant:
                trans.modified_by_accountant = True
                trans.viewed_by_admin = False

            trans.save()

            client_changed = trans.client and trans.client_percentage != trans.client.percentage
            supplier_changed = trans.supplier and trans.supplier_percentage != trans.supplier.cost_percentage
            changed_cells = {
                trans.id: {
                    'client_percentage': client_changed,
                    'supplier_percentage': supplier_changed
                }
            }

            def debt_value(debt, base):
                return -1 if base == 0 or base == "0" or base == 0.0 else debt

            debts = {
                "supplier_debt": debt_value(getattr(trans, "supplier_debt", 0), getattr(trans, "paid_amount", 0)),
                "client_debt": debt_value(getattr(trans, "client_debt", 0), getattr(trans, "remaining_amount", 0)),
                "bonus_debt": debt_value(getattr(trans, "bonus_debt", 0), getattr(trans, "bonus", 0)),
                "investor_debt": debt_value(getattr(trans, "investor_debt", 0), getattr(trans, "profit", 0)),
            }

            context = {
                "item": trans,
                "fields": get_transaction_fields(is_accountant, is_assistant),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": trans.id,
                "changed_cells": changed_cells,
                "debts": debts,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def transaction_delete(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID транзакции не указан"},
                    status=400,
                )

            is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False

            if not is_admin:
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно прав для выполнения действия"},
                    status=403
                )
            trans = get_object_or_404(Transaction, id=pk)

            if trans.paid_amount > 0:
                return JsonResponse(
                    {"status": "error", "message": "Нельзя удалить транзакцию с оплатой. Сначала обнулите оплаченную сумму."},
                    status=400,
                )

            trans.delete()

            return JsonResponse(
                {
                    "status": "success",
                    "message": "Транзакция успешно удалена",
                }
            )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
def client_detail(request, pk: int):
    client = get_object_or_404(Client, id=pk)
    return JsonResponse({"data": model_to_dict(client)})

@forbid_supplier
@login_required
def supplier_detail(request, pk: int):
    supplier = get_object_or_404(Supplier, id=pk)
    data = model_to_dict(supplier)
    data["username"] = supplier.user.username if supplier.user else None
    data["account_ids"] = ",".join(str(acc.id) for acc in supplier.accounts.all())
    return JsonResponse({"data": data})

@forbid_supplier
@login_required
def get_modified_transactions(request):
    is_admin = hasattr(request.user, 'user_type') and request.user.user_type.name == 'Администратор'

    if not is_admin:
        return JsonResponse({"modified_ids": []})

    modified_ids = Transaction.objects.filter(
        modified_by_accountant=True,
        viewed_by_admin=False
    ).values_list('id', flat=True)

    return JsonResponse({"modified_ids": list(modified_ids)})

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def mark_transaction_viewed(request, pk):
    is_admin = hasattr(request.user, 'user_type') and request.user.user_type.name == 'Администратор'

    if not is_admin:
        return JsonResponse({"status": "error", "message": "Недостаточно прав"}, status=403)

    transaction = get_object_or_404(Transaction, id=pk)
    transaction.viewed_by_admin = True
    transaction.save()

    return JsonResponse({"status": "success"})

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def mark_all_transactions_viewed(request):
    try:
        data = json.loads(request.body)
        ids = data.get('ids', [])

        if not ids:
            return JsonResponse({"status": "error", "message": "Не указаны ID транзакций"}, status=400)

        is_admin = hasattr(request.user, 'user_type') and request.user.user_type.name == 'Администратор'

        if not is_admin:
            return JsonResponse({"status": "error", "message": "Недостаточно прав"}, status=403)

        with transaction.atomic():
            updated_count = Transaction.objects.filter(
                id__in=ids,
                modified_by_accountant=True,
                viewed_by_admin=False
            ).update(viewed_by_admin=True)

        return JsonResponse({
            "status": "success",
            "message": f"Отмечено транзакций: {updated_count}"
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@forbid_supplier
@login_required
def accounts(request):
    accounts = Account.objects.all().order_by("account_type")
    accounts_data = prepare_accounts_data(accounts)
    context = {
        "fields": {
            "accounts": [
                {"name": "name", "verbose_name": "Название"},
                {"name": "balance", "verbose_name": "Баланс", "is_number": True},
            ],
        },
        "data": {"accounts": accounts_data},
        "is_grouped": {"accounts-table": True},
    }
    return render(request, "main/accounts.html", context)

def prepare_accounts_data(accounts):
    data = {}
    for acc in accounts:
        acc_balance = float(acc.balance or 0)
        acc_data = BankAccountData(
            name=acc.name,
            balance=format_currency(acc_balance),
        )
        acc_type = str(acc.account_type) if acc.account_type else "Без типа"
        data.setdefault(acc_type, []).append(acc_data)
    return data

@staff_member_required
def clear_cache_view(request):
    cache.clear()
    return JsonResponse({"status": "success"})

@forbid_supplier
@login_required
def suppliers(request):
    suppliers = Supplier.objects.all()

    for supplier in suppliers:
        supplier.accounts_display = ", ".join(acc.name for acc in supplier.accounts.all().exclude(name="Наличные"))

    fields = get_supplier_fields()
    
    for field in fields:
        if field.get("name") == "accounts":
            field["name"] = "accounts_display"

    context = {
        "fields": fields,
        "data": suppliers,
        "data_ids": [t.id for t in suppliers],
    }

    return render(request, "main/suppliers.html", context)

def get_supplier_fields():
    excluded = [
        "id",
        "cost_percentage",
        "user",
        "visible_for_assistant",
        "default_account",
        "visible_in_summary"
    ]
    fields = get_model_fields(
        Supplier,
        excluded_fields=excluded,
    )

    insertions = [
        (2, {"name": "cost_percentage", "verbose_name": "%", "is_percent": True, }),
        (3, {"name": "accounts", "verbose_name": "Счета"}),
    ]

    for pos, field in insertions:
        fields.insert(pos, field)

    return fields

@forbid_supplier
@login_required
def clients(request):
    clients = Client.objects.all()
    context = {
        "fields": get_client_fields(),
        "data": clients,
        "data_ids": [t.id for t in clients],
    }

    return render(request, "main/clients.html", context)

def get_client_fields():
    excluded = [
        "id",
        "percentage",
        "bonus_percentage"
    ]
    fields = get_model_fields(
        Client,
        excluded_fields=excluded,
    )

    insertions = [
        (1, {"name": "percentage", "verbose_name": "%", "is_percent": True, }),
        (3, {"name": "bonus_percentage", "verbose_name": "%", "is_percent": True, }),
    ]

    for pos, field in insertions:
        fields.insert(pos, field)

    return fields

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def client_create(request):
    try:
        with transaction.atomic():
            name = request.POST.get("name")
            percentage = clean_percentage(request.POST.get("percentage"))
            comment = request.POST.get("comment", "")
            bonus_percentage = clean_percentage(request.POST.get("bonus_percentage", "0"))
            if not bonus_percentage:
                bonus_percentage = 0

            if not name or not percentage:
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            client = Client.objects.create(
                name=name,
                percentage=float(percentage),
                comment=comment,
                bonus_percentage=float(bonus_percentage) if bonus_percentage is not None else 0,
            )

            context = {
                "item": client,
                "fields": get_client_fields(),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": client.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def client_edit(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID клиента не указан"},
                    status=400,
                )

            client = get_object_or_404(Client, id=pk)
            name = request.POST.get("name")
            percentage = clean_percentage(request.POST.get("percentage"))
            comment = request.POST.get("comment", "")
            bonus_percentage = clean_percentage(request.POST.get("bonus_percentage", "0"))

            if not name or not percentage:
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            old_percentage = float(client.percentage)
            new_percentage = float(percentage)

            client.name = name
            client.percentage = float(percentage)
            client.comment = comment
            client.bonus_percentage = float(bonus_percentage) if bonus_percentage is not None else 0

            client.save()
            context = {
                "item": client,
                "fields": get_client_fields(),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": client.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def client_delete(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID клиента не указан"},
                    status=400,
                )

            client = get_object_or_404(Client, id=pk)

            client.delete()

            return JsonResponse({
                "status": "success",
                "message": "Клиент успешно удален",
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
def cash_flow(request):
    cash_flow = CashFlow.objects.all().order_by('-created_at')

    paginator = Paginator(cash_flow, 200)
    page_number = request.GET.get('page', 1)
    page = paginator.get_page(page_number)

    context = {
        "fields": get_cash_flow_fields(),
        "data": page.object_list,
        "data_ids": [t.id for t in page.object_list],
        "total_pages": paginator.num_pages,
        "current_page": page.number,
    }

    return render(request, "main/cash_flow.html", context)

@forbid_supplier
@login_required
def cash_flow_list(request):
    fields = get_cash_flow_fields()
    cash_flow = CashFlow.objects.all().order_by('-created_at')

    id_purpose = request.GET.get('id_purpose')
    created_at = request.GET.get('created_at')
    
    if id_purpose:
        cash_flow = cash_flow.filter(purpose_id=id_purpose)
    if created_at:
        from datetime import datetime
        from django.utils.timezone import make_aware
        try:
            if '.' in created_at and len(created_at.split('.')) == 2:
                month, year = map(int, created_at.split('.'))
                dt = make_aware(datetime(year, month, 1))
                from calendar import monthrange
                last_day = monthrange(year, month)[1]
                dt_end = make_aware(datetime(year, month, last_day, 23, 59, 59))
            elif '.' in created_at:
                dt = make_aware(datetime.strptime(created_at, "%d.%m.%Y"))
                dt_end = make_aware(datetime.strptime(created_at, "%d.%m.%Y").replace(hour=23, minute=59, second=59))
            elif '-' in created_at and len(created_at.split('-')) == 2:
                year, month = map(int, created_at.split('-'))
                dt = make_aware(datetime(year, month, 1))
                from calendar import monthrange
                last_day = monthrange(year, month)[1]
                dt_end = make_aware(datetime(year, month, last_day, 23, 59, 59))
            else:
                dt = make_aware(datetime.strptime(created_at, "%Y-%m-%d"))
                dt_end = make_aware(datetime.strptime(created_at, "%Y-%m-%d").replace(hour=23, minute=59, second=59))
            cash_flow = cash_flow.filter(created_at__range=(dt, dt_end))
        except Exception:
            cash_flow = CashFlow.objects.none()

    paginator = Paginator(cash_flow, 200)
    page_number = request.GET.get('page', 1)
    page = paginator.get_page(page_number)
    cash_flow_ids = [tr.id for tr in page.object_list]
    html = "".join(
        render_to_string(
            "components/table_row.html",
            {"item": tr, "fields": fields},
        )
        for tr in page.object_list
    )
    return JsonResponse({
        "html": html,
        "context": {
            "total_pages": paginator.num_pages,
            "current_page": page.number,
            "cash_flow_ids": cash_flow_ids,
        },
    })

@forbid_supplier
@login_required
def branch_list(request):
    branch_data = Branch.objects.values('id', 'name')
    return JsonResponse(list(branch_data), safe=False)

@forbid_supplier
@login_required
def investor_list(request):
    investor_data = Investor.objects.values('id', 'name')
    return JsonResponse(list(investor_data), safe=False)

def get_cash_flow_fields():
    excluded = [
        "id",
        "amount",
        "transaction",
        "returned_to_investor"
    ]
    fields = [
        {"name": "created_at", "verbose_name": "Дата", "is_date": True},
        {"name": "account", "verbose_name": "Счет", "is_relation": True},
        {"name": "supplier", "verbose_name": "Поставщик", "is_relation": True},
        {"name": "purpose", "verbose_name": "Назначение", "is_relation": True},
        {"name": "comment", "verbose_name": "Комментарий"},
        {"name": "created_by", "verbose_name": "Пользователь", "is_relation": True},
    ]

    insertions = [
        (3, {"name": "formatted_amount", "verbose_name": "Сумма", "is_text": True}),
    ]

    for pos, field in insertions:
        fields.insert(pos, field)

    return fields

@forbid_supplier
@login_required
def transaction_list(request):
    is_accountant = request.user.user_type.name == 'Бухгалтер' if hasattr(request.user, 'user_type') else False
    is_assistant = request.user.user_type.name == 'Ассистент' if hasattr(request.user, 'user_type') else False

    fields = get_transaction_fields(is_accountant, is_assistant)
    transactions = Transaction.objects.select_related('client', 'supplier').all().order_by('-created_at')
    paginator = Paginator(transactions, 200)
    page_number = request.GET.get('page', 1)
    page = paginator.get_page(page_number)
    changed_cells = {}
    for t in page.object_list:
        client_changed = t.client and t.client_percentage != t.client.percentage
        supplier_changed = t.supplier and t.supplier_percentage != t.supplier.cost_percentage

        if client_changed or supplier_changed:
            changed_cells[t.id] = {
                'client_percentage': client_changed,
                'supplier_percentage': supplier_changed
            }
    transaction_ids = [tr.id for tr in page.object_list]
    html = "".join(
        render_to_string(
            "components/table_row.html",
            {"item": tr, "fields": fields},
        )
        for tr in page.object_list
    )

    supplier_debts = [
        strip_cents(getattr(t, 'supplier_debt', 0))
        for t in page.object_list
    ]

    client_debts = [
        strip_cents(getattr(t, 'client_debt', 0))
        for t in page.object_list
    ]

    bonus_debts = [
        strip_cents(Decimal(str(t.amount or 0)) * Decimal(str(t.bonus_percentage or 0)) / Decimal('100') - Decimal(str(t.returned_bonus or 0)))
        for t in page.object_list
    ]

    investor_debts = [
        strip_cents(getattr(t, 'investor_debt', 0))
        for t in page.object_list
    ]

    return JsonResponse({
        "html": html,
        "context": {
            "total_pages": paginator.num_pages,
            "current_page": page.number,
            "transaction_ids": transaction_ids,
            "changed_cells": changed_cells,
            "supplier_debts": supplier_debts,
            "debts": {
                "supplier_debts": supplier_debts,
                "client_debt": client_debts,
                "bonus_debt": bonus_debts,
                "investor_debt": investor_debts,
            },
        },
    })

@forbid_supplier
@login_required
def supplier_accounts(request):
    suppliers = Supplier.objects.filter(visible_in_summary=True).order_by('name')
    bank_accounts = Account.objects.exclude(name__iexact="Наличные").order_by('name')

    class SupplierAccountRow:
        def __init__(self, supplier_name, supplier_id):
            self.supplier = supplier_name
            self.supplier_id = supplier_id

    supplier_accounts_qs = SupplierAccount.objects.select_related('supplier', 'account').all()
    balances = {}
    for sa in supplier_accounts_qs:
        balances[(sa.supplier_id, sa.account_id)] = sa.balance or 0

    rows = []
    account_totals = {account.id: 0 for account in bank_accounts}

    for supplier in suppliers:
        row = SupplierAccountRow(supplier.name, supplier.id)
        total_balance = 0
        for account in bank_accounts:
            balance = balances.get((supplier.id, account.id), 0)
            balance_float = float(balance or 0)
            setattr(row, f'account_{account.id}', format_currency(balance_float))
            account_totals[account.id] = float(account_totals[account.id]) + balance_float
            total_balance += balance_float
        setattr(row, 'total_balance', format_currency(total_balance))
        rows.append(row)

    grand_total = sum(account_totals.values())

    total_row = SupplierAccountRow("ВСЕГО", 0)
    for account in bank_accounts:
        total_val = float(account_totals.get(account.id, 0))
        setattr(total_row, f'account_{account.id}', format_currency(total_val))
    setattr(total_row, 'total_balance', format_currency(grand_total))
    rows.append(total_row)

    supplier_fields = [
        {"name": "supplier", "verbose_name": "Поставщик"}
    ]
    for account in bank_accounts:
        supplier_fields.append({
            "name": f"account_{account.id}",
            "verbose_name": account.name,
            "is_amount": True
        })
    supplier_fields.append({
        "name": "total_balance",
        "verbose_name": "Итого",
        "is_amount": True
    })

    is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False
    supplier_ids = [supplier.id for supplier in suppliers]
    account_ids = [account.id for account in bank_accounts]

    cash_account = Account.objects.filter(name__iexact="Наличные").first()
    cash_balance = float(cash_account.balance) if cash_account and cash_account.balance is not None else 0.0

    grand_total_with_cash = grand_total + cash_balance

    logs_fields = [
        {"name": "date", "verbose_name": "Дата", "is_date": True},
        {"name": "type", "verbose_name": "Тип", "is_relation": True},
        {"name": "info", "verbose_name": "Инфо"},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
        {"name": "comment", "verbose_name": "Комментарий"},
        {"name": "created_by", "verbose_name": "Создал", "is_relation": True},
    ]

    context = {
        "fields": supplier_fields,
        "data": rows,
        "is_grouped": {"accounts-table": True},
        "is_admin": is_admin,
        "supplier_ids": supplier_ids,
        "account_ids": account_ids,
        "cash_balance": format_currency(cash_balance),
        "grand_total_with_cash": format_currency(grand_total_with_cash),
        "logs_fields": logs_fields,
    }
    return render(request, "main/supplierAccount.html", context)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def supplier_create(request):
    try:
        with transaction.atomic():
            name = request.POST.get("name")
            branch_id = request.POST.get("branch")
            cost_percentage = clean_percentage(request.POST.get("cost_percentage"))
            account_ids = request.POST.get("account_ids")
            visible_for_assistant = request.POST.get("visible_for_assistant") == "on"
            visible_in_summary = request.POST.get("visible_in_summary") == "on"

            username = request.POST.get("username")
            password = request.POST.get("password")

            if not all([name, branch_id, cost_percentage, account_ids]) or not branch_id or branch_id == 'null':
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            branch = get_object_or_404(Branch, id=branch_id)

            supplier = Supplier.objects.create(
                name=name,
                branch=branch,
                cost_percentage=float(cost_percentage),
                visible_for_assistant=visible_for_assistant,
                visible_in_summary=visible_in_summary,
            )

            supplier.accounts.set(Account.objects.filter(id__in=[int(x) for x in account_ids.split(',') if x.strip()]))

            if username and password:
                from users.models import User, UserType
                if User.objects.filter(username=username).exists():
                    return JsonResponse(
                        {"status": "error", "message": "Пользователь с таким именем уже существует"},
                        status=400,
                    )
                supplier_type = UserType.objects.filter(name="Поставщик").first()
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    user_type=supplier_type
                )
                supplier.user = user
                supplier.save()

            supplier.accounts_display = ", ".join(acc.name for acc in supplier.accounts.all().exclude(name="Наличные"))

            fields = get_supplier_fields()
            
            for field in fields:
                if field.get("name") == "accounts":
                    field["name"] = "accounts_display"

            context = {
                "item": supplier,
                "fields": fields,
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": supplier.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def supplier_edit(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk or pk == 'null':
                return JsonResponse(
                    {"status": "error", "message": "ID поставщика не указан"},
                    status=400,
                )

            supplier = get_object_or_404(Supplier, id=pk)
            name = request.POST.get("name")
            branch_id = request.POST.get("branch")
            cost_percentage = clean_percentage(request.POST.get("cost_percentage"))
            account_ids = request.POST.get("account_ids")
            visible_for_assistant = request.POST.get("visible_for_assistant") == "on"
            visible_in_summary = request.POST.get("visible_in_summary") == "on"

            username = request.POST.get("username")
            password = request.POST.get("password")
            
            if not all([name, branch_id, cost_percentage, account_ids]) or not branch_id or branch_id == 'null':
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            branch = get_object_or_404(Branch, id=branch_id)

            old_account_ids = set(str(acc.id) for acc in supplier.accounts.all())
            new_account_ids = set([x for x in account_ids.split(',') if x.strip()])

            removed_account_ids = old_account_ids - new_account_ids
            if removed_account_ids:
                for acc_id in removed_account_ids:
                    supplier_account = SupplierAccount.objects.filter(supplier=supplier, account_id=acc_id).first()
                    if supplier_account and float(supplier_account.balance or 0) != 0.0:
                        account_obj = Account.objects.get(id=acc_id)
                        return JsonResponse(
                            {"status": "error", "message": f"На счете '{account_obj.name}' есть остаток. Переведите баланс перед редактированием."},
                            status=400,
                        )

            old_cost_percentage = float(supplier.cost_percentage)
            new_cost_percentage = float(cost_percentage)

            supplier.name = name
            supplier.branch = branch
            supplier.cost_percentage = float(cost_percentage)
            supplier.visible_for_assistant = visible_for_assistant
            supplier.visible_in_summary = visible_in_summary
            supplier.accounts.set(Account.objects.filter(id__in=[int(x) for x in account_ids.split(',') if x.strip()]))

            from users.models import User, UserType
            supplier_type = UserType.objects.filter(name="Поставщик").first()

            if supplier.user:
                user = supplier.user
                if username:
                    if User.objects.exclude(pk=user.pk).filter(username=username).exists():
                        return JsonResponse(
                            {"status": "error", "message": "Пользователь с таким логином уже существует"},
                            status=400,
                        )
                    user.username = username
                if password:
                    user.set_password(password)
                user.user_type = supplier_type
                user.save()
            elif username and password:
                if User.objects.filter(username=username).exists():
                    return JsonResponse(
                        {"status": "error", "message": "Пользователь с таким логином уже существует"},
                        status=400,
                    )
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    user_type=supplier_type
                )
                supplier.user = user

            supplier.save()

            supplier.accounts_display = ", ".join(acc.name for acc in supplier.accounts.all().exclude(name="Наличные"))

            fields = get_supplier_fields()
            
            for field in fields:
                if field.get("name") == "accounts":
                    field["name"] = "accounts_display"

            context = {
                "item": supplier,
                "fields": fields,
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": supplier.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def supplier_delete(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID поставщика не указан"},
                    status=400,
                )

            supplier = get_object_or_404(Supplier, id=pk)

            supplier_accounts = SupplierAccount.objects.filter(supplier=supplier)
            for sa in supplier_accounts:
                if float(sa.balance or 0) != 0.0:
                    account_obj = sa.account
                    return JsonResponse(
                        {"status": "error", "message": f"На счете '{account_obj.name}' есть остаток. Переведите баланс перед удалением поставщика."},
                        status=400,
                    )

            if supplier.user:
                supplier.user.delete()

            supplier.delete()

            return JsonResponse({
                "status": "success",
                "message": "Поставщик успешно удален",
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
def cash_flow_detail(request, pk: int):
    cashflow = get_object_or_404(CashFlow, id=pk)
    data = model_to_dict(cashflow)

    data['operation_type'] = cashflow.operation_type
    data['formatted_amount'] = cashflow.formatted_amount

    data['created_at_formatted'] = timezone.localtime(cashflow.created_at).strftime('%Y-%m-%dT%H:%M') if cashflow.created_at else ""

    return JsonResponse({"data": data})

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def cash_flow_create(request):
    try:
        with transaction.atomic():
            user = request.user

            # Получение данных из запроса
            amount = clean_currency(request.POST.get("amount"))
            purpose_id = request.POST.get("purpose")
            supplier_id = request.POST.get("supplier")
            account_id = request.POST.get("account")
            comment = request.POST.get("comment", "")

            # Проверка обязательных полей
            if not all([amount, purpose_id, (supplier_id or account_id == "0")]):
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            # Проверка корректности суммы
            try:
                amount_value = Decimal(amount)
                if amount_value <= 0:
                    return JsonResponse(
                        {"status": "error", "message": "Сумма должна быть больше нуля"},
                        status=400,
                    )
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Некорректное значение суммы"},
                    status=400,
                )

            # Получение цели платежа
            purpose = get_object_or_404(PaymentPurpose, id=purpose_id)

            # Определение счета и поставщика
            if account_id == "0":
                cash_account = Account.objects.filter(name__iexact="Наличные").first()
                if not cash_account:
                    return JsonResponse(
                        {"status": "error", "message": 'Счет "Наличные" не найден'},
                        status=400,
                    )
                account = cash_account
                supplier = None
            else:
                account = get_object_or_404(Account, id=account_id)
                supplier = get_object_or_404(Supplier, id=supplier_id) if supplier_id else None

            # Логика для ДТ
            if purpose.name == "ДТ":
                amount_value_decimal = Decimal(abs(amount_value))
                if amount_value_decimal == 0:
                    raise Exception("Сумма должна быть больше нуля")

                # Поиск транзакций
                dt_transactions = (
                    Transaction.objects
                    .filter(client__name="ДТ")
                    .annotate(
                        client_debt_paid_calc=ExpressionWrapper(
                            Floor(F("paid_amount") * (100 - F("client_percentage")) / 100) - F("returned_to_client"),
                            output_field=IntegerField()
                        )
                    )
                    .order_by("created_at")
                )

                # Фильтрация транзакций
                positive_debts = dt_transactions.filter(client_debt_paid_calc__gt=0)
                negative_debts = dt_transactions.filter(client_debt_paid_calc__lt=0)
                zero_debt = (
                    Transaction.objects
                    .filter(client__name="ДТ")
                    .annotate(
                        client_debt_paid_calc=ExpressionWrapper(
                            Floor(F("paid_amount") * (100 - F("client_percentage")) / 100) - F("returned_to_client"),
                            output_field=IntegerField()
                        )
                    )
                    .filter(client_debt_paid_calc=0)
                    .first()
                )

                remaining = amount_value_decimal
                repayments = []
                appended_comment = (comment + ". " if comment else "") + f"Выдача клиенту ДТ"

                # Погашение положительных долгов
                for trans in positive_debts:
                    if remaining <= 0:
                        break
                    debt = trans.client_debt_paid_calc
                    repay_amount = min(debt, remaining)

                    # Списание средств
                    if supplier:
                        supplier_account_obj, _ = SupplierAccount.objects.select_for_update().get_or_create(
                            supplier=supplier,
                            account=account,
                            defaults={'balance': Decimal('0')}
                        )
                        if Decimal(str(supplier_account_obj.balance or 0)) < repay_amount:
                            raise Exception(f"Недостаточно средств на счете поставщика '{supplier.name}' / '{account.name}'")
                        supplier_account_obj.balance = Decimal(supplier_account_obj.balance or 0) - repay_amount
                        supplier_account_obj.save()
                    else:
                        account_db = Account.objects.select_for_update().get(id=account.id)
                        if Decimal(str(account_db.balance or 0)) < repay_amount:
                            raise Exception(f"Недостаточно средств на счете '{account_db.name}'")
                        Account.objects.filter(id=account.id).update(balance=F('balance') - repay_amount)
                        account.refresh_from_db(fields=['balance'])

                    # Обновление долга
                    trans.returned_to_client = Decimal(str(trans.returned_to_client or 0)) + repay_amount
                    trans.save()

                    repayments.append(ClientDebtRepayment(
                        client=trans.client,
                        amount=repay_amount,
                        comment=appended_comment,
                        created_by=request.user,
                        transaction=trans
                    ))

                    remaining -= repay_amount

                # Если осталась сумма, добавляем к отрицательным долгам или долгу 0
                if remaining > 0:
                    target_trans = negative_debts.first() or zero_debt
                    if target_trans:
                        debt = target_trans.client_debt_paid_calc
                        repay_amount = remaining

                        # Списание средств
                        if supplier:
                            supplier_account_obj, _ = SupplierAccount.objects.select_for_update().get_or_create(
                                supplier=supplier,
                                account=account,
                                defaults={'balance': Decimal('0')}
                            )
                            if Decimal(str(supplier_account_obj.balance or 0)) < repay_amount:
                                raise Exception(f"Недостаточно средств на счете поставщика '{supplier.name}' / '{account.name}'")
                            supplier_account_obj.balance = Decimal(supplier_account_obj.balance or 0) - repay_amount
                            supplier_account_obj.save()
                        else:
                            account_db = Account.objects.select_for_update().get(id=account.id)
                            if Decimal(str(account_db.balance or 0)) < repay_amount:
                                raise Exception(f"Недостаточно средств на счете '{account_db.name}'")
                            Account.objects.filter(id=account.id).update(balance=F('balance') - repay_amount)
                            account.refresh_from_db(fields=['balance'])

                        # Обновление долга
                        target_trans.returned_to_client = Decimal(str(target_trans.returned_to_client or 0)) + repay_amount
                        target_trans.save()

                        repayments.append(ClientDebtRepayment(
                            client=target_trans.client,
                            amount=repay_amount,
                            comment=appended_comment,
                            created_by=request.user,
                            transaction=target_trans
                        ))

                        remaining = 0

                # Создание записи CashFlow
                repay_purpose, _ = PaymentPurpose.objects.get_or_create(
                    name="ДТ",
                    defaults={"operation_type": PaymentPurpose.EXPENSE}
                )

                cashflow = CashFlow.objects.create(
                    account=account,
                    supplier=supplier if supplier else None,
                    amount=-amount_value_decimal,
                    purpose=repay_purpose,
                    comment=appended_comment,
                    created_by=request.user,
                    created_at=timezone.now()
                )

                for repayment in repayments:
                    repayment.cash_flow = cashflow
                    repayment.save()

            # Обработка других целей
            else:
                if purpose.operation_type == PaymentPurpose.EXPENSE:
                    amount_value = -abs(amount_value)
                elif purpose.operation_type == PaymentPurpose.INCOME:
                    amount_value = abs(amount_value)

                # Обновление балансов для других целей
                if purpose.operation_type == PaymentPurpose.EXPENSE:
                    amount_to_deduct = abs(amount_value)
                    if supplier:
                        supplier_account_obj, _ = SupplierAccount.objects.select_for_update().get_or_create(
                            supplier=supplier,
                            account=account,
                            defaults={'balance': Decimal('0')}
                        )
                        if Decimal(str(supplier_account_obj.balance or 0)) < amount_to_deduct:
                            raise Exception(f"Недостаточно средств на счете поставщика '{supplier.name}' / '{account.name}'")
                        supplier_account_obj.balance = Decimal(supplier_account_obj.balance or 0) - amount_to_deduct
                        supplier_account_obj.save()
                    else:
                        account_db = Account.objects.select_for_update().get(id=account.id)
                        if Decimal(str(account_db.balance or 0)) < amount_to_deduct:
                            raise Exception(f"Недостаточно средств на счете '{account_db.name}'")
                        Account.objects.filter(id=account.id).update(balance=F('balance') - amount_to_deduct)
                        account.refresh_from_db(fields=['balance'])
                elif purpose.operation_type == PaymentPurpose.INCOME:
                    amount_to_add = amount_value
                    if supplier:
                        supplier_account_obj, _ = SupplierAccount.objects.select_for_update().get_or_create(
                            supplier=supplier,
                            account=account,
                            defaults={'balance': Decimal('0')}
                        )
                        supplier_account_obj.balance = Decimal(supplier_account_obj.balance or 0) + amount_to_add
                        supplier_account_obj.save()
                    else:
                        Account.objects.filter(id=account.id).update(balance=F('balance') + amount_to_add)
                        account.refresh_from_db(fields=['balance'])

                cashflow = CashFlow.objects.create(
                    account=account,
                    amount=amount_value,
                    purpose=purpose,
                    supplier=supplier,
                    comment=comment,
                    created_by=user,
                )

            if not cashflow:
                raise Exception("Ошибка при создании записи движения денежных средств")

            context = {
                "item": cashflow,
                "fields": get_cash_flow_fields()
            }

            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": cashflow.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
def cash_flow_edit(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID операции не указан"},
                    status=400,
                )

            cashflow = get_object_or_404(CashFlow, id=pk)

            new_supplier_id = request.POST.get("supplier")
            new_amount = clean_currency(request.POST.get("amount"))
            new_purpose_id = request.POST.get("purpose")
            new_account_id = request.POST.get("account")
            comment = request.POST.get("comment", "")
            created_at_str = request.POST.get("created_at_formatted", "")

            user = request.user

            if not all([new_amount, new_purpose_id, (new_supplier_id not in (None, "", "null") or new_account_id == "0")]):
                return JsonResponse({
                    "status": "error",
                    "message": "Все поля обязательны для заполнения",
                }, status=400)

            try:
                new_amount_value = Decimal(new_amount)
                if new_amount_value <= 0:
                    return JsonResponse({
                        "status": "error",
                        "message": "Сумма должна быть больше нуля",
                    }, status=400)
                if cashflow.transaction:
                    if new_amount_value > Decimal(cashflow.transaction.amount):
                        return JsonResponse({
                            "status": "error",
                            "message": "Сумма не может превышать общую сумму транзакции",
                        }, status=400)
            except Exception:
                return JsonResponse({
                    "status": "error",
                    "message": "Некорректная сумма",
                }, status=400)

            old_account_id = cashflow.account_id
            old_supplier_id = cashflow.supplier_id if cashflow.supplier else None
            old_amount = Decimal(cashflow.amount or 0)
            old_purpose_id = cashflow.purpose_id

            if new_account_id == "0":
                cash_account = Account.objects.filter(name__iexact="Наличные").first()
                if not cash_account:
                    return JsonResponse(
                        {"status": "error", "message": 'Счет "Наличные" не найден'},
                        status=400,
                    )
                new_account = cash_account
                new_supplier = None
            else:
                if new_account_id in (None, "", "null"):
                    return JsonResponse({"status": "error", "message": "Счет не указан"}, status=400)
                new_account = get_object_or_404(Account, id=new_account_id)
                if new_supplier_id in (None, "", "null"):
                    new_supplier = None
                else:
                    new_supplier = get_object_or_404(Supplier, id=new_supplier_id)

            new_purpose = get_object_or_404(PaymentPurpose, id=new_purpose_id)

            if (cashflow.purpose.name == "Перевод") != (new_purpose.name == "Перевод"):
                return JsonResponse({
                    "status": "error",
                    "message": "Нельзя изменять тип операции на 'Перевод' или с 'Перевод'",
                }, status=400)

            if cashflow.purpose.operation_type == PaymentPurpose.INCOME and old_purpose_id != int(new_purpose_id):
                return JsonResponse({
                    "status": "error",
                    "message": "Нельзя изменить цель у прихода",
                }, status=400)
            if new_purpose.operation_type != PaymentPurpose.EXPENSE and cashflow.purpose.operation_type == PaymentPurpose.EXPENSE:
                return JsonResponse({
                    "status": "error",
                    "message": "Цель должна быть с типом 'расход'",
                }, status=400)

            is_transfer = cashflow.purpose.name == "Перевод"
            pair_cashflow = None
            if is_transfer:
                from datetime import timedelta
                if cashflow.amount < 0:
                    pair_comment_part = f"Получено от {cashflow.supplier.name if cashflow.supplier else ''} со счета {cashflow.account.name}"
                    pair = CashFlow.objects.filter(
                        purpose__name="Перевод",
                        amount__gt=0,
                        comment__icontains=pair_comment_part,
                        created_at__range=(cashflow.created_at - timedelta(seconds=10), cashflow.created_at + timedelta(seconds=10))
                    ).exclude(id=cashflow.id).first()
                else:
                    pair_comment_part = f"Перевод {cashflow.supplier.name if cashflow.supplier else ''} на счет {cashflow.account.name}"
                    pair = CashFlow.objects.filter(
                        purpose__name="Перевод",
                        amount__lt=0,
                        comment__icontains=pair_comment_part,
                        created_at__range=(cashflow.created_at - timedelta(seconds=10), cashflow.created_at + timedelta(seconds=10))
                    ).exclude(id=cashflow.id).first()
                
                if not pair:
                    mt = MoneyTransfer.objects.filter(
                        created_at__range=(cashflow.created_at - timedelta(seconds=10), cashflow.created_at + timedelta(seconds=10))
                    ).first()
                    if not mt:
                        abs_amount = abs(cashflow.amount)
                        if cashflow.amount < 0:
                            mt = MoneyTransfer.objects.filter(
                                source_account=cashflow.account,
                                source_supplier=cashflow.supplier,
                                amount=abs_amount
                            ).first()
                        else:
                            mt = MoneyTransfer.objects.filter(
                                destination_account=cashflow.account,
                                destination_supplier=cashflow.supplier,
                                amount=abs_amount
                            ).first()
                    
                    if mt:
                        transfer_purpose = PaymentPurpose.objects.filter(name="Перевод").first()
                        if transfer_purpose:
                            if cashflow.amount < 0:
                                pair = CashFlow.objects.filter(
                                    account=mt.destination_account,
                                    supplier=mt.destination_supplier,
                                    purpose=transfer_purpose,
                                    created_at__range=(mt.created_at - timedelta(seconds=10), mt.created_at + timedelta(seconds=10))
                                ).exclude(id=cashflow.id).first()
                            else:
                                pair = CashFlow.objects.filter(
                                    account=mt.source_account,
                                    supplier=mt.source_supplier,
                                    purpose=transfer_purpose,
                                    created_at__range=(mt.created_at - timedelta(seconds=10), mt.created_at + timedelta(seconds=10))
                                ).exclude(id=cashflow.id).first()
                
                pair_cashflow = pair

            if is_transfer:
                if cashflow.amount < 0:
                    updated_amount = -abs(new_amount_value)
                    pair_updated_amount = abs(new_amount_value)
                else:
                    updated_amount = abs(new_amount_value)
                    pair_updated_amount = -abs(new_amount_value)
            else:
                updated_amount = -abs(new_amount_value) if new_purpose.operation_type == PaymentPurpose.EXPENSE else abs(new_amount_value)

            old_account = get_object_or_404(Account, id=old_account_id)
            if old_supplier_id:
                old_supplier = get_object_or_404(Supplier, id=old_supplier_id)
                old_supplier_account = SupplierAccount.objects.filter(
                    supplier=old_supplier,
                    account=old_account
                ).first()
                if old_supplier_account:
                    old_supplier_account.balance = Decimal(old_supplier_account.balance or 0) - Decimal(old_amount)
                    old_supplier_account.save()
                else:
                    old_account.balance = F('balance') - old_amount
                    old_account.save(update_fields=['balance'])
                    old_account.refresh_from_db(fields=['balance'])
            else:
                old_account.balance = F('balance') - old_amount
                old_account.save(update_fields=['balance'])
                old_account.refresh_from_db(fields=['balance'])

            if pair_cashflow:
                old_pair_account = pair_cashflow.account
                old_pair_supplier = pair_cashflow.supplier
                old_pair_amount = Decimal(pair_cashflow.amount or 0)
                if old_pair_supplier:
                    old_pair_supplier_account = SupplierAccount.objects.filter(
                        supplier=old_pair_supplier,
                        account=old_pair_account
                    ).first()
                    if old_pair_supplier_account:
                        old_pair_supplier_account.balance = Decimal(old_pair_supplier_account.balance or 0) - Decimal(old_pair_amount)
                        old_pair_supplier_account.save()
                    else:
                        old_pair_account.balance = F('balance') - old_pair_amount
                        old_pair_account.save(update_fields=['balance'])
                        old_pair_account.refresh_from_db(fields=['balance'])
                else:
                    old_pair_account.balance = F('balance') - old_pair_amount
                    old_pair_account.save(update_fields=['balance'])
                    old_pair_account.refresh_from_db(fields=['balance'])

            if new_supplier:
                new_supplier_account, _ = SupplierAccount.objects.get_or_create(
                    supplier=new_supplier,
                    account=new_account,
                    defaults={'balance': 0}
                )
                new_supplier_account.balance = Decimal(new_supplier_account.balance or 0) + Decimal(updated_amount)
                new_supplier_account.save()
            else:
                new_account.balance = F('balance') + updated_amount
                new_account.save(update_fields=['balance'])
                new_account.refresh_from_db(fields=['balance'])

            if pair_cashflow:
                if pair_cashflow.supplier:
                    pair_supplier_account = SupplierAccount.objects.filter(
                        supplier=pair_cashflow.supplier,
                        account=pair_cashflow.account
                    ).first()
                    if pair_supplier_account:
                        pair_supplier_account.balance = Decimal(pair_supplier_account.balance or 0) + Decimal(pair_updated_amount)
                        pair_supplier_account.save()
                    else:
                        pair_cashflow.account.balance = F('balance') + pair_updated_amount
                        pair_cashflow.account.save(update_fields=['balance'])
                        pair_cashflow.account.refresh_from_db(fields=['balance'])
                else:
                    pair_cashflow.account.balance = F('balance') + pair_updated_amount
                    pair_cashflow.account.save(update_fields=['balance'])
                    pair_cashflow.account.refresh_from_db(fields=['balance'])

                if cashflow.amount < 0:
                    pair_cashflow.comment = f"Получено от {new_supplier.name if new_supplier else ''} со счета {new_account.name}"
                else:
                    pair_cashflow.comment = f"Перевод {new_supplier.name if new_supplier else ''} на счет {new_account.name}"
                pair_cashflow.amount = int(pair_updated_amount)
                pair_cashflow.save()

                from datetime import timedelta
                mt = MoneyTransfer.objects.filter(
                    created_at__range=(cashflow.created_at - timedelta(seconds=10), cashflow.created_at + timedelta(seconds=10))
                ).first()
                if mt:
                    if cashflow.amount < 0:
                        mt.source_account = new_account
                        mt.source_supplier = new_supplier
                        mt.destination_account = pair_cashflow.account
                        mt.destination_supplier = pair_cashflow.supplier
                    else:
                        mt.destination_account = new_account
                        mt.destination_supplier = new_supplier
                        mt.source_account = pair_cashflow.account
                        mt.source_supplier = pair_cashflow.supplier
                    mt.amount = abs(new_amount_value)
                    mt.save()

            if cashflow.purpose.name == "Оплата" and cashflow.transaction:
                transaction_obj = cashflow.transaction
                transaction_obj.paid_amount = int(transaction_obj.paid_amount or 0) - int(old_amount) + int(updated_amount)
                transaction_obj.save()

            cashflow.account = new_account
            cashflow.supplier = new_supplier
            cashflow.amount = int(updated_amount)
            cashflow.purpose = new_purpose
            cashflow.created_at = parse_datetime_string(created_at_str) if created_at_str else cashflow.created_at
            cashflow.created_by = user
            cashflow.comment = comment
            cashflow.save()

            if pair_cashflow:
                pair_cashflow.amount = int(pair_updated_amount)
                pair_cashflow.save()

            cashflow.refresh_from_db()

            context = {
                "item": cashflow,
                "fields": get_cash_flow_fields()
            }

            response_data = {
                "html": render_to_string("components/table_row.html", context),
                "id": cashflow.id,
                "status": "success",
                "message": "Движение средств успешно обновлено"
            }

            if pair_cashflow:
                pair_context = {
                    "item": pair_cashflow,
                    "fields": get_cash_flow_fields()
                }
                response_data["pair_html"] = render_to_string("components/table_row.html", pair_context)
                response_data["pair_id"] = pair_cashflow.id

            return JsonResponse(response_data)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
def cash_flow_delete(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID транзакции не указан"},
                    status=400,
                )

            cashflow = get_object_or_404(CashFlow, id=pk)
            account = cashflow.account
            supplier = cashflow.supplier
            amount = Decimal(cashflow.amount or 0)
            purpose = cashflow.purpose
            transaction_obj = cashflow.transaction

            is_payment = purpose and purpose.name == "Оплата"

            pair_id = None
            is_transfer = purpose and purpose.name == "Перевод"
            pair = None
            mt = None
            if is_transfer:
                from datetime import timedelta
                mt = MoneyTransfer.objects.filter(
                    created_at__range=(cashflow.created_at - timedelta(seconds=10), cashflow.created_at + timedelta(seconds=10))
                ).first()
                if not mt:
                    abs_amount = abs(cashflow.amount)
                    if cashflow.amount < 0:
                        mt = MoneyTransfer.objects.filter(
                            source_account=cashflow.account,
                            source_supplier=cashflow.supplier,
                            amount=abs_amount
                        ).first()
                    else:
                        mt = MoneyTransfer.objects.filter(
                            destination_account=cashflow.account,
                            destination_supplier=cashflow.supplier,
                            amount=abs_amount
                        ).first()
                
                if mt:
                    transfer_purpose = PaymentPurpose.objects.filter(name="Перевод").first()
                    if transfer_purpose:
                        pair_cashflows = CashFlow.objects.filter(
                            account__in=[mt.source_account, mt.destination_account],
                            supplier__in=[mt.source_supplier, mt.destination_supplier] if mt.source_supplier and mt.destination_supplier else [mt.source_supplier or mt.destination_supplier],
                            purpose=transfer_purpose,
                            created_at__range=(mt.created_at - timedelta(seconds=10), mt.created_at + timedelta(seconds=10))
                        ).exclude(id=cashflow.id)
                        pair_ids = list(pair_cashflows.values_list('id', flat=True))
                        pair_cashflows.delete()
                        pair_id = pair_ids[0] if pair_ids else None 
                    mt.delete()

            if supplier:
                try:
                    supplier_account = SupplierAccount.objects.get(
                        supplier=supplier,
                        account=account
                    )
                    supplier_account.balance = Decimal(supplier_account.balance or 0) - amount
                    supplier_account.save()
                except SupplierAccount.DoesNotExist:
                    account.balance = F('balance') - amount
                    account.save(update_fields=['balance'])
                    account.refresh_from_db(fields=['balance'])
            else:
                account.balance = F('balance') - amount
                account.save(update_fields=['balance'])
                account.refresh_from_db(fields=['balance'])

            if is_payment and transaction_obj is not None:
                payment_amount = abs(int(amount))
                if transaction_obj.paid_amount >= payment_amount:
                    transaction_obj.paid_amount -= payment_amount
                    transaction_obj.save()

            cashflow.delete()

            return JsonResponse({
                "status": "success",
                "message": f"Транзакция успешно удалена",
                "pair_id": pair_id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)



@forbid_supplier
@login_required
def account_list(request):
    supplier_id = request.GET.get('supplier_id')
    is_collection = request.GET.get('is_collection') == 'true'
    include_cash = request.GET.get('include_cash') == 'true'  

    accounts = Account.objects.all()
    
    if supplier_id and is_collection:
        try:
            supplier = Supplier.objects.get(id=supplier_id)
            accounts = supplier.accounts.filter(account_type__name="Банковская карта")
        except Supplier.DoesNotExist:
            accounts = Account.objects.none()
    elif supplier_id:
        try:
            supplier = Supplier.objects.get(id=supplier_id)
            accounts = supplier.accounts.all()
        except Supplier.DoesNotExist:
            accounts = Account.objects.none()
    elif is_collection:
        accounts = accounts.filter(account_type__name="Банковская карта")

    accounts = accounts.exclude(name="Наличные")

    cash_account = Account.objects.filter(name__iexact="Наличные").first()
    account_data = [
        {"id": acc.id, "name": acc.name} for acc in accounts.exclude(name="Наличные")
    ]

    if include_cash and cash_account:
        account_data.append({"id": cash_account.id, "name": cash_account.name})

    return JsonResponse(account_data, safe=False)


@forbid_supplier
@login_required
def payment_purpose_list(request):
    show_all = request.GET.get("all") == "True" or request.GET.get("all") == "true"
    if show_all:
        payment_purpose_data = [
            {"id": acc.id, "name": acc.name}
            for acc in PaymentPurpose.objects.all().order_by('operation_type', 'name')
        ]
    else:
        payment_purpose_data = [
            {"id": acc.id, "name": acc.name}
            for acc in PaymentPurpose.objects.all().exclude(name="Оплата").exclude(name="Перевод").exclude(name="Инкассация").exclude(name="Погашение долга поставщика").exclude(name="Забор инвестора").exclude(name="Внесение инвестора").order_by('operation_type', 'name')
        ]
    return JsonResponse(payment_purpose_data, safe=False)


@forbid_supplier
@login_required
def payment_purpose_types(request):
    types = (
        PaymentPurpose.objects
        .all()
        .exclude(name="Оплата")
        .exclude(name="Перевод")
        .exclude(name="Инкассация")
        .exclude(name="Погашение долга поставщика")
        .order_by('operation_type', 'name')
        .values('id', 'operation_type')
    )
    seen = set()
    ordered_types = []
    for t in types:
        key = (t['id'], t['operation_type'])
        if key not in seen:
            seen.add(key)
            ordered_types.append({'id': t['id'], 'operation_type': t['operation_type']})
    return JsonResponse(ordered_types, safe=False)


@forbid_supplier
@login_required
def cash_flow_report(request):
    from datetime import datetime

    current_year = datetime.now().year

    purposes = PaymentPurpose.objects.all().order_by('operation_type', 'name')

    MONTHS_RU = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"
    ]
    months = [
        {"num": i, "name": MONTHS_RU[i-1]}
        for i in range(1, 13)
    ]

    class ReportRow:
        def __init__(self, purpose_name, purpose_id, operation_type=None, is_total=False):
            self.purpose = purpose_name
            self.purpose_id = purpose_id
            self.operation_type = operation_type
            self.is_total = is_total
            self.total = 0

            for month in months:
                setattr(self, f"month_{month['num']}", 0)

    cash_flows = CashFlow.objects.filter(
        created_at__year=current_year
    ).select_related('purpose')

    rows_dict = {purpose.id: ReportRow(purpose.name, purpose.id, purpose.operation_type) for purpose in purposes}

    for cf in cash_flows:
        month_num = cf.created_at.month
        purpose_id = cf.purpose_id

        if purpose_id in rows_dict:
            current_value = getattr(rows_dict[purpose_id], f"month_{month_num}")
            setattr(rows_dict[purpose_id], f"month_{month_num}", current_value + cf.amount)

            rows_dict[purpose_id].total += cf.amount

    rows = list(rows_dict.values())

    rows.sort(key=lambda x: (x.operation_type != PaymentPurpose.INCOME, x.purpose))

    total_row = ReportRow("ИТОГО", 0, None, True)

    for row in rows:
        for month in months:
            month_attr = f"month_{month['num']}"
            total_month_value = getattr(total_row, month_attr)
            row_month_value = getattr(row, month_attr)

            setattr(total_row, month_attr, total_month_value + row_month_value)

        total_row.total += row.total

    rows.append(total_row)

    def format_amount_for_display(amount):
        sign = "-" if amount < 0 else ""
        formatted = locale.format_string("%.0f", abs(amount), grouping=True)
        return f"{sign}{formatted} р."

    for row in rows:
        for month in months:
            month_attr = f"month_{month['num']}"
            month_value = getattr(row, month_attr)
            setattr(row, month_attr, format_amount_for_display(month_value))

        row.total = format_amount_for_display(row.total)

    fields = [
        {"name": "purpose", "verbose_name": "Назначение платежа"}
    ]

    for month in months:
        fields.append({
            "name": f"month_{month['num']}",
            "verbose_name": month['name'],
            "is_text": True
        })

    fields.append({
        "name": "total",
        "verbose_name": "Итого",
        "is_text": True
    })

    context = {
        "fields": fields,
        "data": rows,
        "year": current_year,
        "data_ids": [row.purpose_id for row in rows],
    }

    return render(request, "main/cash_flow_report.html", context)


@forbid_supplier
@login_required
@require_http_methods(["POST"])
def money_transfer_collection(request):
    try:
        with transaction.atomic():
            source_supplier_id = request.POST.get("supplier")
            source_account_id = request.POST.get("account")
            amount = clean_currency(request.POST.get("amount"))
            
            if not all([source_supplier_id, source_account_id, amount]):
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            try:
                amount_value = int(float(amount))
                if amount_value <= 0:
                    return JsonResponse(
                        {"status": "error", "message": "Сумма должна быть больше нуля"},
                        status=400,
                    )
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Некорректное значение суммы"},
                    status=400,
                )

            source_supplier = get_object_or_404(Supplier, id=source_supplier_id)
            source_account = get_object_or_404(Account, id=source_account_id)

            source_supplier_account = SupplierAccount.objects.filter(
                supplier=source_supplier,
                account=source_account
            ).first()

            if not source_supplier_account or Decimal(source_supplier_account.balance or 0) < Decimal(amount_value):
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно средств на счете поставщика"},
                    status=400,
                )

            cash_account = Account.objects.filter(name="Наличные").first()
            if not cash_account:
                return JsonResponse(
                    {"status": "error", "message": 'Счет "Наличные" не найден в системе'},
                    status=400,
                )

            MoneyTransfer.objects.create(
                source_account=source_account,
                source_supplier=source_supplier,
                destination_account=cash_account,
                destination_supplier=source_supplier,
                amount=amount_value
            )

            source_supplier_account.balance = Decimal(source_supplier_account.balance or 0) - Decimal(amount_value)
            source_supplier_account.save()

            cash_account.balance = F('balance') + amount_value
            cash_account.save(update_fields=['balance'])
            cash_account.refresh_from_db(fields=['balance'])

            collection_purpose = PaymentPurpose.objects.filter(name="Инкассация").first()
            if not collection_purpose:
                collection_purpose = PaymentPurpose.objects.create(
                    name="Инкассация",
                    operation_type=PaymentPurpose.EXPENSE
                )
            CashFlow.objects.create(
                account=source_account,
                supplier=source_supplier,
                amount=-amount_value,
                purpose=collection_purpose,
                comment=f"Инкассация: перевод на счет 'Наличные'",
                created_by=request.user
            )

            bank_accounts = Account.objects.exclude(name__iexact="Наличные").order_by('name')
            suppliers = Supplier.objects.filter(visible_in_summary=True).order_by('name')

            class SupplierAccountRow:
                def __init__(self, supplier_name, supplier_id):
                    self.supplier = supplier_name
                    self.supplier_id = supplier_id

            balances = {}
            supplier_accounts_qs = SupplierAccount.objects.select_related('supplier', 'account').all()
            for sa in supplier_accounts_qs:
                balances[(sa.supplier_id, sa.account_id)] = sa.balance or 0

            rows = []
            account_totals = {account.id: 0 for account in bank_accounts}
            grand_total = 0

            for supplier in suppliers:
                row = SupplierAccountRow(supplier.name, supplier.id)
                total_balance = 0
                for account in bank_accounts:
                    balance = balances.get((supplier.id, account.id), 0)
                    balance_float = float(balance or 0)
                    setattr(row, f'account_{account.id}', format_currency(balance_float))
                    account_totals[account.id] = float(account_totals[account.id]) + balance_float
                    total_balance += balance_float
                grand_total += total_balance
                setattr(row, 'total_balance', format_currency(total_balance))
                rows.append(row)

            grand_total = sum(account_totals.values())

            total_row = SupplierAccountRow("ВСЕГО", 0)
            for account in bank_accounts:
                setattr(total_row, f'account_{account.id}', format_currency(account_totals[account.id]))
            setattr(total_row, 'total_balance', format_currency(grand_total))

            supplier_fields = [
                {"name": "supplier", "verbose_name": "Поставщик"}
            ]
            for account in bank_accounts:
                supplier_fields.append({
                    "name": f"account_{account.id}",
                    "verbose_name": account.name,
                    "is_amount": True
                })
            supplier_fields.append({
                "name": "total_balance",
                "verbose_name": "Итого",
                "is_amount": True
            })

            context_row = {
                "item": row,
                "fields": supplier_fields
            }

            context_total = {
                "item": total_row,
                "fields": supplier_fields
            }

            cash_account = Account.objects.filter(name__iexact="Наличные").first()
            cash_balance = float(cash_account.balance) if cash_account and cash_account.balance is not None else 0

            grand_total_with_cash = grand_total + cash_balance

            return JsonResponse({
                "html": render_to_string("components/table_row.html", context_row),
                "total_html": render_to_string("components/table_row.html", context_total),
                "id": source_supplier.id,
                "status": "success",
                "message": f"Инкассация на сумму {amount_value} р. успешно выполнена",
                "cash_balance": format_currency(cash_balance),
                "grand_total_with_cash": format_currency(grand_total_with_cash),
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@forbid_supplier
@login_required
def money_transfers(request):
    money_transfers = MoneyTransfer.objects.select_related('source_account', 'destination_account', 'source_supplier', 'destination_supplier').all()

    class MoneyTransferRow:
        def __init__(self, source_account, destination_account, source_supplier, destination_supplier, amount):
            self.source_account = source_account
            self.destination_account = destination_account
            self.source_supplier = source_supplier
            self.destination_supplier = destination_supplier
            self.amount = amount

    rows = [MoneyTransferRow(
        mt.source_account.name,
        mt.destination_account.name,
        mt.source_supplier.name if mt.source_supplier else "Не указан",
        mt.destination_supplier.name if mt.destination_supplier else "Не указан",
        format_currency(mt.amount)
    ) for mt in money_transfers]

    fields = [
        {"name": "source_account", "verbose_name": "Счет отправителя"},
        {"name": "destination_account", "verbose_name": "Счет получателя"},
        {"name": "source_supplier", "verbose_name": "Поставщик отправитель"},
        {"name": "destination_supplier", "verbose_name": "Поставщик получатель"},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True}
    ]
    is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False

    context = {
        "fields": fields,
        "data": rows,
        "is_admin": is_admin,
        "data_ids": [mt.id for mt in money_transfers],
    }

    return render(request, "main/money_transfers.html", context)

@forbid_supplier
@login_required
def money_transfer_detail(request, pk: int):
    money_transfer = get_object_or_404(MoneyTransfer, id=pk)

    data = model_to_dict(money_transfer)

    data['source_account_name'] = money_transfer.source_account.name if money_transfer.source_account else ""
    data['destination_account_name'] = money_transfer.destination_account.name if money_transfer.destination_account else ""
    data['source_supplier_name'] = money_transfer.source_supplier.name if money_transfer.source_supplier else ""
    data['destination_supplier_name'] = money_transfer.destination_supplier.name if money_transfer.destination_supplier else ""

    data['formatted_amount'] = format_currency(money_transfer.amount)

    data['created_at_formatted'] = timezone.localtime(money_transfer.created_at).strftime("%d.%m.%Y %H:%M") if money_transfer.created_at else ""

    return JsonResponse({"data": data})


@forbid_supplier
@login_required
@require_http_methods(["POST"])
def money_transfer_create(request):
    try:
        with transaction.atomic():
            source_supplier_id = request.POST.get("source_supplier")
            destination_supplier_id = request.POST.get("destination_supplier")

            source_account_id = request.POST.get("source_account")
            destination_account_id = request.POST.get("destination_account")

            amount = clean_currency(request.POST.get("amount"))
            comment = request.POST.get("comment", "")

            is_exchange = request.GET.get("exchange") == "true"

            if not all([source_supplier_id, destination_supplier_id, amount, source_account_id, destination_account_id]):
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            try:
                amount_value = int(float(amount))
                if amount_value <= 0:
                    return JsonResponse(
                        {"status": "error", "message": "Сумма должна быть больше нуля"},
                        status=400,
                    )
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Некорректное значение суммы"},
                    status=400,
                )

            source_supplier = get_object_or_404(Supplier, id=source_supplier_id)
            destination_supplier = get_object_or_404(Supplier, id=destination_supplier_id)

            transfer_type = None
            is_counted = None

            if is_exchange:
                source_visible = getattr(source_supplier, "visible_for_assistant", False)
                destination_visible = getattr(destination_supplier, "visible_for_assistant", False)
                if source_visible:
                    transfer_type = "from_us"
                elif not destination_visible:
                    transfer_type = "from_us"
                else:
                    transfer_type = "to_us"

                if source_visible and destination_visible:
                    is_counted = False
                elif not source_visible and not destination_visible:
                    is_counted = False
                else:
                    is_counted = True

            source_account = get_object_or_404(Account, id=source_account_id)
            destination_account = get_object_or_404(Account, id=destination_account_id)

            if source_account.id == destination_account.id and source_supplier.id == destination_supplier.id:
                return JsonResponse(
                    {"status": "error", "message": "Нельзя переводить средства на тот же счет того же поставщика"},
                    status=400,
                )

            source_supplier_account = SupplierAccount.objects.filter(
                supplier=source_supplier,
                account=source_account
            ).first()

            if not source_supplier_account or Decimal(source_supplier_account.balance or 0) < Decimal(amount_value):
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно средств на счете поставщика-отправителя"},
                    status=400,
                )

            money_transfer = MoneyTransfer.objects.create(
                source_account=source_account,
                destination_account=destination_account,
                source_supplier=source_supplier,
                destination_supplier=destination_supplier,
                amount=amount_value,
                transfer_type=transfer_type if is_exchange else None,
                is_counted=is_counted if is_exchange else None,
                comment=comment,
                created_at=timezone.now()
            )

            source_supplier_account.balance = Decimal(source_supplier_account.balance or 0) - Decimal(amount_value)
            source_supplier_account.save()

            destination_supplier_account, _ = SupplierAccount.objects.get_or_create(
                supplier=destination_supplier,
                account=destination_account,
                defaults={'balance': 0}
            )
            destination_supplier_account.balance = Decimal(destination_supplier_account.balance or 0) + Decimal(amount_value)
            destination_supplier_account.save()

            transfer_purpose = PaymentPurpose.objects.filter(name="Перевод").first()
            if not transfer_purpose:
                transfer_purpose = PaymentPurpose.objects.create(
                    name="Перевод",
                    operation_type=PaymentPurpose.EXPENSE
                )
            
            if comment:
                comment_source = comment
                comment_destination = comment
            else:
                comment_source = f"Перевод {destination_supplier.name} на счет {destination_account.name}"
                comment_destination = f"Получено от {source_supplier.name} со счета {source_account.name}"
                
            CashFlow.objects.create(
                account=source_account,
                supplier=source_supplier,
                amount=-amount_value,
                purpose=transfer_purpose,
                comment=comment_source,
                created_by=request.user,
                created_at=timezone.now()
            )
            CashFlow.objects.create(
                account=destination_account,
                supplier=destination_supplier,
                amount=amount_value,
                purpose=transfer_purpose,
                comment=comment_destination,
                created_by=request.user,
                created_at=timezone.now()
            )

            suppliers = Supplier.objects.filter(visible_in_summary=True).order_by('name')
            bank_accounts = Account.objects.exclude(name__iexact="Наличные").order_by('name')

            class SupplierAccountRow:
                def __init__(self, supplier_name, supplier_id):
                    self.supplier = supplier_name
                    self.supplier_id = supplier_id

            balances = {}
            supplier_accounts = SupplierAccount.objects.select_related('supplier', 'account').all()
            for sa in supplier_accounts:
                balances[(sa.supplier_id, sa.account_id)] = sa.balance or 0

            rows = []
            account_totals = {account.id: 0 for account in bank_accounts}
            grand_total = 0

            for supplier in suppliers:
                row = SupplierAccountRow(supplier.name, supplier.id)
                total_balance = 0
                for account in bank_accounts:
                    balance = balances.get((supplier.id, account.id), 0)
                    setattr(row, f'account_{account.id}', format_currency(float(balance)))
                    account_totals[account.id] = float(account_totals[account.id]) + float(balance)
                    total_balance += float(balance)
                grand_total += total_balance
                setattr(row, 'total_balance', format_currency(total_balance))
                rows.append(row)

            grand_total = sum(account_totals.values())

            total_row = SupplierAccountRow("ВСЕГО", 0)
            for account in bank_accounts:
                setattr(total_row, f'account_{account.id}', format_currency(account_totals[account.id]))
            setattr(total_row, 'total_balance', format_currency(grand_total))
            rows.append(total_row)

            supplier_fields = [
                {"name": "supplier", "verbose_name": "Поставщик"}
            ]
            for account in bank_accounts:
                supplier_fields.append({
                    "name": f"account_{account.id}",
                    "verbose_name": account.name,
                    "is_amount": True
                })
            supplier_fields.append({
                "name": "total_balance",
                "verbose_name": "Итого",
                "is_amount": True
            })

            table_context = {
                "id": "suppliers-account-table",
                "fields": supplier_fields,
                "data": rows,
            }
            html_table = render_to_string("components/table.html", table_context)

            class MoneyTransferRow:
                def __init__(self, source_account, destination_account, source_supplier, destination_supplier, amount):
                    self.source_account = source_account
                    self.destination_account = destination_account
                    self.source_supplier = source_supplier
                    self.destination_supplier = destination_supplier
                    self.amount = amount

            row = MoneyTransferRow(
                source_account.name,
                destination_account.name,
                source_supplier.name,
                destination_supplier.name,
                format_currency(amount_value)
            )

            fields = [
                {"name": "source_supplier", "verbose_name": "Поставщик отправитель"},
                {"name": "source_account", "verbose_name": "Счет отправителя"},
                {"name": "destination_supplier", "verbose_name": "Поставщик получатель"},
                {"name": "destination_account", "verbose_name": "Счет получателя"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True}
            ]

            context = {
                "item": row,
                "fields": fields
            }

            from_us_transfers = list(
                MoneyTransfer.objects.filter(transfer_type="from_us").order_by('-is_counted')
            )
            to_us_transfers = list(
                MoneyTransfer.objects.filter(transfer_type="to_us")
            )
            
            cash_account = Account.objects.filter(name__iexact="Наличные").first()
            cash_balance = cash_account.balance if cash_account else 0

            grand_total_with_cash = grand_total + (float(cash_balance) if cash_balance is not None else 0)
            
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": money_transfer.id,
                "status": "success",
                "message": f"Перевод на сумму {amount_value} р. успешно выполнен",
                "table_html": html_table,
                "transfer_type": money_transfer.transfer_type,
                "type": "create",
                "counted_from_us": [t.id for t in from_us_transfers if t.is_counted],
                "counted_to_us": [t.id for t in to_us_transfers if not t.is_completed],
                "from_us_completed": [t.id for t in from_us_transfers if t.is_completed],
                "to_us_completed": [t.id for t in to_us_transfers if t.is_completed],
                "cash_balance": format_currency(float(cash_balance) if cash_balance is not None else 0),
                "grand_total_with_cash": format_currency(grand_total_with_cash),
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@forbid_supplier
@login_required
@require_http_methods(["POST"])
def money_transfer_edit(request, pk: int):
    try:
        with transaction.atomic():
            money_transfer = get_object_or_404(MoneyTransfer, id=pk)

            if money_transfer.is_completed:
                return JsonResponse(
                    {"status": "error", "message": "Редактирование завершенных переводов не допускается"},
                    status=400,
                )

            source_supplier_id = request.POST.get("source_supplier")
            destination_supplier_id = request.POST.get("destination_supplier")
            amount = clean_currency(request.POST.get("amount"))
            comment = request.POST.get("comment", "")

            source_account_id = request.POST.get("source_account")
            destination_account_id = request.POST.get("destination_account")

            if not all([source_supplier_id, destination_supplier_id, amount, source_account_id, destination_account_id]):
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            try:
                amount_value = int(float(amount))
                if amount_value <= 0:
                    return JsonResponse(
                        {"status": "error", "message": "Сумма должна быть больше нуля"},
                        status=400,
                    )
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Некорректное значение суммы"},
                    status=400,
                )

            old_transfer_type = money_transfer.transfer_type

            old_source_account = money_transfer.source_account
            old_destination_account = money_transfer.destination_account
            old_source_supplier = money_transfer.source_supplier
            old_destination_supplier = money_transfer.destination_supplier
            old_amount = int(money_transfer.amount)

            new_source_supplier = get_object_or_404(Supplier, id=source_supplier_id)
            new_destination_supplier = get_object_or_404(Supplier, id=destination_supplier_id)

            new_source_account = get_object_or_404(Account, id=source_account_id)
            new_destination_account = get_object_or_404(Account, id=destination_account_id)

            if new_source_account.id == new_destination_account.id and new_source_supplier.id == new_destination_supplier.id:
                return JsonResponse(
                    {"status": "error", "message": "Нельзя переводить средства на тот же счет того же поставщика"},
                    status=400,
                )

            new_source_supplier_account = SupplierAccount.objects.filter(
                supplier=new_source_supplier,
                account=new_source_account
            ).first()
            if not new_source_supplier_account or Decimal(new_source_supplier_account.balance or 0) < Decimal(amount_value):
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно средств на счете поставщика-отправителя"},
                    status=400,
                )

            if old_source_supplier:
                old_source_supplier_account, _ = SupplierAccount.objects.get_or_create(
                    supplier=old_source_supplier,
                    account=old_source_account,
                    defaults={'balance': 0}
                )
                old_source_supplier_account.balance = Decimal(old_source_supplier_account.balance or 0) + Decimal(old_amount)
                old_source_supplier_account.save()
            else:
                old_source_account.balance = F('balance') + old_amount
                old_source_account.save(update_fields=['balance'])
                old_source_account.refresh_from_db(fields=['balance'])

            if old_destination_supplier:
                old_destination_supplier_account = SupplierAccount.objects.filter(
                    supplier=old_destination_supplier,
                    account=old_destination_account
                ).first()
                if old_destination_supplier_account:
                    old_destination_supplier_account.balance = Decimal(old_destination_supplier_account.balance or 0) - Decimal(old_amount)
                    old_destination_supplier_account.save()
            else:
                old_destination_account.balance = F('balance') - old_amount
                old_destination_account.save(update_fields=['balance'])
                old_destination_account.refresh_from_db(fields=['balance'])

            new_source_supplier_account.balance = Decimal(new_source_supplier_account.balance or 0) - Decimal(amount_value)
            new_source_supplier_account.save()

            new_destination_supplier_account, _ = SupplierAccount.objects.get_or_create(
                supplier=new_destination_supplier,
                account=new_destination_account,
                defaults={'balance': 0}
            )
            new_destination_supplier_account.balance = Decimal(new_destination_supplier_account.balance or 0) + Decimal(amount_value)
            new_destination_supplier_account.save()

            transfer_type = None
            is_counted = None

            if money_transfer.transfer_type in ["from_us", "to_us"]:
                source_visible = getattr(new_source_supplier, "visible_for_assistant", False)
                destination_visible = getattr(new_destination_supplier, "visible_for_assistant", False)
                if source_visible:
                    transfer_type = "from_us"
                elif not destination_visible:
                    transfer_type = "from_us"
                else:
                    transfer_type = "to_us"

                if source_visible and destination_visible:
                    is_counted = False
                elif not source_visible and not destination_visible:
                    is_counted = False
                else:
                    is_counted = True

            money_transfer.source_account = new_source_account
            money_transfer.destination_account = new_destination_account
            money_transfer.source_supplier = new_source_supplier
            money_transfer.destination_supplier = new_destination_supplier
            money_transfer.amount = amount_value
            money_transfer.transfer_type = transfer_type
            money_transfer.is_counted = is_counted
            money_transfer.comment = comment
            money_transfer.save()

            from datetime import timedelta
            transfer_purpose = PaymentPurpose.objects.filter(name="Перевод").first()
            if transfer_purpose:
                if comment:
                    comment_source = comment
                    comment_destination = comment
                else:
                    comment_source = f"Перевод {new_destination_supplier.name} на счет {new_destination_account.name}"
                    comment_destination = f"Получено от {new_source_supplier.name} со счета {new_source_account.name}"

                source_cf = CashFlow.objects.filter(
                    account=old_source_account,
                    supplier=old_source_supplier,
                    purpose=transfer_purpose,
                    created_at__range=(money_transfer.created_at - timedelta(seconds=10), money_transfer.created_at + timedelta(seconds=10))
                ).first()
                if source_cf:
                    source_cf.account = new_source_account
                    source_cf.supplier = new_source_supplier
                    source_cf.amount = -amount_value
                    source_cf.comment = comment_source
                    source_cf.save()

                dest_cf = CashFlow.objects.filter(
                    account=old_destination_account,
                    supplier=old_destination_supplier,
                    purpose=transfer_purpose,
                    created_at__range=(money_transfer.created_at - timedelta(seconds=10), money_transfer.created_at + timedelta(seconds=10))
                ).first()
                if dest_cf:
                    dest_cf.account = new_destination_account
                    dest_cf.supplier = new_destination_supplier
                    dest_cf.amount = amount_value
                    dest_cf.comment = comment_destination
                    dest_cf.save()

            class MoneyTransferRow:
                def __init__(self, source_account, destination_account, source_supplier, destination_supplier, amount):
                    self.source_account = source_account
                    self.destination_account = destination_account
                    self.source_supplier = source_supplier
                    self.destination_supplier = destination_supplier
                    self.amount = amount

            row = MoneyTransferRow(
                new_source_account.name,
                new_destination_account.name,
                new_source_supplier.name,
                new_destination_supplier.name,
                format_currency(amount_value)
            )

            fields = [
                {"name": "source_supplier", "verbose_name": "Поставщик отправитель"},
                {"name": "source_account", "verbose_name": "Счет отправителя"},
                {"name": "destination_supplier", "verbose_name": "Поставщик получатель"},
                {"name": "destination_account", "verbose_name": "Счет получателя"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True}
            ]

            context = {
                "item": row,
                "fields": fields
            }

            from_us_transfers = list(
                MoneyTransfer.objects.filter(transfer_type="from_us").order_by('-is_counted')
            )
            to_us_transfers = list(
                MoneyTransfer.objects.filter(transfer_type="to_us")
            )

            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": money_transfer.id,
                "status": "success",
                "message": f"Перевод успешно обновлен",
                "transfer_type": money_transfer.transfer_type,
                "old_transfer_type": old_transfer_type,
                "type": "edit",
                "counted_from_us": [t.id for t in from_us_transfers if t.is_counted],
                "counted_to_us": [t.id for t in to_us_transfers if not t.is_completed],
                "from_us_completed": [t.id for t in from_us_transfers if t.is_completed],
                "to_us_completed": [t.id for t in to_us_transfers if t.is_completed],
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)




@forbid_supplier
@login_required
@require_http_methods(["POST"])
def money_transfer_delete(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID перевода не указан"},
                    status=400,
                )

            money_transfer = get_object_or_404(MoneyTransfer, id=pk)

            if money_transfer.is_completed:
                return JsonResponse(
                    {"status": "error", "message": "Удаление завершенных переводов не допускается"},
                    status=400,
                )

            source_account = money_transfer.source_account
            destination_account = money_transfer.destination_account
            source_supplier = money_transfer.source_supplier
            destination_supplier = money_transfer.destination_supplier
            amount = int(money_transfer.amount)

            destination_supplier_account = None
            if destination_supplier:
                destination_supplier_account = SupplierAccount.objects.filter(
                    supplier=destination_supplier,
                    account=destination_account
                ).first()

                if not destination_supplier_account or Decimal(destination_supplier_account.balance or 0) < Decimal(amount):
                    return JsonResponse(
                        {"status": "error", "message": "Недостаточно средств у получателя для отмены перевода"},
                        status=400,
                    )

            if source_supplier:
                source_supplier_account, _ = SupplierAccount.objects.get_or_create(
                    supplier=source_supplier,
                    account=source_account,
                    defaults={'balance': 0}
                )
                source_supplier_account.balance = Decimal(source_supplier_account.balance or 0) + Decimal(amount)
                source_supplier_account.save()
            else:
                source_account.balance = F('balance') + amount
                source_account.save(update_fields=['balance'])
                source_account.refresh_from_db(fields=['balance'])

            if destination_supplier and destination_supplier_account:
                destination_supplier_account.balance = Decimal(destination_supplier_account.balance or 0) - Decimal(amount)
                destination_supplier_account.save()
            else:
                destination_account.balance = F('balance') - amount
                destination_account.save(update_fields=['balance'])
                destination_account.refresh_from_db(fields=['balance'])

            transfer_type = money_transfer.transfer_type
            money_transfer.delete()

            from datetime import timedelta
            transfer_purpose = PaymentPurpose.objects.filter(name="Перевод").first()
            if transfer_purpose:
                CashFlow.objects.filter(
                    account__in=[source_account, destination_account],
                    supplier__in=[source_supplier, destination_supplier] if source_supplier and destination_supplier else [source_supplier or destination_supplier],
                    purpose=transfer_purpose,
                    created_at__range=(money_transfer.created_at - timedelta(seconds=10), money_transfer.created_at + timedelta(seconds=10))
                ).delete()

            from_us_transfers = list(
                MoneyTransfer.objects.filter(transfer_type="from_us").order_by('-is_counted')
            )
            to_us_transfers = list(
                MoneyTransfer.objects.filter(transfer_type="to_us")
            )

            return JsonResponse({
                "status": "success",
                "message": f"Перевод на сумму {amount} р. успешно удален",
                "id": pk,
                "type": "delete",
                "transfer_type": transfer_type,
                "counted_from_us": [t.id for t in from_us_transfers if t.is_counted],
                "counted_to_us": [t.id for t in to_us_transfers if not t.is_completed],
                "from_us_completed": [t.id for t in from_us_transfers if t.is_completed],
                "to_us_completed": [t.id for t in to_us_transfers if t.is_completed],
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@login_required
def debtors(request):
    user = request.user
    is_admin = hasattr(user, 'user_type') and user.user_type.name == 'Администратор'

    is_supplier = hasattr(request.user, 'user_type') and request.user.user_type.name == 'Поставщик' or request.user.user_type.name == 'Филиал'

    branches = list(Branch.objects.all().values('id', 'name'))

    if is_supplier:
        branch = None
        if hasattr(user, 'branch') and user.branch:
            branch = user.branch
        else:
            supplier = Supplier.objects.filter(user=user).first()
            if supplier:
                branch = supplier.branch
        if branch:
            branches = [b for b in branches if b['id'] == branch.id]

    transactions = Transaction.objects.select_related('supplier__branch').filter(paid_amount__gt=0).all()

    branch_debts = defaultdict(float)
    for t in transactions:
        branch = t.supplier.branch if t.supplier and t.supplier.branch else None
        if branch and branch.name != "Филиал 1" and branch.name != "Наши ИП":
            branch_debts[branch.name] += float(getattr(t, 'supplier_debt', 0))

    branch_debts_list = [
        {"branch": branch['name'], "debt": branch_debts.get(branch['name'], 0)}
        for branch in branches
    ]

    total_branch_debts = sum(
        branch['debt'] for branch in branch_debts_list if branch['branch'] != "Филиал 1" and branch['branch'] != "Наши ИП"
    )

    total_bonuses = sum(float(t.bonus_debt) for t in transactions)
    total_remaining = sum(float(t.client_debt_paid) for t in transactions)
    total_profit = sum(float(t.profit) for t in transactions if float(t.paid_amount) - float(t.amount) == 0)

    transactionsInvestors = [
        t for t in Transaction.objects.filter(paid_amount__gt=0)
        if getattr(t, 'bonus_debt', 0) == 0
        and getattr(t, 'client_debt', 0) == 0
        and getattr(t, 'profit', 0) > 0
    ]

    cashflows = CashFlow.objects.filter(
        purpose__operation_type=PaymentPurpose.INCOME
    ).exclude(purpose__name__in=["Оплата", "Внесение инвестора", "Возврат от поставщиков"])

    total_profit = sum(float(t.profit - t.returned_to_investor) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

    summary = [
        {"name": "Бонусы", "amount": total_bonuses},
        {"name": "Выдачи клиентам", "amount": total_remaining},
    ]

    if is_admin:
        summary.append({"name": "Инвесторам", "amount": total_profit})

    if is_supplier:
        summary = []

    total_summary_debts = sum(item['amount'] for item in summary)
    
    context = {
        "is_admin": is_admin,
        "is_supplier": is_supplier,
        "branch_debts": branch_debts_list,
        "summary": summary,
        "total_branch_debts": total_branch_debts,
        "total_summary_debts": total_summary_debts,
    }
    return render(request, "main/debtors.html", context)


@login_required
def balance(request):
    user = request.user
    is_admin = hasattr(user, 'user_type') and user.user_type.name == 'Администратор'

    is_supplier = hasattr(request.user, 'user_type') and request.user.user_type.name == 'Поставщик' or request.user.user_type.name == 'Филиал'

    branches = list(Branch.objects.all().values('id', 'name'))

    if is_supplier:
        branch = None
        if hasattr(user, 'branch') and user.branch:
            branch = user.branch
        else:
            supplier = Supplier.objects.filter(user=user).first()
            if supplier:
                branch = supplier.branch
        if branch:
            branches = [b for b in branches if b['id'] == branch.id]

    transactions = Transaction.objects.select_related('supplier__branch').filter(paid_amount__gt=0).all()

    branch_debts = defaultdict(float)
    for t in transactions:
        branch = t.supplier.branch if t.supplier and t.supplier.branch else None
        if branch and branch.name != "Филиал 1" and branch.name != "Наши ИП":
            branch_debts[branch.name] += float(getattr(t, 'supplier_debt', 0))

    branch_debts_list = [
        {"branch": branch['name'], "debt": branch_debts.get(branch['name'], 0)}
        for branch in branches
    ]

    total_branch_debts = sum(
        branch['debt'] for branch in branch_debts_list if branch['branch'] != "Филиал 1" and branch['branch'] != "Наши ИП"
    )

    total_bonuses = sum(float(t.bonus_debt) for t in transactions)
    total_remaining = sum(float(t.client_debt_paid) for t in transactions)
    total_profit = sum(float(t.profit) for t in transactions if float(t.paid_amount) - float(t.amount) == 0)

    transactionsInvestors = [
        t for t in Transaction.objects.filter(paid_amount__gt=0)
        if getattr(t, 'bonus_debt', 0) == 0
        and getattr(t, 'client_debt', 0) == 0
        and getattr(t, 'profit', 0) > 0
    ]

    cashflows = CashFlow.objects.filter(
        purpose__operation_type=PaymentPurpose.INCOME
    ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

    total_profit = sum(float(t.profit - t.returned_to_investor) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

    summary = [
        {"name": "Бонусы", "amount": total_bonuses},
        {"name": "Выдачи клиентам", "amount": total_remaining},
    ]

    if is_admin:
        summary.append({"name": "Инвесторам", "amount": total_profit})

    if is_supplier:
        summary = []

    total_summary_debts = sum(item['amount'] for item in summary)
    
    context = {
        "is_admin": is_admin,
        "is_supplier": is_supplier,
        "branch_debts": branch_debts_list,
        "summary": summary,
        "total_branch_debts": total_branch_debts,
        "total_summary_debts": total_summary_debts,
    }
    return render(request, "main/balance.html", context)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def settle_supplier_debt(request, pk: int):
    try:
        with transaction.atomic():
            amount = clean_currency(request.POST.get("amount"))
            type_ = request.POST.get("type")
            comment = request.POST.get("comment", "").strip()

            if not amount:
                return JsonResponse({"status": "error", "message": "Сумма обязательна"}, status=400)
            try:
                amount_value = Decimal(str(amount))
                if amount_value <= 0:
                    return JsonResponse({"status": "error", "message": "Сумма должна быть больше нуля"}, status=400)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректная сумма"}, status=400)

            if type_ not in ("balance", "initial", "short_term_liabilities", "credit", "equipment", "profit"):
                trans = get_object_or_404(Transaction, id=pk)

            if type_ == "branch":
                branch = trans.supplier.branch if trans and trans.supplier else None

                supplier_ids = Supplier.objects.filter(branch=branch).values_list('id', flat=True)
                branch_transactions = Transaction.objects.filter(
                    supplier_id__in=supplier_ids,
                    paid_amount__gt=0
                ).order_by('created_at')

                branch_total_debt = sum(Decimal(str(getattr(t, 'supplier_debt', 0) or 0)) for t in branch_transactions)

                if amount_value > branch_total_debt:
                    return JsonResponse({"status": "error", "message": "Сумма не может превышать долг филиала"}, status=400)

                remaining = amount_value
                repayments = []
                changed_html_rows = []
                changed_ids = []

                for t in branch_transactions:
                    debt = Decimal(str(getattr(t, 'supplier_debt', 0) or 0))
                    if debt <= 0 or remaining <= 0:
                        continue
                    repay_amount = min(debt, remaining)

                    t.returned_by_supplier = (Decimal(str(t.returned_by_supplier or 0)) + repay_amount)
                    t.returned_date = timezone.now()
                    t.save()

                    remaining -= repay_amount

                    row = type("DebtorRow", (), {})()
                    row.created_at = timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else ""
                    row.supplier = str(t.supplier) if t.supplier else ""
                    row.supplier_percentage = t.supplier_percentage
                    paid = Decimal(str(t.paid_amount or 0))
                    supplier_fee = Decimal(math.floor(float(Decimal(str(t.amount or 0)) * Decimal(str(t.supplier_percentage or 0)) / Decimal('100'))))
                    row.supplier_debt = paid - supplier_fee - Decimal(str(t.returned_by_supplier or 0))
                    row.amount = t.amount

                    fields = [
                        {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                        {"name": "supplier", "verbose_name": "Поставщик"},
                        {"name": "amount", "verbose_name": "Сумма сделки", "is_amount": True},
                        {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True},
                        {"name": "supplier_debt", "verbose_name": "Сумма", "is_amount": True},
                    ]

                    changed_html_rows.append(render_to_string("components/table_row.html", {"item": row, "fields": fields}))
                    changed_ids.append(t.id)

                branch_total_debt = sum(float(getattr(t, 'supplier_debt', 0) or 0) for t in branch_transactions)

                cash_account = Account.objects.filter(name__iexact="Наличные").first()
                if cash_account:
                    cash_account.balance = F('balance') + amount_value
                    cash_account.save(update_fields=['balance'])
                    cash_account.refresh_from_db(fields=['balance'])

                try:
                    supplier_for_record = None
                    if branch_transactions:
                        supplier_for_record = branch_transactions[0].supplier

                    collection_purpose = PaymentPurpose.objects.filter(name="Возврат от поставщиков").first()
                    if not collection_purpose:
                        collection_purpose = PaymentPurpose.objects.create(
                            name="Возврат от поставщиков",
                            operation_type=PaymentPurpose.EXPENSE
                        )
                    if cash_account:
                        CashFlow.objects.create(
                            account=cash_account,
                            supplier=supplier_for_record,
                            amount=amount_value,
                            purpose=collection_purpose,
                            comment=f"Возврат от поставщиков: перевод на счет 'Наличные'",
                            created_by=request.user,
                            created_at=timezone.now()
                        )
                except Exception as e:
                    import logging
                    logging.exception("Ошибка при создании CashFlow для инкассации филиала: %s", e)

                user = request.user

                supplier_for_record = None
                if branch_transactions:
                    supplier_for_record = branch_transactions[0].supplier 
                debtRepayment = SupplierDebtRepayment.objects.create(
                    supplier=supplier_for_record,
                    amount=amount_value,
                    comment=comment,
                    created_by=user
                )
                repayments.append(debtRepayment)

                html_debt_repayments = []
                for debtRepayment in repayments:
                    debtRepayment.created_at = timezone.localtime(debtRepayment.created_at).strftime("%d.%m.%Y %H:%M") if debtRepayment.created_at else ""
                    html_debt_repayments.append(render_to_string("components/table_row.html", {
                        "item": debtRepayment,
                        "fields": [
                            {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                            {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                            {"name": "comment", "verbose_name": "Комментарий"}
                        ]
                    }))

                transactions_all = Transaction.objects.filter(paid_amount__gt=0).exclude(supplier__branch__name="Филиал 1").exclude(supplier__branch__name="Наши ИП")
                all_branches_total_debt = sum(float(getattr(t, 'supplier_debt', 0) or 0) for t in transactions_all)

                return JsonResponse({
                    "html_debt_repayments": html_debt_repayments,
                    "debt_repayment_ids": [r.id for r in repayments],
                    "changed_html_rows": changed_html_rows,
                    "changed_ids": changed_ids,
                    "branch": branch.name.replace(" ", "_") if branch else None,
                    "total_debt": float(branch_total_debt) if branch else 0,
                    "type": "Поставщики",
                    "total_branch_debts": all_branches_total_debt,
                })

            elif type_ == "bonus":
                if amount_value == 0:
                    return JsonResponse({"status": "error", "message": "Сумма должна быть больше нуля"}, status=400)

                if amount_value > Decimal(str(trans.bonus_debt or 0)):
                    return JsonResponse({"status": "error", "message": "Сумма не может превышать долг по бонусам"}, status=400)
                
                cash_account = Account.objects.filter(name__iexact="Наличные").first()
                if not cash_account:
                    return JsonResponse({"status": "error", "message": 'Счет "Наличные" не найден'}, status=400)

                if Decimal(str(cash_account.balance or 0)) < amount_value:
                    return JsonResponse({"status": "error", "message": "Недостаточно средств на счете 'Наличные'"}, status=400)

                cash_account.balance = F('balance') - amount_value
                cash_account.save(update_fields=['balance'])
                cash_account.refresh_from_db(fields=['balance'])

                try:
                    bonus_purpose = PaymentPurpose.objects.filter(name="Выдача бонусов").first()
                    if not bonus_purpose:
                        bonus_purpose = PaymentPurpose.objects.create(
                            name="Выдача бонусов",
                            operation_type=PaymentPurpose.EXPENSE
                        )
                    CashFlow.objects.create(
                        account=cash_account,
                        amount=-int(float(amount_value)),
                        purpose=bonus_purpose,
                        comment=comment or (f"Выдача бонусов клиенту {trans.client}" if trans and getattr(trans, "client", None) else "Выдача бонусов"),
                        created_by=request.user,
                        created_at=timezone.now()
                    )
                except Exception as e:
                    import logging
                    logging.exception("Ошибка при создании CashFlow для выдачи бонусов: %s", e)


                trans.returned_bonus = Decimal(str(trans.returned_bonus or 0)) + amount_value
                trans.save()

                row = type("Row", (), {
                    "created_at": timezone.localtime(trans.created_at).strftime("%d.%m.%Y") if trans.created_at else "",
                    "client": str(trans.client) if trans.client else "",
                    "bonus_percentage": trans.bonus_percentage,
                    "bonus_debt": trans.bonus_debt,
                })()

                fields = [
                    {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                    {"name": "client", "verbose_name": "Клиент"},
                    {"name": "bonus_percentage", "verbose_name": "%", "is_percent": True},
                    {"name": "bonus_debt", "verbose_name": "Бонус", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                total_debt = sum(float(getattr(t, 'bonus_debt', 0) or 0) for t in Transaction.objects.filter(paid_amount__gt=0))

                transactions_all = Transaction.objects.filter(paid_amount__gt=0)
                total_bonuses = sum(float(getattr(t, 'bonus_debt', 0) or 0) for t in transactions_all)
                total_remaining = sum(float(getattr(t, 'client_debt_paid', 0) or 0) for t in transactions_all)

                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                cashflows = CashFlow.objects.filter(
                    purpose__operation_type=PaymentPurpose.INCOME
                ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

                total_profit = sum(float(getattr(t, 'profit', 0) - getattr(t, 'returned_to_investor', 0)) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

                is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False

                summary = [
                    {"name": "Бонусы", "amount": total_bonuses},
                    {"name": "Выдачи клиентам", "amount": total_remaining},
                ]

                if is_admin:
                    summary.append({"name": "Инвесторам", "amount": total_profit})

                total_summary_debts = sum(item['amount'] for item in summary)

                return JsonResponse({
                    "html": html,
                    "id": trans.id,
                    "type": "Бонусы",
                    "total_debt": total_debt,
                    "total_summary_debts": total_summary_debts,
                    "total_profit": total_profit,
                })

            elif type_ == "remaining":
                if amount_value == 0:
                    return JsonResponse({"status": "error", "message": "Сумма должна быть больше нуля"}, status=400)

                if amount_value > Decimal(str(trans.client_debt_paid or 0)):
                    return JsonResponse({"status": "error", "message": "Сумма не может превышать долг по выдачам"}, status=400)

                cash_account = Account.objects.filter(name__iexact="Наличные").first()
                if not cash_account:
                    return JsonResponse({"status": "error", "message": 'Счет "Наличные" не найден'}, status=400)

                if Decimal(str(cash_account.balance or 0)) < amount_value:
                    return JsonResponse({"status": "error", "message": "Недостаточно средств на счете 'Наличные'"}, status=400)

                cash_account.balance = F('balance') - amount_value
                cash_account.save(update_fields=['balance'])
                cash_account.refresh_from_db(fields=['balance'])

                cash_flow = None

                try:
                    purpose = PaymentPurpose.objects.filter(name="Погашение долга клиента").first()
                    if not purpose:
                        purpose = PaymentPurpose.objects.create(
                            name="Погашение долга клиента",
                            operation_type=PaymentPurpose.EXPENSE
                        )
                    cash_flow = CashFlow.objects.create(
                        account=cash_account,
                        amount=-int(float(amount_value)),
                        purpose=purpose,
                        comment=comment or (f"Выдача клиенту {trans.client}" if trans and getattr(trans, "client", None) else "Выдача клиенту"),
                        created_by=request.user,
                        created_at=timezone.now()
                    )
                except Exception as e:
                    import logging
                    logging.exception("Ошибка при создании CashFlow для выдачи клиенту: %s", e)

                trans.returned_to_client = Decimal(str(trans.returned_to_client or 0)) + amount_value
                trans.save()

                user = request.user

                clientDebtRepayment = ClientDebtRepayment.objects.create(
                    client=trans.client,
                    amount=amount_value,
                    comment=comment,
                    created_by=user,
                    transaction=trans,
                    cash_flow=cash_flow
                )

                row = type("Row", (), {
                    "created_at": timezone.localtime(trans.created_at).strftime("%d.%m.%Y") if trans.created_at else "",
                    "client": str(trans.client) if trans.client else "",
                    "amount": trans.amount,
                    "client_debt_paid": trans.client_debt_paid,
                })()

                fields = [
                    {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                    {"name": "client", "verbose_name": "Клиент"},
                    {"name": "amount", "verbose_name": "Сумма сделки", "is_amount": True},
                    {"name": "client_debt_paid", "verbose_name": "Выдать", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                clientDebtRepayment.created_at = timezone.localtime(clientDebtRepayment.created_at).strftime("%d.%m.%Y %H:%M") if clientDebtRepayment.created_at else ""

                html_client_debt_repayments = render_to_string("components/table_row.html", {
                    "item": clientDebtRepayment,
                    "fields": [
                        {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                        {"name": "client", "verbose_name": "Клиент"},
                        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                        {"name": "comment", "verbose_name": "Комментарий"}
                    ]
                })

                total_debt = sum(float(getattr(t, 'client_debt_paid', 0) or 0) for t in Transaction.objects.filter(paid_amount__gt=0))

                transactions_all = Transaction.objects.filter(paid_amount__gt=0)
                total_bonuses = sum(float(getattr(t, 'bonus_debt', 0) or 0) for t in transactions_all)
                total_remaining = sum(float(getattr(t, 'client_debt_paid', 0) or 0) for t in transactions_all)

                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                cashflows = CashFlow.objects.filter(
                    purpose__operation_type=PaymentPurpose.INCOME
                ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

                total_profit = sum(float(getattr(t, 'profit', 0) - getattr(t, 'returned_to_investor', 0)) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

                summary = [
                    {"name": "Бонусы", "amount": total_bonuses},
                    {"name": "Выдачи клиентам", "amount": total_remaining},
                ]

                is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False

                if is_admin:
                    summary.append({"name": "Инвесторам", "amount": total_profit})

                total_summary_debts = sum(item['amount'] for item in summary)

                return JsonResponse({
                    "html": html,
                    "id": trans.id,
                    "type": "Выдачи клиентам",
                    "total_debt": total_debt,
                    "total_summary_debts": total_summary_debts,
                    "total_profit": total_profit,
                    "html_client_debt_repayments": html_client_debt_repayments,
                    "client_debt_repayment_id": clientDebtRepayment.id,
                })

            elif type_ == "balance":
                operation_type = request.POST.get("operation_type")
                if operation_type not in ["withdrawal", "deposit"]:
                    return JsonResponse({"status": "error", "message": "Некорректный тип операции"}, status=400)

                investor = get_object_or_404(Investor, id=pk)

                cash_account = Account.objects.filter(name__iexact="Наличные").first()
                if not cash_account:
                    return JsonResponse({"status": "error", "message": "Счет 'Наличные' не найден"}, status=400)

                if operation_type == "deposit":
                    investor.balance = Decimal(str(investor.balance or 0)) + amount_value
                elif operation_type == "withdrawal":
                    if Decimal(str(investor.balance or 0)) < amount_value:
                        return JsonResponse({"status": "error", "message": "Недостаточно средств для снятия"}, status=400)
                    investor.balance = Decimal(str(investor.balance or 0)) - amount_value

                investor.save()

                user = request.user

                investorDebtOperation = InvestorDebtOperation.objects.create(
                    investor=investor,
                    amount=amount_value,
                    operation_type=operation_type,
                    created_by=user
                )

                row = type("InvestorRow", (), {
                    "name": investor.name,
                    "balance": investor.balance,
                })()
                fields = [
                    {"name": "name", "verbose_name": "Инвестор"},
                    {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                transactions_all = Transaction.objects.filter(paid_amount__gt=0)

                total_bonuses = sum(float(getattr(t, 'bonus_debt', 0) or 0) for t in transactions_all)
                total_remaining = sum(float(getattr(t, 'client_debt_paid', 0) or 0) for t in transactions_all)
                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                total_profit = sum(float(getattr(t, 'profit', 0)) for t in transactionsInvestors)

                investorDebtOperation.created_at = timezone.localtime(investorDebtOperation.created_at).strftime("%d.%m.%Y %H:%M") if investorDebtOperation.created_at else ""
                investorDebtOperation.operation_type = (
                    "Внесение" if investorDebtOperation.operation_type == "deposit"
                    else "Забор" if investorDebtOperation.operation_type == "withdrawal"
                    else "Прибыль" if investorDebtOperation.operation_type == "profit"
                    else investorDebtOperation.operation_type
                )

                html_investor_debt_operation = render_to_string("components/table_row.html", {
                    "item": investorDebtOperation,
                    "fields": [
                        {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                        {"name": "investor", "verbose_name": "Инвестор"},
                        {"name": "operation_type", "verbose_name": "Тип операции"},
                        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                    ]
                })

                summary = [
                    {"name": "Бонусы", "amount": total_bonuses},
                    {"name": "Выдачи клиентам", "amount": total_remaining},
                    {"name": "Инвесторам", "amount": total_profit},
                ]

                total_summary_debts = sum(item['amount'] for item in summary)

                return JsonResponse({
                    "html": html,
                    "id": investor.id,
                    "type": "balance_investor",
                    "total_summary_debts": total_summary_debts,
                    "html_investor_debt_operation": html_investor_debt_operation,
                })

            elif type_ in ["short_term_liabilities", "credit", "equipment"]:
                type_map = {
                    "equipment": "Оборудование",
                    "credit": "Кредит",
                    "short_term_liabilities": "Краткосрочные обязательства",
                }
                balance_type = type_map.get(type_, type_)
                balance_obj = get_object_or_404(BalanceData, name=balance_type)
                balance_obj.amount = amount_value
                balance_obj.save()

                equipment = BalanceData.objects.filter(name="Оборудование").aggregate(total=Sum("amount"))["total"] or Decimal(0)
                credit = BalanceData.objects.filter(name="Кредит").aggregate(total=Sum("amount"))["total"] or Decimal(0)
                short_term = BalanceData.objects.filter(name="Краткосрочные обязательства").aggregate(total=Sum("amount"))["total"] or Decimal(0)

                debtors = []
                total_debtors = Decimal(0)
                for branch in Supplier.objects.exclude(branch=None).values_list("branch__id", "branch__name").distinct():
                    branch_id, branch_name = branch
                    if branch_name != "Филиал 1" and branch_name != "Наши ИП":
                        branch_debt = sum(
                            (t.supplier_debt or Decimal(0))
                            for t in Transaction.objects.filter(supplier__branch_id=branch_id, paid_amount__gt=0)
                        )
                        debtors.append({"branch": branch_name, "amount": branch_debt})
                        total_debtors += branch_debt

                safe_amount = SupplierAccount.objects.filter(
                    supplier__visible_in_summary=True
                ).aggregate(total=Sum("balance"))["total"] or Decimal(0)

                cash_account = Account.objects.filter(name__iexact="Наличные").first()
                cash_balance = Decimal(cash_account.balance) if cash_account and cash_account.balance is not None else Decimal(0)

                safe_amount += cash_balance

                bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))
                client_debts = sum((t.client_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0).all())

                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                cashflows = CashFlow.objects.filter(
                    purpose__operation_type=PaymentPurpose.INCOME
                ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

                total_profit = sum(float(getattr(t, 'profit', 0) - getattr(t, 'returned_to_investor', 0)) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

                assets_total = equipment + Decimal(0) + total_debtors + safe_amount
                liabilities_total = credit + client_debts + short_term + bonuses + Decimal(total_profit)
                capital = assets_total - liabilities_total

                data = {
                    "non_current_assets": {
                        "total": equipment,
                        "items": [{"name": "Оборудование", "amount": equipment}]
                    },
                    "current_assets": {
                        "inventory": {"total": 0, "items": []},
                        "debtors": {"total": total_debtors, "items": debtors},
                        "cash": {"total": safe_amount, "items": [{"name": "Счета, Карты и Сейф", "amount": safe_amount}]},
                    },
                    "assets": assets_total,
                    "liabilities": {
                        "total": liabilities_total,
                        "items": [
                            {"name": "Кредит", "amount": credit},
                            {"name": "Кредиторская задолженность", "amount": client_debts},
                            {"name": "Краткосрочные обязательства", "amount": short_term},
                            {"name": "Бонусы", "amount": bonuses},
                            {"name": "Выплата инвесторам", "amount": total_profit},
                        ],
                    },
                    "capital": capital,
                    "type": "balance"
                }
                return JsonResponse(data, safe=False)

            elif type_ == "profit":
                if amount_value == 0:
                    return JsonResponse({"status": "error", "message": "Сумма должна быть больше нуля"}, status=400)

                trans = None
                cashflow = None

                if isinstance(pk, str) and pk.startswith("cf-"):
                    cf_id = pk.replace("cf-", "")
                    cashflow = get_object_or_404(CashFlow, id=cf_id)
                else:
                    trans = Transaction.objects.select_related('client').filter(id=pk).first()
                    if not trans:
                        return JsonResponse({"status": "error", "message": "Транзакция не найдена"}, status=400)

                if trans:
                    if amount_value > (Decimal(str(trans.profit or 0)) - Decimal(str(trans.returned_to_investor or 0))):
                        return JsonResponse({"status": "error", "message": "Сумма не может превышать долг инвестору"}, status=400)
                elif cashflow:
                    if amount_value > (Decimal(str(cashflow.amount or 0)) - Decimal(str(cashflow.returned_to_investor or 0))):
                        return JsonResponse({"status": "error", "message": "Сумма не может превышать долг инвестору"}, status=400)
                else:
                    return JsonResponse({"status": "error", "message": "Транзакция или денежный поток не найдены"}, status=400)

                investor_id = request.POST.get("investor_select")
                if not investor_id:
                    return JsonResponse({"status": "error", "message": "Инвестор обязателен"}, status=400)

                investor = get_object_or_404(Investor, id=investor_id)

                investor.balance = Decimal(str(investor.balance or 0)) + amount_value
                investor.save()

                user = request.user

                investorDebtOperation = InvestorDebtOperation.objects.create(
                    investor=investor,
                    amount=amount_value,
                    operation_type="profit",
                    created_by=user,
                )

                if trans:
                    trans.returned_to_investor = Decimal(str(trans.returned_to_investor or 0)) + amount_value
                    trans.save()

                    row = type("Row", (), {
                        "created_at": timezone.localtime(trans.created_at).strftime("%d.%m.%Y") if trans.created_at else "",
                        "client": str(trans.client) if trans.client else "",
                        "amount": trans.amount,
                        "profit": Decimal(str(trans.profit or 0)) - Decimal(str(trans.returned_to_investor or 0))
                    })()
                elif cashflow:
                    cashflow.returned_to_investor = Decimal(str(cashflow.returned_to_investor or 0)) + amount_value
                    cashflow.save()

                    row = type("Row", (), {
                        "created_at": timezone.localtime(cashflow.created_at).strftime("%d.%m.%Y") if cashflow.created_at else "",
                        "client": cashflow.purpose.name if cashflow.purpose else "Денежный поток",
                        "amount": cashflow.amount,
                        "profit": Decimal(str(cashflow.amount or 0)) - Decimal(str(cashflow.returned_to_investor or 0))
                    })()

                fields = [
                    {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                    {"name": "client", "verbose_name": "Клиент"},
                    {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                    {"name": "profit", "verbose_name": "Прибыль", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                investorDebtOperation.created_at = timezone.localtime(investorDebtOperation.created_at).strftime("%d.%m.%Y %H:%M") if investorDebtOperation.created_at else ""
                investorDebtOperation.operation_type = (
                    "Внесение" if investorDebtOperation.operation_type == "deposit"
                    else "Забор" if investorDebtOperation.operation_type == "withdrawal"
                    else "Прибыль" if investorDebtOperation.operation_type == "profit"
                    else investorDebtOperation.operation_type
                )

                html_investor_debt_operation = render_to_string("components/table_row.html", {
                    "item": investorDebtOperation,
                    "fields": [
                        {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                        {"name": "investor", "verbose_name": "Инвестор"},
                        {"name": "operation_type", "verbose_name": "Тип операции"},
                        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                    ]
                })

                transactions_all = Transaction.objects.filter(paid_amount__gt=0)
                total_bonuses = sum(float(getattr(t, 'bonus_debt', 0) or 0) for t in transactions_all)
                total_remaining = sum(float(getattr(t, 'client_debt_paid', 0) or 0) for t in transactions_all)

                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                cashflows = CashFlow.objects.filter(
                    purpose__operation_type=PaymentPurpose.INCOME
                ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

                total_debt = sum(float(Decimal(str(t.profit or 0)) - Decimal(str(t.returned_to_investor or 0))) for t in transactionsInvestors) + sum(float(Decimal(str(cf.amount or 0)) - Decimal(str(cf.returned_to_investor or 0))) for cf in cashflows)
                total_profit = total_debt

                is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False

                summary = [
                    {"name": "Бонусы", "amount": total_bonuses},
                    {"name": "Выдачи клиентам", "amount": total_remaining},
                ]

                if is_admin:
                    summary.append({"name": "Инвесторам", "amount": total_profit})

                total_summary_debts = sum(item['amount'] for item in summary)

                investor_fields = [
                    {"name": "name", "verbose_name": "Инвестор"},
                    {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
                ]
                investors = Investor.objects.all()
                investor_data = []
                for inv in investors:
                    investor_data.append(type("InvestorRow", (), {
                        "name": inv.name,
                        "balance": inv.balance,
                    })())
                investor_ids = [inv.id for inv in investors]

                html_investors = render_to_string(
                    "components/table.html",
                    {"id": "investors-table", "fields": investor_fields, "data": investor_data}
                )

                return JsonResponse({
                    "html": html,
                    "id": trans.id if trans else f"cf-{cashflow.id}",
                    "type": "Инвесторам",
                    "total_debt": total_debt,
                    "total_summary_debts": total_summary_debts,
                    "total_profit": total_profit,
                    "html_investor_debt_operation": html_investor_debt_operation,
                    "html_investors": html_investors,
                    "investor_ids": investor_ids,
                })

            else:
                return JsonResponse({"status": "error", "message": "Некорректный тип"}, status=400)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@forbid_supplier
@login_required
def debtor_detail(request, type, pk):
    if isinstance(pk, str) and pk.startswith("cf-"):
        cf_id = pk.replace("cf-", "")
        cashflow = get_object_or_404(CashFlow, id=cf_id)
        data = model_to_dict(cashflow)

        data['amount'] = float(Decimal(str(cashflow.amount or 0)) - Decimal(str(cashflow.returned_to_investor or 0)))
        return JsonResponse({"data": data})

    type_map = {
        "equipment": "Оборудование",
        "credit": "Кредит",
        "short_term_liabilities": "Краткосрочные обязательства",
    }
    type = type_map.get(type, type)

    if type in ["Оборудование", "Кредит", "Краткосрочные обязательства"]:
        obj = BalanceData.objects.filter(name=type).order_by('-created_at').first()
        if not obj:
            obj = BalanceData.objects.create(name=type, amount=0)
        data = {
            "name": obj.name,
            "amount": obj.amount
        }
    elif type in ("investors", "balance", "initial"):
        if pk == -1:
            return JsonResponse({"error": "ID инвестора не указан"}, status=400)
        obj = get_object_or_404(Investor, id=pk)
        data = model_to_dict(obj)

        if type == "initial" and obj.balance != 0:
            data["amount"] = 0
    elif type.startswith("transactions"):
        try:
            pk_int = int(pk)
        except (ValueError, TypeError):
            pk_int = None
        if pk_int == -1:
            transactions = [
                t for t in Transaction.objects.filter(paid_amount__gt=0)
                if getattr(t, 'bonus_debt', 0) == 0
                and getattr(t, 'client_debt', 0) == 0
                and t.amount == t.paid_amount
            ]

            total_investor_debt = sum(float(getattr(t, 'investor_debt', 0) or 0) for t in transactions)

            cashflows = CashFlow.objects.filter(
                purpose__operation_type=PaymentPurpose.INCOME
            ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])
            total_cashflow_income = sum(float(Decimal(str(cf.amount or 0)) - Decimal(str(cf.returned_to_investor or 0))) for cf in cashflows if cf.amount > 0)
            data = {}
            data["amount"] = total_investor_debt + total_cashflow_income
            return JsonResponse({"data": data})
        transaction = get_object_or_404(Transaction, id=pk)
        data = model_to_dict(transaction)
        if "amount" in data:
            if "." in type:
                suffix = type.split(".")[1]
                if suffix == "bonus":
                    data["amount"] = float(getattr(transaction, "bonus_debt", 0) or 0)
                elif suffix == "remaining":
                    data["amount"] = float(getattr(transaction, "client_debt_paid", 0) or 0)
                elif suffix == "investors":
                    data["amount"] = float(getattr(transaction, "investor_debt", 0) or 0)
                else:
                    data["amount"] = 0
            else:
                data["amount"] = 0
    else:
        return JsonResponse({"error": "Unknown type"}, status=400)

    return JsonResponse({"data": data})

@forbid_supplier
@login_required
def profit_distribution(request):
    transactions = Transaction.objects.select_related('client', 'supplier').all().order_by('created_at')

    class ProfitRow:
        def __init__(self, t):
            self.created_at = timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else ""
            self.client = str(t.client) if t.client else ""
            self.supplier = str(t.supplier) if t.supplier else ""
            self.amount = t.amount
            self.supplier_percentage = t.supplier_percentage
            self.profit = getattr(t, 'profit', None) if hasattr(t, 'profit') else None

    rows = [ProfitRow(t) for t in transactions]

    is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False

    fields = [
        {"name": "created_at", "verbose_name": "Дата", "is_date": True},
        {"name": "client", "verbose_name": "Клиент"},
        {"name": "supplier", "verbose_name": "Поставщик"},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
        {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True},
        {"name": "profit", "verbose_name": "Прибыль", "is_amount": True},
    ]

    context = {
        "fields": fields,
        "data": rows,
        "data_ids": [t.id for t in transactions],
        "is_admin": is_admin,
    }
    return render(request, "main/profit_distribution.html", context)


from django.views.decorators.http import require_GET

@login_required
@require_GET
def debtor_details(request):
    type_ = request.GET.get("type")
    value = request.GET.get("value")

    if type_ == "branch":
        branch = Branch.objects.filter(name=value).first()
        if not branch:
            return JsonResponse({"html": "<div>Филиал не найден</div>"})

        safe_branch = "".join([c if c.isalnum() else "_" for c in value])
        transactions_table_id = f"branch-transactions-{safe_branch}"
        repayments_table_id = f"branch-repayments-{safe_branch}"

        suppliers = Supplier.objects.filter(branch=branch)
        supplier_ids = suppliers.values_list('id', flat=True)
        transactions = (
            Transaction.objects
            .filter(supplier_id__in=supplier_ids, paid_amount__gt=0)
            .select_related('supplier').order_by('created_at')
        )

        transaction_fields = [
            {"name": "created_at", "verbose_name": "Дата", "is_date": True},
            {"name": "supplier", "verbose_name": "Поставщик"},
            {"name": "amount", "verbose_name": "Сумма сделки", "is_amount": True},
            {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True},
            {"name": "supplier_debt", "verbose_name": "Сумма", "is_amount": True},
        ]
        transaction_data = []
        for t in transactions:
            transaction_data.append(type("Row", (), {
                "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else "",
                "supplier": str(t.supplier) if t.supplier else "",
                "amount": t.amount,
                "supplier_percentage": t.supplier_percentage,
                "supplier_debt": t.supplier_debt,
            })())

        repayments = SupplierDebtRepayment.objects.filter(supplier_id__in=supplier_ids)
        repayment_fields = [
            {"name": "created_at", "verbose_name": "Дата", "is_date": True},
            {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            {"name": "comment", "verbose_name": "Комментарий"}
        ]
        repayment_data = []
        for r in repayments:
            repayment_data.append(type("Row", (), {
                "created_at": timezone.localtime(r.created_at).strftime("%d.%m.%Y %H:%M") if r.created_at else "",
                "amount": r.amount,
                "comment": r.comment or "",
            })())

        html_transactions = render_to_string(
            "components/table.html",
            {"id": transactions_table_id, "fields": transaction_fields, "data": transaction_data}
        )
        html_repayments = render_to_string(
            "components/table.html",
            {"id": repayments_table_id, "fields": repayment_fields, "data": repayment_data}
        )
        return JsonResponse({
            "html_transactions": html_transactions,
            "html_repayments": html_repayments,
            "data_ids": [t.id for t in transactions],
            "repayment_ids": [r.id for r in repayments],
            "transactions_table_id": transactions_table_id,
            "repayments_table_id": repayments_table_id
        })

    elif type_ == "summary":
        if value == "Выдачи клиентам":
            transactions = [
                t for t in Transaction.objects.filter(paid_amount__gt=0)
                if getattr(t, 'client_debt_paid', 0) != 0
            ]
            fields = [
                {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                {"name": "client", "verbose_name": "Клиент", "is_relation": True},
                {"name": "amount", "verbose_name": "Сумма сделки", "is_amount": True},
                {"name": "client_debt_paid", "verbose_name": "Выдать", "is_amount": True},
            ]
            data = []
            for t in transactions:
                data.append(type("Row", (), {
                    "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else "",
                    "client": str(t.client) if t.client else "",
                    "amount": t.amount,
                    "client_debt_paid": t.client_debt_paid,
                })())
            table_id = "summary-remaining"
            data_ids = [t.id for t in transactions]

            html = render_to_string(
                "components/table.html",
                {"id": table_id, "fields": fields, "data": data}
            )

            client_debt_qs = ClientDebtRepayment.objects.order_by('-created_at')
            try:
                per_page = int(request.GET.get('cdr_per_page', 25))
                if per_page <= 0:
                    per_page = 25
            except Exception:
                per_page = 25
            page_number = request.GET.get('cdr_page', 1)
            paginator = Paginator(client_debt_qs, per_page)
            page = paginator.get_page(page_number)
            client_debt_repayments = page.object_list

            repayment_fields = [
                {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                {"name": "client", "verbose_name": "Клиент"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                {"name": "comment", "verbose_name": "Комментарий"}
            ]
            repayment_data = []
            for cdr in client_debt_repayments:
                repayment_data.append(type("Row", (), {
                    "created_at": timezone.localtime(cdr.created_at).strftime("%d.%m.%Y %H:%M") if cdr.created_at else "",
                    "client": str(cdr.client) if cdr.client else "",
                    "amount": cdr.amount,
                    "comment": cdr.comment or "",
                })())

            html_client_debt_repayments = render_to_string(
                "components/table.html",
                {"id": "client-debt-repayments-table", "fields": repayment_fields, "data": repayment_data}
            )

            return JsonResponse({
                "html": html,
                "table_id": table_id,
                "data_ids": data_ids,
                "html_client_debt_repayments": html_client_debt_repayments,
                "client_debt_repayments_page": page.number,
                "client_debt_repayments_total_pages": paginator.num_pages,
                "client_debt_repayment_ids": [r.id for r in client_debt_repayments],
            })
        elif value == "Бонусы":
            transactions = Transaction.objects.filter(paid_amount__gt=0)
            fields = [
                {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                {"name": "client", "verbose_name": "Клиент"},
                {"name": "bonus_percentage", "verbose_name": "%", "is_percent": True},
                {"name": "bonus_debt", "verbose_name": "Бонус", "is_amount": True},
            ]
            data = []
            for t in transactions:
                data.append(type("Row", (), {
                    "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else "",
                    "client": str(t.client) if t.client else "",
                    "bonus_percentage": t.bonus_percentage,
                    "bonus_debt": t.bonus_debt,
                })())
            table_id = "summary-bonus"
            data_ids = [t.id for t in transactions]

            html = render_to_string(
                "components/table.html",
                {"id": table_id, "fields": fields, "data": data}
            )

            return JsonResponse({"html": html, "table_id": table_id, "data_ids": data_ids})
        elif value == "Инвесторам":
            transactions = [
                t for t in Transaction.objects.filter(paid_amount__gt=0)
                if getattr(t, 'bonus_debt', 0) == 0
                and getattr(t, 'client_debt', 0) == 0
                and getattr(t, 'profit', 0) > 0
                and (getattr(t, 'profit', 0) - getattr(t, 'returned_to_investor', 0)) > 0
            ]

            cashflows = CashFlow.objects.filter(
                purpose__operation_type=PaymentPurpose.INCOME,
            ).exclude(purpose__name__in=["Оплата", "Внесение инвестора", "Возврат от поставщиков"])

            cashflows = [cf for cf in cashflows if (cf.amount - (cf.returned_to_investor or 0)) > 0]

            class TransactionRow:
                def __init__(self, created_at, client, amount, profit, id, returned_to_investor=0):
                    self.created_at = created_at
                    self.client = client
                    self.amount = amount
                    self.profit = profit
                    self.id = id
                    self.returned_to_investor = returned_to_investor 

            for cf in cashflows:
                transactions.append(TransactionRow(
                    created_at=cf.created_at,
                    client=cf.purpose.name if cf.purpose else "",
                    amount=cf.amount,
                    profit=cf.amount,
                    id=f"cf-{cf.id}",
                    returned_to_investor=cf.returned_to_investor if cf.returned_to_investor is not None else 0
                ))

            fields = [
                {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                {"name": "client", "verbose_name": "Клиент"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                {"name": "profit", "verbose_name": "Прибыль", "is_amount": True},
            ]
            data = []
            for t in transactions:
                data.append(type("Row", (), {
                    "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else "",
                    "client": str(t.client) if t.client else "",
                    "amount": t.amount,
                    "profit": t.profit - t.returned_to_investor,
                })())
            table_id = "summary-profit"
            data_ids = [t.id for t in transactions]

            investor_fields = [
                {"name": "name", "verbose_name": "Инвестор"},
                {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
            ]
            investors = Investor.objects.all()
            investor_data = []
            for inv in investors:
                investor_data.append(type("InvestorRow", (), {
                    "name": inv.name,
                    "balance": inv.balance,
                })())
            investor_ids = [inv.id for inv in investors]
            html_investors = render_to_string(
                "components/table.html",
                {"id": "investors-table", "fields": investor_fields, "data": investor_data}
            )

            investor_operations = InvestorDebtOperation.objects.all()
            operation_fields = [
                {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                {"name": "investor", "verbose_name": "Инвестор"},
                {"name": "operation_type", "verbose_name": "Тип операции"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            ]
            operation_data = []
            for op in investor_operations:
                operation_data.append(type("OperationRow", (), {
                    "created_at": timezone.localtime(op.created_at).strftime("%d.%m.%Y %H:%M") if op.created_at else "",
                    "investor": str(op.investor) if op.investor else "",
                    "amount": op.amount,
                    "operation_type": dict(InvestorDebtOperation.OPERATION_TYPES).get(op.operation_type, ""),
                })())
            operation_table_id = "investor-operations-table"
            html_operations = render_to_string(
                "components/table.html",
                {"id": operation_table_id, "fields": operation_fields, "data": operation_data}
            )

            html = render_to_string(
                "components/table.html",
                {"id": table_id, "fields": fields, "data": data}
            )

            return JsonResponse({
                "html": html,
                "table_id": table_id,
                "data_ids": data_ids,
                "html_investors": html_investors,
                "investor_ids": investor_ids,
                "html_operations": html_operations,
            })

    return JsonResponse({"html": "<div>Нет данных</div>"})


@login_required
def cash_flow_payment_stats(request, supplier_id):
    current_year = datetime.now().year
    months = [i for i in range(1, 13)]

    cashflows = CashFlow.objects.filter(
        supplier_id=supplier_id,
        created_at__year=current_year
    )

    stats = {month: 0 for month in months}
    for cf in cashflows:
        if cf.created_at:
            stats[cf.created_at.month] += float(Decimal(str(cf.amount or 0)))

    return JsonResponse({
        "months": [datetime(current_year, m, 1).strftime('%b') for m in months],
        "values": [stats[m] for m in months]
    })


@forbid_supplier
@login_required
@require_GET
def company_balance_stats(request):
    equipment = BalanceData.objects.filter(name="Оборудование").aggregate(total=Sum("amount"))["total"] or Decimal(0)

    credits_qs = Credit.objects.all().order_by('name')
    credit_rows = [
        type("Row", (), {
            "name": getattr(c, "name", str(c)),
            "amount": getattr(c, "amount", Decimal(0))
        })()
        for c in credits_qs
    ]
    credit_total = sum((getattr(c, "amount", Decimal(0)) or Decimal(0)) for c in credits_qs) if credits_qs else Decimal(0)
    credit_fields = [
        {"name": "name", "verbose_name": "Наименование"},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
    ]
    credit_html = render_to_string("components/table.html", {"id": "credits-table", "fields": credit_fields, "data": credit_rows})

    short_qs = ShortTermLiability.objects.all().order_by('name')
    short_rows = [
        type("Row", (), {
            "name": getattr(s, "name", str(s)),
            "amount": getattr(s, "amount", Decimal(0))
        })()
        for s in short_qs
    ]
    short_total = sum((getattr(s, "amount", Decimal(0)) or Decimal(0)) for s in short_qs) if short_qs else Decimal(0)
    short_fields = [
        {"name": "name", "verbose_name": "Наименование"},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
    ]
    short_html = render_to_string("components/table.html", {"id": "short-term-table", "fields": short_fields, "data": short_rows})

    inventory_qs = InventoryItem.objects.all().order_by('name')
    inventory_rows = []
    for it in inventory_qs:
        qty = getattr(it, "quantity", Decimal(0)) or Decimal(0)
        if isinstance(qty, Decimal):
            try:
                if qty == qty.to_integral():
                    quantity_val = int(qty)
                else:
                    quantity_val = qty.normalize()
            except Exception:
                quantity_val = qty
        else:
            if isinstance(qty, float) and qty.is_integer():
                quantity_val = int(qty)
            else:
                quantity_val = qty

        inventory_rows.append(
            type("Row", (), {
                "name": getattr(it, "name", str(it)),
                "quantity": quantity_val,
                "price": getattr(it, "price", Decimal(0)),
                "amount": getattr(it, "total", getattr(it, "amount", Decimal(0)))
            })()
        )
    inventory_total = sum((getattr(it, "total", getattr(it, "amount", Decimal(0))) or Decimal(0)) for it in inventory_qs) if inventory_qs else Decimal(0)
    inventory_fields = [
        {"name": "name", "verbose_name": "Наименование"},
        {"name": "quantity", "verbose_name": "Количество"},
        {"name": "price", "verbose_name": "Цена за ед.", "is_amount": True},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
    ]
    inventory_html = render_to_string("components/table.html", {"id": "inventory-table", "fields": inventory_fields, "data": inventory_rows})

    debtors = []
    total_debtors = Decimal(0)
    for branch in Supplier.objects.exclude(branch=None).values_list("branch__id", "branch__name").distinct():
        branch_id, branch_name = branch
        if branch_name != "Филиал 1" and branch_name != "Наши ИП":
            branch_debt = sum(
                (t.supplier_debt or Decimal(0))
                for t in Transaction.objects.filter(supplier__branch_id=branch_id, paid_amount__gt=0)
            )
            debtors.append({"branch": branch_name, "amount": branch_debt})
            total_debtors += branch_debt

    safe_amount = SupplierAccount.objects.filter(
        supplier__visible_in_summary=True
    ).aggregate(total=Sum("balance"))["total"] or Decimal(0)

    cash_account = Account.objects.filter(name__iexact="Наличные").first()
    cash_balance = Decimal(cash_account.balance) if cash_account and cash_account.balance is not None else Decimal(0)

    safe_amount = Decimal(safe_amount) + cash_balance

    bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))
    total_remaining = sum((t.client_debt_paid or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))
    
    transactionsInvestors = [
        t for t in Transaction.objects.filter(paid_amount__gt=0)
        if getattr(t, 'bonus_debt', 0) == 0
        and getattr(t, 'client_debt', 0) == 0
        and getattr(t, 'profit', 0) > 0
    ]
    cashflows = CashFlow.objects.filter(
        purpose__operation_type=PaymentPurpose.INCOME
    ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

    total_profit_decimal = sum(
        (Decimal(str(getattr(t, 'profit', 0) or 0)) - Decimal(str(getattr(t, 'returned_to_investor', 0) or 0)))
        for t in transactionsInvestors
    ) + sum(
        (Decimal(str(cf.amount or 0)) - Decimal(str(cf.returned_to_investor or 0)))
        for cf in cashflows
    )

    total_summary_debts = (bonuses or Decimal(0)) + (total_remaining or Decimal(0)) + (total_profit_decimal or Decimal(0))

    client_debts = sum((t.client_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0).all())

    investors_qs = Investor.objects.all().order_by('name')
    investors_rows = [
        type("Row", (), {
            "name": inv.name,
            "amount": inv.balance or Decimal(0)
        })()
        for inv in investors_qs
    ]
    investors_total = sum((inv.balance or Decimal(0)) for inv in investors_qs) if investors_qs else Decimal(0)
    investor_fields = [
        {"name": "name", "verbose_name": "Инвестор"},
        {"name": "amount", "verbose_name": "Баланс", "is_amount": True},
    ]
    investors_html = render_to_string("components/table.html", {"id": "investors-table", "fields": investor_fields, "data": investors_rows})

    undistributed_profit = Decimal(0)

    assets_total = equipment + inventory_total + total_debtors + safe_amount

    provisional_liabilities = credit_total + short_total + total_summary_debts + investors_total + undistributed_profit

    current_capital = assets_total - provisional_liabilities

    liabilities_total = provisional_liabilities + current_capital

    current_year = datetime.now().year
    capitals = []

    MONTHS_RU = [
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"
    ]
    months = [MONTHS_RU[month-1] for month in range(1, 13)]

    for month in range(1, 13):
        capital = float(get_monthly_capital(current_year, month))
        capitals.append(capital)

    if capitals:
        total_capital = round(sum(capitals) / len(capitals), 1)
    else:
        total_capital = 0

    data = {
        "non_current_assets": {
            "total": equipment,
            "items": [{"name": "Оборудование", "amount": equipment}]
        },
        "current_assets": {
            "inventory": {"total": inventory_total, "html": inventory_html},
            "debtors": {"total": total_debtors, "items": debtors},
            "cash": {"total": safe_amount,
                     "items": [{"name": "Счета, Карты и Сейф", "amount": safe_amount}]},
        },
        "assets": assets_total,
        "liabilities": {
            "total": liabilities_total,
            "items": [
                {"name": "Кредит", "amount": credit_total, "html": credit_html},
                {
                    "name": "Кредиторская задолженность",
                    "amount": total_summary_debts,
                    "items": [
                        {"name": "Бонусы", "amount": bonuses},
                        {"name": "Выдачи клиентам", "amount": total_remaining},
                        {"name": "Инвесторам", "amount": total_profit_decimal},
                    ],
                },
                {"name": "Краткосрочные обязательства", "amount": short_total, "html": short_html},
                {
                    "name": "Вложения инвесторов",
                    "amount": investors_total,
                    "items": [{"name": inv.name, "amount": inv.balance or Decimal(0)} for inv in investors_qs],
                    "html": investors_html
                },
                {"name": "Нераспределенная прибыль", "amount": undistributed_profit},
            ],
        },
        "capital": current_capital,
        "capitals_by_month": {
            "months": months,
            "capitals": capitals,
            "total": total_capital
        },
        "ids":{
            "credit_ids": [c.id for c in credits_qs],
            "short_ids": [s.id for s in short_qs],
            "inventory_ids": [i.id for i in inventory_qs],
        }
    }
    return JsonResponse(data, safe=False)



@forbid_supplier
@login_required
@require_GET
def company_balance_stats_by_month(request):
    current_year = datetime.now().year
    current_month = datetime.now().month
    capitals = []
    months = []
    for month in range(1, 13):
        if month == current_month:
            capital = float(get_monthly_capital(current_year, month))
        else:
            mc = MonthlyCapital.objects.filter(year=current_year, month=month).first()
            capital = float(mc.capital) if mc else 0
        capitals.append(capital)
        months.append(datetime(current_year, month, 1).strftime('%B'))
    return JsonResponse({"months": months, "capitals": capitals})


def get_monthly_capital(year, month):
    """
    Новый алгоритм:
    - Берёт капитал предыдущего месяца (MonthlyCapital.year=prev_year, month=prev_month). Если нет — считает по данным инвесторов на конец предыдущего месяца.
    - Берёт капитал текущего месяца: если MonthlyCapital для этого месяца есть — использует его, иначе считает по данным инвесторов на конец этого месяца.
    - Средний капитал = (prev_capital + curr_capital) / 2.
    - Прибыль за месяц = сумма profit по транзакциям в заданном месяце.
    - Возвращает процент = profit / average_capital * 100 (округлён до 1 знака). При нулевом среднем капитале возвращает 0.
    """
    last_day = monthrange(year, month)[1]
    dt_start = timezone.make_aware(datetime(year, month, 1, 0, 0, 0))
    dt_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1

    def _investors_total_up_to(dt):
        total = Investor.objects.filter(created_at__lte=dt).aggregate(total=Sum('balance'))['total'] or Decimal(0)
        return Decimal(total)

    prev_obj = MonthlyCapital.objects.filter(year=prev_year, month=prev_month).first()
    if prev_obj and prev_obj.capital is not None:
        prev_cap = Decimal(prev_obj.capital)
    else:
        prev_last_day = monthrange(prev_year, prev_month)[1]
        prev_dt_end = timezone.make_aware(datetime(prev_year, prev_month, prev_last_day, 23, 59, 59))
        prev_cap = _investors_total_up_to(prev_dt_end)

    curr_obj = MonthlyCapital.objects.filter(year=year, month=month).first()
    if curr_obj and curr_obj.capital is not None:
        curr_cap = Decimal(curr_obj.capital)
    else:
        curr_cap = _investors_total_up_to(dt_end)

    try:
        avg_cap = (Decimal(prev_cap) + Decimal(curr_cap)) / Decimal(2)
    except Exception:
        avg_cap = Decimal(0)

    transactions = Transaction.objects.filter(created_at__range=(dt_start, dt_end)).select_related()
    profit_total = sum(
        (Decimal(str(getattr(t, 'profit', 0) or 0)) for t in transactions),
        Decimal(0)
    )

    if avg_cap > 0 and profit_total != 0:
        capital_percent = float(profit_total) / float(avg_cap) * 100.0
    else:
        capital_percent = 0.0

    return round(capital_percent, 1)

def calculate_and_save_monthly_capital(year, month):
    last_day = monthrange(year, month)[1]
    dt_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

    total_capital = Investor.objects.filter(created_at__lte=dt_end).aggregate(
        total=Sum('balance')
    )['total'] or 0

    MonthlyCapital.objects.update_or_create(
        year=year, month=month,
        defaults={'capital': total_capital, 'calculated_at': datetime.now()}
    )


@forbid_supplier
@login_required
def users(request):
    is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False
    if not is_admin:
        raise PermissionDenied

    users = User.objects.exclude(username="admin_hidden")

    context = {
        "fields": get_user_fields(),
        "data": users,
        "data_ids": [t.id for t in users],
    }

    return render(request, "main/users.html", context)


def get_user_fields():
    excluded = [
        "id",
        "data_joined",
        "supplier",
        "password",
        "last_login",
        "is_superuser",
        "is_staff",
        "email",
        "branch",
    ]
    fields = get_model_fields(
        User,
        excluded_fields=excluded,
    )

    insertions = [
        (0, {"name": "email", "verbose_name": "Почта", }),
    ]

    for pos, field in insertions:
        fields.insert(pos, field)

    return fields


@forbid_supplier
@login_required
def user_detail(request, pk: int):
    user = get_object_or_404(User, id=pk)
    data = model_to_dict(user)

    data.pop("password", None)
    
    return JsonResponse({"data": data})


@forbid_supplier
@login_required
@require_http_methods(["POST"])
def user_create(request):
    try:
        with transaction.atomic():
            email = request.POST.get("email")
            username = request.POST.get("username")
            password = request.POST.get("password")
            user_type_id = request.POST.get("user_type")
            is_active = request.POST.get("is_active") == "on"
            branch_id = request.POST.get("branch")

            if not all([username, password, user_type_id]):
                return JsonResponse(
                    {"status": "error", "message": "Логин, пароль и тип пользователя обязательны"},
                    status=400,
                )

            if username == "admin_hidden":
                return JsonResponse(
                    {"status": "error", "message": "Недопустимый логин"},
                    status=400,
                )

            if User.objects.filter(username=username).exists():
                return JsonResponse(
                    {"status": "error", "message": "Пользователь с таким логином уже существует"},
                    status=400,
                )

            user_type = get_object_or_404(UserType, id=user_type_id)
            branch = None
            if user_type.name == "Филиал":
                if not branch_id or branch_id == 'null':
                    return JsonResponse(
                        {"status": "error", "message": "Для типа 'Филиал' необходимо выбрать филиал"},
                        status=400,
                    )
                branch = get_object_or_404(Branch, id=branch_id)

            user = User.objects.create(
                email=email,
                username=username,
                user_type=user_type,
                is_active=is_active,
                branch=branch
            )
            user.set_password(password)
            user.save()

            context = {
                "item": user,
                "fields": get_user_fields(),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": user.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@forbid_supplier
@login_required
@require_http_methods(["POST"])
def user_edit(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID пользователя не указан"},
                    status=400,
                )

            user = get_object_or_404(User, id=pk)

            email = request.POST.get("email")
            username = request.POST.get("username")
            password = request.POST.get("password")
            user_type_id = request.POST.get("user_type")
            is_active = request.POST.get("is_active") == "on"
            branch_id = request.POST.get("branch")

            if not all([username, user_type_id]):
                return JsonResponse(
                    {"status": "error", "message": "Логин и тип пользователя обязательны"},
                    status=400,
                )

            if username == "admin_hidden":
                return JsonResponse(
                    {"status": "error", "message": "Недопустимый логин"},
                    status=400,
                )

            if User.objects.exclude(pk=user.pk).filter(username=username).exists():
                return JsonResponse(
                    {"status": "error", "message": "Пользователь с таким логином уже существует"},
                    status=400,
                )

            user_type = get_object_or_404(UserType, id=user_type_id)
            branch = None
            if user_type.name == "Филиал":
                if not branch_id or branch_id == 'null':
                    return JsonResponse(
                        {"status": "error", "message": "Для типа 'Филиал' необходимо выбрать филиал"},
                        status=400,
                    )
                branch = get_object_or_404(Branch, id=branch_id)

            user.email = email
            user.username = username
            if password:
                user.set_password(password)
            user.user_type = user_type
            user.is_active = is_active
            user.branch = branch
            user.save()

            context = {
                "item": user,
                "fields": get_user_fields(),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": user.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@forbid_supplier
@login_required
@require_http_methods(["POST"])
def user_delete(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID пользователя не указан"},
                    status=400,
                )

            user = get_object_or_404(User, id=pk)
            user.delete()

            return JsonResponse({
                "status": "success",
                "message": "Пользователь успешно удален",
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
def user_types(request):
    types = UserType.objects.exclude(name="Поставщик")

    type_data = [
        {"id": acc.id, "name": acc.name} for acc in types
    ]
    return JsonResponse(type_data, safe=False)


@forbid_supplier
@login_required
def repay_supplier_debt(request, pk: int):
    supplier_debt_repay = get_object_or_404(SupplierDebtRepayment, id=pk)
    data = model_to_dict(supplier_debt_repay)
    return JsonResponse({"data": data})


@forbid_supplier
@login_required
@require_http_methods(["POST"])
def edit_supplier_debt_repayment(request, pk=None):
    try:
        with transaction.atomic():
            pk = pk or request.POST.get("id")
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID выдачи не указано"},
                    status=400,
                )

            debt_repay = get_object_or_404(SupplierDebtRepayment, id=pk)

            comment = request.POST.get("comment", "").strip()

            debt_repay.comment = comment
            debt_repay.save()

            context = {
                "item": debt_repay,
                "fields": [
                    {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                    {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                    {"name": "comment", "verbose_name": "Комментарий"}
                ]
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": debt_repay.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@forbid_supplier
@login_required
def exchange(request):
    fields = [
        {"name": "source_supplier", "verbose_name": "От кого"},
        {"name": "source_account", "verbose_name": "С какого счета"},
        {"name": "destination_supplier", "verbose_name": "Кому"},
        {"name": "destination_account", "verbose_name": "На какой счет"},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True}
    ]

    from_us_transfers = list(
        MoneyTransfer.objects.filter(transfer_type="from_us").order_by('-is_counted')
    )
    to_us_transfers = list(
        MoneyTransfer.objects.filter(transfer_type="to_us")
    )

    total_from_us = sum(t.amount for t in from_us_transfers if t.is_counted)
    total_to_us = sum(t.amount for t in to_us_transfers)

    context = {
        "fields": fields,
        "data": {
            "from_us": from_us_transfers,
            "to_us": to_us_transfers,
        },
        "data_ids": {
            "from_us": [t.id for t in from_us_transfers],
            "to_us": [t.id for t in to_us_transfers],
            "counted_from_us": [t.id for t in from_us_transfers if t.is_counted],
            "counted_to_us": [t.id for t in to_us_transfers if not t.is_completed],
            "from_us_completed": [t.id for t in from_us_transfers if t.is_completed],
            "to_us_completed": [t.id for t in to_us_transfers if t.is_completed],
        },
        "totals": {
            "from_us": total_from_us,
            "to_us": total_to_us,
        }
    }

    return render(request, "main/exchange.html", context)


@forbid_supplier
@login_required
@require_http_methods(["POST"])
def complete_all_unfinished_transfers(request):
    try:
        with transaction.atomic():
            unfinished_transfers = MoneyTransfer.objects.filter(is_completed=False)
            count = unfinished_transfers.update(is_completed=True)
            return JsonResponse({
                "status": "success",
                "message": f"Завершено {count} переводов",
                "completed_count": count,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@forbid_supplier
@login_required
def money_logs(request):
    cash_flows = CashFlow.objects.select_related('account', 'supplier', 'purpose', 'transaction').all()
    debt_repayments = SupplierDebtRepayment.objects.select_related('supplier').all()
    investor_ops = InvestorDebtOperation.objects.select_related('investor').filter(operation_type="profit")

    class LogRow:
        def __init__(self, dt, type, info, amount, comment="", created_by=None):
            self.dt = dt
            self.date = timezone.localtime(dt).strftime("%d.%m.%Y %H:%M") if dt else ""
            self.type = type
            self.info = info
            self.amount = amount
            self.comment = comment
            self.created_by = created_by

    rows = []

    for cf in cash_flows:
        rows.append(LogRow(
            dt=cf.created_at,
            type="Движение ДС",
            info=f"Счет: {cf.account}, Поставщик: {cf.supplier}, Назначение: {cf.purpose}",
            amount=cf.amount,
            comment=cf.comment or "",
            created_by=str(cf.created_by) if cf.created_by else ""
        ))

    for dr in debt_repayments:
        rows.append(LogRow(
            dt=dr.created_at,
            type="Погашение долга",
            info=f"Поставщик: {dr.supplier}",
            amount=dr.amount,
            comment=dr.comment or "",
            created_by=str(dr.created_by) if dr.created_by else ""
        ))

    for io in investor_ops:
        rows.append(LogRow(
            dt=io.created_at,
            type=f"Инвестор: {io.get_operation_type_display()}",
            info=f"Инвестор: {io.investor}",
            amount=io.amount,
            comment="",
            created_by=str(io.created_by) if io.created_by else ""
        ))

    rows.sort(key=lambda x: x.dt or timezone.make_aware(datetime.min), reverse=True)

    fields = [
        {"name": "date", "verbose_name": "Дата"},
        {"name": "type", "verbose_name": "Тип"},
        {"name": "info", "verbose_name": "Инфо"},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
        {"name": "comment", "verbose_name": "Комментарий"},
        {"name": "created_by", "verbose_name": "Создал"}
    ]

    page_number = request.GET.get('page') or request.POST.get('page')
    try:
        page_number = int(page_number) if page_number is not None else 1
    except Exception:
        page_number = 1

    paginator = Paginator(rows, 200)
    page = paginator.get_page(page_number)

    html = render_to_string("components/table.html", {
        "id": "money-logs-table",
        "fields": fields,
        "data": page.object_list,
    })

    return JsonResponse({
        "html": html,
        "total_pages": paginator.num_pages,
        "current_page": page.number,
    })

@forbid_supplier
@login_required
def money_logs_list(request):
    page_number = request.GET.get('page', 1)
    try:
        page_number = int(page_number)
    except Exception:
        page_number = 1

    per_page = request.GET.get('per_page', 200)
    try:
        per_page = int(per_page)
        if per_page <= 0:
            per_page = 200
    except Exception:
        per_page = 200

    offset = (page_number - 1) * per_page

    cash_flows = CashFlow.objects.select_related(
        'account', 'supplier', 'purpose', 'created_by'
    ).order_by('-created_at')

    investor_ops = InvestorDebtOperation.objects.select_related(
        'investor', 'created_by'
    ).filter(operation_type='profit').order_by('-created_at')

    combined_items = list(cash_flows) + list(investor_ops)
    
    combined_items.sort(key=lambda x: x.created_at, reverse=True)

    total_count = len(combined_items)
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    page_items = combined_items[offset:offset + per_page]

    rows = []
    for item in page_items:
        if isinstance(item, CashFlow):
            cf = item
            purpose_name = cf.purpose.name if cf.purpose else ""
            
            if purpose_name == "Погашение долга поставщика":
                type_label = "Погашение долга поставщика"
                info = f"Поставщик: {cf.supplier.name if cf.supplier else ''}, Счет: {cf.account.name if cf.account else ''}"
            elif purpose_name == "Возврат от поставщиков":
                type_label = "Погашение долга поставщика"
                info = f"Поставщик: {cf.supplier.name if cf.supplier else ''}, Счет: {cf.account.name if cf.account else ''}"
            elif purpose_name == "Погашение долга клиента":
                type_label = "Погашение долга клиента"
                client_name = ""
                try:
                    cdr = ClientDebtRepayment.objects.filter(cash_flow=cf).first()
                    if cdr and cdr.client:
                        client_name = cdr.client.name
                except Exception:
                    pass
                info = f"Клиент: {client_name}, Счет: {cf.account.name if cf.account else ''}"
            elif purpose_name in ["Забор инвестора", "Внесение инвестора"]:
                operation_map = {
                    'Забор инвестора': 'Забор',
                    'Внесение инвестора': 'Внесение',
                }
                type_label = f"Инвестор: {operation_map.get(purpose_name, purpose_name)}"
                info = f"Счет: {cf.account.name if cf.account else ''}"
                if cf.supplier:
                    info += f", Поставщик: {cf.supplier.name}"
            elif purpose_name == "Выдача бонусов":
                type_label = "Выдача бонусов"
                parts = []
                if cf.account:
                    parts.append(f"Счет: {cf.account.name}")
                info = ", ".join(parts)
            elif purpose_name == "ДТ":
                type_label = "Выдача клиенту ДТ"
                parts = []
                if cf.account:
                    parts.append(f"Счет: {cf.account.name}")
                info = ", ".join(parts)
            else:
                type_label = "Движение ДС"
                parts = []
                if cf.account:
                    parts.append(f"Счет: {cf.account.name}")
                if cf.supplier:
                    parts.append(f"Поставщик: {cf.supplier.name}")
                if purpose_name:
                    parts.append(f"Назначение: {purpose_name}")
                info = ", ".join(parts)

            obj = type("LogRow", (), {})()
            obj.id = f"cf-{cf.id}"
            obj.dt = cf.created_at
            obj.date = timezone.localtime(cf.created_at).strftime("%d.%m.%Y %H:%M") if cf.created_at else ""
            obj.type = type_label
            obj.info = info
            obj.amount = cf.amount
            obj.comment = cf.comment or ""
            obj.created_by = cf.created_by.username if cf.created_by else ""

            rows.append(obj)

        elif isinstance(item, InvestorDebtOperation):
            io = item
            type_label = "Инвестор: Прибыль"
            info = f"Инвестор: {io.investor.name if io.investor else ''}"

            obj = type("LogRow", (), {})()
            obj.id = f"io-{io.id}"
            obj.dt = io.created_at
            obj.date = timezone.localtime(io.created_at).strftime("%d.%m.%Y %H:%M") if io.created_at else ""
            obj.type = type_label
            obj.info = info
            obj.amount = io.amount
            obj.comment = ""
            obj.created_by = io.created_by.username if io.created_by else ""

            rows.append(obj)

    html = "".join(
        render_to_string("components/table_row.html", {"item": row, "fields": [
            {"name": "date", "verbose_name": "Дата", "is_date": True},
            {"name": "type", "verbose_name": "Тип", "is_relation": True},
            {"name": "info", "verbose_name": "Инфо"},
            {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            {"name": "comment", "verbose_name": "Комментарий"},
            {"name": "created_by", "verbose_name": "Создал", "is_relation": True},
        ]})
        for row in rows
    )

    money_log_ids = [row.id for row in rows]

    return JsonResponse({
        "html": html,
        "context": {
            "current_page": page_number,
            "total_pages": total_pages,
            "money_log_ids": money_log_ids,
        },
    })

@forbid_supplier
@login_required
def close_investor_debt(request, pk):
    try:
        with transaction.atomic():
            ids_raw = request.POST.get("ids")
            amount = clean_currency(request.POST.get("amount"))
            investor_id = request.POST.get("investor_select")

            if not ids_raw or not amount or not investor_id:
                return JsonResponse({"status": "error", "message": "Не указаны все параметры"}, status=400)

            try:
                amount_value = Decimal(amount)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректная сумма"}, status=400)

            if amount_value <= 0:
                return JsonResponse({"status": "error", "message": "Сумма должна быть больше нуля"}, status=400)

            try:
                ids = json.loads(ids_raw) if ids_raw else []
            except Exception:
                ids = []

            investor = get_object_or_404(Investor, id=investor_id)
            remaining = amount_value
            closed = []
            changed_html_rows = []

            for item_id in ids:
                if remaining <= 0:
                    break
                if str(item_id).startswith("cf-"):
                    cf_id = item_id.replace("cf-", "")
                    obj = get_object_or_404(CashFlow, id=cf_id)
                    debt = Decimal(obj.amount) - (obj.returned_to_investor or Decimal(0))
                    repay = min(debt, remaining)
                    if repay > 0:
                        obj.returned_to_investor = (obj.returned_to_investor or Decimal(0)) + repay
                        obj.save()
                        closed.append({"id": item_id, "closed": float(repay)})
                        remaining -= repay
                        if repay < debt:
                            row = type("Row", (), {
                                "created_at": timezone.localtime(obj.created_at).strftime("%d.%m.%Y") if obj.created_at else "",
                                "client": obj.purpose.name if obj.purpose else "",
                                "amount": obj.amount,
                                "profit": obj.amount - obj.returned_to_investor,
                            })()
                            fields = [
                                {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                                {"name": "client", "verbose_name": "Клиент"},
                                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                                {"name": "profit", "verbose_name": "Прибыль", "is_amount": True},
                            ]
                            html_row = render_to_string("components/table_row.html", {"item": row, "fields": fields})
                            changed_html_rows.append({"id": item_id, "html": html_row})
                else:
                    t = get_object_or_404(Transaction, id=item_id)
                    debt = Decimal(t.profit) - (t.returned_to_investor or Decimal(0))
                    repay = min(debt, remaining)
                    if repay > 0:
                        t.returned_to_investor = (t.returned_to_investor or Decimal(0)) + repay
                        t.save()
                        closed.append({"id": item_id, "closed": float(repay)})
                        remaining -= repay
                        if repay < debt:
                            row = type("Row", (), {
                                "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else "",
                                "client": str(t.client) if t.client else "",
                                "amount": t.amount,
                                "profit": t.profit - t.returned_to_investor,
                            })()
                            fields = [
                                {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                                {"name": "client", "verbose_name": "Клиент"},
                                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                                {"name": "profit", "verbose_name": "Прибыль", "is_amount": True},
                            ]
                            html_row = render_to_string("components/table_row.html", {"item": row, "fields": fields})
                            changed_html_rows.append({"id": item_id, "html": html_row})

            amount_closed = amount_value - remaining
            investor.balance += amount_closed
            investor.save()

            user = request.user if request.user.is_authenticated else None

            investorDebtOperation = InvestorDebtOperation.objects.create(
                investor=investor,
                amount=amount_closed,
                operation_type="deposit",
                created_by=user
            )

            investorDebtOperation.created_at = timezone.localtime(investorDebtOperation.created_at).strftime("%d.%m.%Y %H:%M") if investorDebtOperation.created_at else ""
            investorDebtOperation.operation_type = (
                "Внесение" if investorDebtOperation.operation_type == "deposit"
                else "Забор" if investorDebtOperation.operation_type == "withdrawal"
                else "Прибыль" if investorDebtOperation.operation_type == "profit"
                else investorDebtOperation.operation_type
            )
            html_investor_debt_operation = render_to_string("components/table_row.html", {
                "item": investorDebtOperation,
                "fields": [
                    {"name": "created_at", "verbose_name": "Дата", "is_date": True},
                    {"name": "investor", "verbose_name": "Инвестор"},
                    {"name": "operation_type", "verbose_name": "Тип операции"},
                    {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                ]
            })

            investor_fields = [
                {"name": "name", "verbose_name": "Инвестор"},
                {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
            ]
            investor_row = type("InvestorRow", (), {
                "name": investor.name,
                "balance": investor.balance,
            })()
            html_investor_row = render_to_string("components/table_row.html", {"item": investor_row, "fields": investor_fields})

            return JsonResponse({
                "status": "success",
                "closed": closed,
                "amount_closed": float(amount_closed),
                "amount_left": float(remaining),
                "changed_html_rows": changed_html_rows,
                "html_investor_debt_operation": html_investor_debt_operation,
                "html_investor_row": html_investor_row,
                "investor_id": investor.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@login_required
@require_http_methods(["GET"])
def get_hidden_rows(request):
    table = request.GET.get("table")
    if not table:
        return JsonResponse({"status": "error", "message": "Не указано имя таблицы"}, status=400)
    hidden, _ = HiddenRows.objects.get_or_create(user=request.user, table=table)
    return JsonResponse({"hidden_ids": hidden.hidden_ids})


@login_required
@require_http_methods(["POST"])
def set_hidden_rows(request):
    try:
        data = json.loads(request.body)
        table = data.get("table")
        hidden_ids = data.get("hidden_ids")
        page_ids = data.get("page_ids", None)
    except Exception:
        table = request.POST.get("table")
        hidden_ids = request.POST.get("hidden_ids")
        page_ids = request.POST.getlist("page_ids") if request.POST.get("page_ids") else None

    if not table or hidden_ids is None:
        return JsonResponse({"status": "error", "message": "Не указаны параметры"}, status=400)

    try:
        if isinstance(hidden_ids, str):
            hidden_ids_list = json.loads(hidden_ids)
        else:
            hidden_ids_list = hidden_ids
    except Exception:
        hidden_ids_list = []

    try:
        if page_ids is None:
            page_ids_list = None
        elif isinstance(page_ids, str):
            page_ids_list = json.loads(page_ids)
        else:
            page_ids_list = page_ids
    except Exception:
        page_ids_list = None

    hidden_obj, _ = HiddenRows.objects.get_or_create(user=request.user, table=table)
    existing_ids = set(map(str, hidden_obj.hidden_ids or []))

    if page_ids_list is not None:
        page_set = set(map(str, page_ids_list))
        incoming_set = set(map(str, hidden_ids_list))
        new_set = (existing_ids - page_set) | incoming_set
        if not new_set:
            hidden_obj.delete()
            return JsonResponse({"status": "success", "hidden_ids": []})
        hidden_obj.hidden_ids = sorted(list(new_set), key=lambda x: int(x) if str(x).isdigit() else x)
        hidden_obj.save()
        return JsonResponse({"status": "success", "hidden_ids": hidden_obj.hidden_ids})

    incoming_set = set(map(str, hidden_ids_list))
    if not incoming_set:
        HiddenRows.objects.filter(user=request.user, table=table).delete()
        return JsonResponse({"status": "success", "hidden_ids": []})

    merged = existing_ids | incoming_set
    hidden_obj.hidden_ids = sorted(list(merged), key=lambda x: int(x) if str(x).isdigit() else x)
    hidden_obj.save()
    return JsonResponse({"status": "success", "hidden_ids": hidden_obj.hidden_ids})


@login_required
@require_http_methods(["POST"])
def clear_hidden_rows(request):
    table = request.POST.get("table")
    if not table:
        return JsonResponse({"status": "error", "message": "Не указано имя таблицы"}, status=400)
    HiddenRows.objects.filter(user=request.user, table=table).delete()
    return JsonResponse({"status": "success"})

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def investor_debt_operation(request, pk: int):
    investor_id = pk
    operation_type = request.POST.get("type")
    supplier_id = request.POST.get("supplier")
    account_id = request.POST.get("account")
    amount_raw = request.POST.get("amount")

    if not investor_id or not operation_type or not account_id or not amount_raw:
        return JsonResponse({"status": "error", "message": "Не указаны все параметры"}, status=400)

    amount_clean = clean_currency(amount_raw)
    try:
        amount_value = Decimal(amount_clean)
    except Exception:
        return JsonResponse({"status": "error", "message": "Некорректная сумма"}, status=400)

    if amount_value <= 0:
        return JsonResponse({"status": "error", "message": "Сумма должна быть больше нуля"}, status=400)

    investor = get_object_or_404(Investor, id=investor_id)
    
    if str(account_id) == "0":
        account = Account.objects.filter(name__iexact="Наличные").first()
        if not account:
            return JsonResponse({"status": "error", "message": "Счет 'Наличные' не найден"}, status=400)
    else:
        account = get_object_or_404(Account, id=account_id)

    is_cash_account = account.name and account.name.lower() == "наличные"

    if supplier_id and is_cash_account:
        return JsonResponse({"status": "error", "message": "Нельзя одновременно выбрать поставщика и счет 'Наличные'"}, status=400)

    user = request.user
    operation_obj = None

    if operation_type == "contribution":
        if not supplier_id and is_cash_account:
            account.balance = F('balance') + amount_value
            account.save(update_fields=['balance'])
            account.refresh_from_db(fields=['balance'])

            purpose = PaymentPurpose.objects.filter(name="Внесение инвестора").first()
            if not purpose:
                purpose = PaymentPurpose.objects.create(name="Внесение инвестора", operation_type=PaymentPurpose.INCOME)
            
            CashFlow.objects.create(
                account=account,
                supplier=None,
                amount=amount_value,
                purpose=purpose,
                comment=f"Внесение инвестора {investor.name}",
                created_by=user
            )

            investor.balance = (investor.balance or Decimal(0)) + amount_value
            investor.save()

            operation_obj = InvestorDebtOperation.objects.create(
                investor=investor,
                operation_type="deposit",
                amount=amount_value,
                created_by=user
            )
        elif supplier_id:
            supplier = get_object_or_404(Supplier, id=supplier_id)

            supplier_account, _ = SupplierAccount.objects.get_or_create(
                supplier=supplier,
                account=account,
                defaults={'balance': Decimal(0)}
            )

            supplier_account.balance = (supplier_account.balance or Decimal(0)) + amount_value
            supplier_account.save()

            purpose = PaymentPurpose.objects.filter(name="Внесение инвестора").first()
            if not purpose:
                purpose = PaymentPurpose.objects.create(name="Внесение инвестора", operation_type=PaymentPurpose.INCOME)
            
            CashFlow.objects.create(
                account=account,
                supplier=supplier,
                amount=amount_value,
                purpose=purpose,
                comment=f"Внесение инвестора {investor.name}",
                created_by=user
            )

            investor.balance = (investor.balance or Decimal(0)) + amount_value
            investor.save()

            operation_obj = InvestorDebtOperation.objects.create(
                investor=investor,
                operation_type="deposit",
                amount=amount_value,
                created_by=user
            )
        else:
            return JsonResponse({"status": "error", "message": "Для внесения необходимо указать поставщика или выбрать счет 'Наличные'"}, status=400)

    elif operation_type == "withdrawal":
        supplier = None
        supplier_account = None
        if supplier_id:
            supplier = get_object_or_404(Supplier, id=supplier_id)
            supplier_account = SupplierAccount.objects.filter(supplier=supplier, account=account).first()
            if not supplier_account:
                return JsonResponse({"status": "error", "message": "Счет поставщика не найден"}, status=400)
            if (supplier_account.balance or Decimal(0)) < amount_value:
                return JsonResponse({"status": "error", "message": "Недостаточно средств на счете поставщика"}, status=400)

        if supplier_account:
            supplier_account.balance = (supplier_account.balance or Decimal(0)) - amount_value
            supplier_account.save()
        else:
            if (account.balance or Decimal(0)) < amount_value:
                return JsonResponse({"status": "error", "message": "Недостаточно средств на счете"}, status=400)
            account.balance = (account.balance or Decimal(0)) - amount_value
            account.save()

        if (investor.balance or Decimal(0)) < amount_value:
            return JsonResponse({"status": "error", "message": "Недостаточно средств у инвестора"}, status=400)

        purpose = PaymentPurpose.objects.filter(name="Забор инвестора").first()
        if not purpose:
            purpose = PaymentPurpose.objects.create(name="Забор инвестора", operation_type=PaymentPurpose.EXPENSE)
        CashFlow.objects.create(
            account=account,
            supplier=supplier if supplier_id else None,
            amount=-amount_value,
            purpose=purpose,
            comment=f"Забор инвестора {investor.name}",
            created_by=user
        )

        investor.balance = (investor.balance or Decimal(0)) - amount_value
        investor.save()

        operation_obj = InvestorDebtOperation.objects.create(
            investor=investor,
            operation_type="withdrawal",
            amount=amount_value,
            created_by=user
        )
    else:
        return JsonResponse({"status": "error", "message": "Некорректный тип операции"}, status=400)

    operation_obj.created_at = timezone.localtime(operation_obj.created_at).strftime("%d.%m.%Y %H:%M") if operation_obj.created_at else ""
    operation_obj.operation_type = (
        "Внесение" if operation_obj.operation_type == "deposit"
        else "Забор" if operation_obj.operation_type == "withdrawal"
        else "Прибыль" if operation_obj.operation_type == "profit"
        else operation_obj.operation_type
    )

    html_operation = render_to_string("components/table_row.html", {
        "item": operation_obj,
        "fields": [
            {"name": "created_at", "verbose_name": "Дата", "is_date": True},
            {"name": "investor", "verbose_name": "Инвестор"},
            {"name": "operation_type", "verbose_name": "Тип операции"},
            {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
        ]
    })

    investor_row = type("InvestorRow", (), {
        "name": investor.name,
        "balance": investor.balance,
    })()
    html_investor = render_to_string("components/table_row.html", {
        "item": investor_row,
        "fields": [
            {"name": "name", "verbose_name": "Инвестор"},
            {"name": "balance", "verbose_name": "Баланс", "is_amount": True},
        ]
    })

    return JsonResponse({
        "status": "success",
        "html_operation": html_operation,
        "html_investor": html_investor,
        "operation_id": operation_obj.id,
        "investor_id": investor.id,
    })

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def add_balance_item(request):
    try:
        type_ = request.POST.get("operation_type")
        name = (request.POST.get("name") or "").strip()
        if not type_ or not name:
            return JsonResponse({"status": "error", "message": "Не указаны обязательные параметры"}, status=400)

        def parse_decimal(v):
            try:
                return Decimal(str(clean_currency(v))) if v is not None else Decimal(0)
            except Exception:
                return Decimal(0)

        created_obj = None
        row_html = ""
        if type_ == "inventory":
            qty_raw = request.POST.get("quantity")
            price_raw = request.POST.get("price")
            if qty_raw is None or price_raw is None:
                return JsonResponse({"status": "error", "message": "Не заданы quantity или price"}, status=400)
            try:
                quantity = Decimal(str(qty_raw).replace(",", "."))
                price = parse_decimal(price_raw)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректные значения quantity/price"}, status=400)
            item = InventoryItem.objects.create(name=name, quantity=quantity, price=price)
            created_obj = item

            inventory_fields = [
                {"name": "name", "verbose_name": "Наименование"},
                {"name": "quantity", "verbose_name": "Количество"},
                {"name": "price", "verbose_name": "Цена за ед.", "is_amount": True},
                {"name": "total", "verbose_name": "Сумма", "is_amount": True},
            ]
            row_html = render_to_string("components/table_row.html", {"item": item, "fields": inventory_fields})

        elif type_ == "credit":
            amount_raw = request.POST.get("amount")
            if amount_raw is None:
                return JsonResponse({"status": "error", "message": "Не указана сумма"}, status=400)
            try:
                amount = parse_decimal(amount_raw)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректная сумма"}, status=400)
            credit = Credit.objects.create(name=name, amount=amount)
            created_obj = credit

            credit_fields = [
                {"name": "name", "verbose_name": "Наименование"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            ]
            row_html = render_to_string("components/table_row.html", {"item": credit, "fields": credit_fields})

        elif type_ in ("short_term", "short_term_liability"):
            amount_raw = request.POST.get("amount")
            if amount_raw is None:
                return JsonResponse({"status": "error", "message": "Не указана сумма"}, status=400)
            try:
                amount = parse_decimal(amount_raw)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректная сумма"}, status=400)
            st = ShortTermLiability.objects.create(name=name, amount=amount)
            created_obj = st

            short_fields = [
                {"name": "name", "verbose_name": "Наименование"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            ]
            row_html = render_to_string("components/table_row.html", {"item": st, "fields": short_fields})
        else:
            return JsonResponse({"status": "error", "message": "Неизвестный тип"}, status=400)

        equipment = BalanceData.objects.filter(name="Оборудование").aggregate(total=Sum("amount"))["total"] or Decimal(0)

        inventory_total = InventoryItem.objects.aggregate(total=Sum("total"))["total"] or Decimal(0)
        credit_total = Credit.objects.aggregate(total=Sum("amount"))["total"] or Decimal(0)
        short_total = ShortTermLiability.objects.aggregate(total=Sum("amount"))["total"] or Decimal(0)

        total_debtors = Decimal(0)
        for branch in Supplier.objects.exclude(branch=None).values_list("branch__id", "branch__name").distinct():
            branch_id, branch_name = branch
            if branch_name != "Филиал 1" and branch_name != "Наши ИП":
                branch_debt = sum(
                    (t.supplier_debt or Decimal(0))
                    for t in Transaction.objects.filter(supplier__branch_id=branch_id, paid_amount__gt=0)
                )
                total_debtors += branch_debt

        safe_amount = SupplierAccount.objects.filter(
            supplier__visible_in_summary=True
        ).aggregate(total=Sum("balance"))["total"] or Decimal(0)

        cash_account = Account.objects.filter(name__iexact="Наличные").first()
        cash_balance = Decimal(cash_account.balance) if cash_account and cash_account.balance is not None else Decimal(0)
        safe_amount = Decimal(safe_amount) + cash_balance

        bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))
        total_remaining = sum((t.client_debt_paid or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))

        transactionsInvestors = [
            t for t in Transaction.objects.filter(paid_amount__gt=0)
            if getattr(t, 'bonus_debt', 0) == 0
            and getattr(t, 'client_debt', 0) == 0
            and getattr(t, 'profit', 0) > 0
        ]
        cashflows = CashFlow.objects.filter(
            purpose__operation_type=PaymentPurpose.INCOME
        ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

        total_profit_decimal = sum(
            (Decimal(str(getattr(t, 'profit', 0) or 0)) - Decimal(str(getattr(t, 'returned_to_investor', 0) or 0)))
            for t in transactionsInvestors
        ) + sum(
            (Decimal(str(cf.amount or 0)) - Decimal(str(cf.returned_to_investor or 0)))
            for cf in cashflows
        )

        assets_total = equipment + inventory_total + total_debtors + safe_amount

        investors_total = Investor.objects.aggregate(total=Sum("balance"))["total"] or Decimal(0)
        total_summary_debts = (bonuses or Decimal(0)) + (total_remaining or Decimal(0)) + (total_profit_decimal or Decimal(0))
        undistributed_profit = Decimal(0)
        provisional_liabilities = credit_total + short_total + total_summary_debts + (investors_total or Decimal(0)) + undistributed_profit

        current_capital = assets_total - provisional_liabilities
        liabilities_total = provisional_liabilities + current_capital

        response = {
            "status": "success",
            "type": type_,
            "id": getattr(created_obj, "id", None),
            "html": row_html,
            "assets": float(assets_total),
            "inventory_total": float(inventory_total),
            "credit_total": float(credit_total),
            "short_term_total": float(short_total),
            "liabilities": float(liabilities_total),
            "capital": float(current_capital),
        }

        return JsonResponse(response)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def edit_balance_item(request, pk=None):
    try:
        type_ = request.POST.get("operation_type")
        item_id = pk or request.POST.get("id")
        name = (request.POST.get("name") or "").strip()
        if not type_ or not item_id or not name:
            return JsonResponse({"status": "error", "message": "Не указаны обязательные параметры"}, status=400)

        def parse_decimal(v):
            try:
                return Decimal(str(clean_currency(v))) if v is not None else Decimal(0)
            except Exception:
                return Decimal(0)

        row_html = ""
        updated_obj = None

        if type_ == "inventory":
            qty_raw = request.POST.get("quantity")
            price_raw = request.POST.get("price")
            if qty_raw is None or price_raw is None:
                return JsonResponse({"status": "error", "message": "Не заданы quantity или price"}, status=400)
            try:
                quantity = Decimal(str(qty_raw).replace(",", "."))
                price = parse_decimal(price_raw)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректные значения quantity/price"}, status=400)

            item = get_object_or_404(InventoryItem, id=item_id)
            item.name = name
            item.quantity = quantity
            item.price = price
            item.save()
            updated_obj = item

            inventory_fields = [
                {"name": "name", "verbose_name": "Наименование"},
                {"name": "quantity", "verbose_name": "Количество"},
                {"name": "price", "verbose_name": "Цена за ед.", "is_amount": True},
                {"name": "total", "verbose_name": "Сумма", "is_amount": True},
            ]
            row_html = render_to_string("components/table_row.html", {"item": item, "fields": inventory_fields})

        elif type_ == "credit":
            amount_raw = request.POST.get("amount")
            if amount_raw is None:
                return JsonResponse({"status": "error", "message": "Не указана сумма"}, status=400)
            try:
                amount = parse_decimal(amount_raw)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректная сумма"}, status=400)

            credit = get_object_or_404(Credit, id=item_id)
            credit.name = name
            credit.amount = amount
            credit.save()
            updated_obj = credit

            credit_fields = [
                {"name": "name", "verbose_name": "Наименование"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            ]
            row_html = render_to_string("components/table_row.html", {"item": credit, "fields": credit_fields})

        elif type_ in ("short_term", "short_term_liability"):
            amount_raw = request.POST.get("amount")
            if amount_raw is None:
                return JsonResponse({"status": "error", "message": "Не указана сумма"}, status=400)
            try:
                amount = parse_decimal(amount_raw)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректная сумма"}, status=400)

            st = get_object_or_404(ShortTermLiability, id=item_id)
            st.name = name
            st.amount = amount
            st.save()
            updated_obj = st

            short_fields = [
                {"name": "name", "verbose_name": "Наименование"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            ]
            row_html = render_to_string("components/table_row.html", {"item": st, "fields": short_fields})
        else:
            return JsonResponse({"status": "error", "message": "Неизвестный тип"}, status=400)

        equipment = BalanceData.objects.filter(name="Оборудование").aggregate(total=Sum("amount"))["total"] or Decimal(0)
        inventory_total = InventoryItem.objects.aggregate(total=Sum("total"))["total"] or Decimal(0)
        credit_total = Credit.objects.aggregate(total=Sum("amount"))["total"] or Decimal(0)
        short_total = ShortTermLiability.objects.aggregate(total=Sum("amount"))["total"] or Decimal(0)

        total_debtors = Decimal(0)
        for branch in Supplier.objects.exclude(branch=None).values_list("branch__id", "branch__name").distinct():
            branch_id, branch_name = branch
            if branch_name != "Филиал 1" and branch_name != "Наши ИП":
                branch_debt = sum(
                    (t.supplier_debt or Decimal(0))
                    for t in Transaction.objects.filter(supplier__branch_id=branch_id, paid_amount__gt=0)
                )
                total_debtors += branch_debt

        safe_amount = SupplierAccount.objects.filter(
            supplier__visible_in_summary=True
        ).aggregate(total=Sum("balance"))["total"] or Decimal(0)

        cash_account = Account.objects.filter(name__iexact="Наличные").first()
        cash_balance = Decimal(cash_account.balance) if cash_account and cash_account.balance is not None else Decimal(0)
        safe_amount = Decimal(safe_amount) + cash_balance

        bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))
        total_remaining = sum((t.client_debt_paid or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))

        transactionsInvestors = [
            t for t in Transaction.objects.filter(paid_amount__gt=0)
            if getattr(t, 'bonus_debt', 0) == 0
            and getattr(t, 'client_debt', 0) == 0
            and getattr(t, 'profit', 0) > 0
        ]
        cashflows = CashFlow.objects.filter(
            purpose__operation_type=PaymentPurpose.INCOME
        ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

        total_profit_decimal = sum(
            (Decimal(str(getattr(t, 'profit', 0) or 0)) - Decimal(str(getattr(t, 'returned_to_investor', 0) or 0)))
            for t in transactionsInvestors
        ) + sum(
            (Decimal(str(cf.amount or 0)) - Decimal(str(cf.returned_to_investor or 0)))
            for cf in cashflows
        )

        assets_total = equipment + inventory_total + total_debtors + safe_amount

        investors_total = Investor.objects.aggregate(total=Sum("balance"))["total"] or Decimal(0)
        total_summary_debts = (bonuses or Decimal(0)) + (total_remaining or Decimal(0)) + (total_profit_decimal or Decimal(0))
        undistributed_profit = Decimal(0)
        provisional_liabilities = credit_total + short_total + total_summary_debts + (investors_total or Decimal(0)) + undistributed_profit

        current_capital = assets_total - provisional_liabilities
        liabilities_total = provisional_liabilities + current_capital

        response = {
            "status": "success",
            "type": type_,
            "id": getattr(updated_obj, "id", None),
            "html": row_html,
            "assets": float(assets_total),
            "inventory_total": float(inventory_total),
            "credit_total": float(credit_total),
            "short_term_total": float(short_total),
            "liabilities": float(liabilities_total),
            "capital": float(current_capital),
        }
        return JsonResponse(response)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
def balance_item_detail(request, type, pk):
    type_ = (type or "").strip().lower()

    def _to_float(v):
        try:
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    try:
        if type_ == "inventory":
            obj = get_object_or_404(InventoryItem, id=pk)
            data = model_to_dict(obj)
            data["quantity"] = _to_float(getattr(obj, "quantity", 0))
            data["price"] = _to_float(getattr(obj, "price", 0))
            data["total"] = _to_float(getattr(obj, "total", getattr(obj, "amount", 0)))
            data["type"] = "inventory"

        elif type_ == "credit":
            obj = get_object_or_404(Credit, id=pk)
            data = model_to_dict(obj)
            data["amount"] = _to_float(getattr(obj, "amount", 0))
            data["type"] = "credit"

        elif type_ in ("short_term", "short_term_liability"):
            obj = get_object_or_404(ShortTermLiability, id=pk)
            data = model_to_dict(obj)
            data["amount"] = _to_float(getattr(obj, "amount", 0))
            data["type"] = "short_term"

        elif type_ in ("equipment", "balancedata", "balance_data"):
            obj = get_object_or_404(BalanceData, id=pk)
            data = model_to_dict(obj)
            data["amount"] = _to_float(getattr(obj, "amount", 0))
            data["type"] = "equipment"

        else:
            found = False
            try:
                obj = InventoryItem.objects.filter(id=pk).first()
                if obj:
                    data = model_to_dict(obj)
                    data["quantity"] = _to_float(getattr(obj, "quantity", 0))
                    data["price"] = _to_float(getattr(obj, "price", 0))
                    data["total"] = _to_float(getattr(obj, "total", getattr(obj, "amount", 0)))
                    data["type"] = "inventory"
                    found = True
            except Exception:
                pass

            if not found:
                try:
                    obj = Credit.objects.filter(id=pk).first()
                    if obj:
                        data = model_to_dict(obj)
                        data["amount"] = _to_float(getattr(obj, "amount", 0))
                        data["type"] = "credit"
                        found = True
                except Exception:
                    pass

            if not found:
                try:
                    obj = ShortTermLiability.objects.filter(id=pk).first()
                    if obj:
                        data = model_to_dict(obj)
                        data["amount"] = _to_float(getattr(obj, "amount", 0))
                        data["type"] = "short_term"
                        found = True
                except Exception:
                    pass

            if not found:
                try:
                    obj = BalanceData.objects.filter(id=pk).first()
                    if obj:
                        data = model_to_dict(obj)
                        data["amount"] = _to_float(getattr(obj, "amount", 0))
                        data["type"] = "equipment"
                        found = True
                except Exception:
                    pass

            if not found:
                return JsonResponse({"status": "error", "message": "Элемент баланса не найден"}, status=404)

        return JsonResponse({"data": data})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def delete_balance_item(request, pk=None):
    try:
        type_ = request.POST.get("operation_type")
        item_id = pk or request.POST.get("id")
        if not type_ or not item_id:
            try:
                body = json.loads(request.body.decode("utf-8") or "{}")
                type_ = type_ or body.get("operation_type") or body.get("type")
                item_id = item_id or body.get("id")
            except Exception:
                pass

        if not type_ or not item_id:
            return JsonResponse({"status": "error", "message": "Не указаны обязательные параметры"}, status=400)

        type_norm = (type_ or "").strip().lower()
        if type_norm == "inventory":
            obj = InventoryItem.objects.filter(id=item_id).first()
            if not obj:
                return JsonResponse({"status": "error", "message": "Элемент инвентаря не найден"}, status=404)
            obj.delete()
        elif type_norm == "credit":
            obj = Credit.objects.filter(id=item_id).first()
            if not obj:
                return JsonResponse({"status": "error", "message": "Кредит не найден"}, status=404)
            obj.delete()
        elif type_norm in ("short_term", "short_term_liability"):
            obj = ShortTermLiability.objects.filter(id=item_id).first()
            if not obj:
                return JsonResponse({"status": "error", "message": "Краткосрочное обязательство не найдено"}, status=404)
            obj.delete()
        elif type_norm in ("equipment", "balancedata", "balance_data"):
            obj = BalanceData.objects.filter(id=item_id).first()
            if not obj:
                return JsonResponse({"status": "error", "message": "Запись баланса не найдена"}, status=404)
            obj.delete()
        else:
            return JsonResponse({"status": "error", "message": "Неизвестный тип"}, status=400)

        equipment = BalanceData.objects.filter(name="Оборудование").aggregate(total=Sum("amount"))["total"] or Decimal(0)
        inventory_total = InventoryItem.objects.aggregate(total=Sum("total"))["total"] or Decimal(0)
        credit_total = Credit.objects.aggregate(total=Sum("amount"))["total"] or Decimal(0)
        short_total = ShortTermLiability.objects.aggregate(total=Sum("amount"))["total"] or Decimal(0)

        total_debtors = Decimal(0)
        for branch in Supplier.objects.exclude(branch=None).values_list("branch__id", "branch__name").distinct():
            branch_id, branch_name = branch
            if branch_name != "Филиал 1" and branch_name != "Наши ИП":
                branch_debt = sum(
                    (t.supplier_debt or Decimal(0))
                    for t in Transaction.objects.filter(supplier__branch_id=branch_id, paid_amount__gt=0)
                )
                total_debtors += branch_debt

        safe_amount = SupplierAccount.objects.filter(
            supplier__visible_in_summary=True
        ).aggregate(total=Sum("balance"))["total"] or Decimal(0)

        cash_account = Account.objects.filter(name__iexact="Наличные").first()
        cash_balance = Decimal(cash_account.balance) if cash_account and cash_account.balance is not None else Decimal(0)
        safe_amount = Decimal(safe_amount) + cash_balance

        bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))
        total_remaining = sum((t.client_debt_paid or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0))

        transactionsInvestors = [
            t for t in Transaction.objects.filter(paid_amount__gt=0)
            if getattr(t, 'bonus_debt', 0) == 0
            and getattr(t, 'client_debt', 0) == 0
            and getattr(t, 'profit', 0) > 0
        ]
        cashflows = CashFlow.objects.filter(
            purpose__operation_type=PaymentPurpose.INCOME
        ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

        total_profit_decimal = sum(
            (Decimal(str(getattr(t, 'profit', 0) or 0)) - Decimal(str(getattr(t, 'returned_to_investor', 0) or 0)))
            for t in transactionsInvestors
        ) + sum(
            (Decimal(str(cf.amount or 0)) - Decimal(str(cf.returned_to_investor or 0)))
            for cf in cashflows
        )

        assets_total = equipment + inventory_total + total_debtors + safe_amount

        investors_total = Investor.objects.aggregate(total=Sum("balance"))["total"] or Decimal(0)
        total_summary_debts = (bonuses or Decimal(0)) + (total_remaining or Decimal(0)) + (total_profit_decimal or Decimal(0))
        undistributed_profit = Decimal(0)
        provisional_liabilities = credit_total + short_total + total_summary_debts + (investors_total or Decimal(0)) + undistributed_profit

        current_capital = assets_total - provisional_liabilities
        liabilities_total = provisional_liabilities + current_capital

        response = {
            "status": "success",
            "type": type_norm,
            "id": item_id,
            "assets": float(assets_total),
            "inventory_total": float(inventory_total),
            "credit_total": float(credit_total),
            "short_term_total": float(short_total),
            "liabilities": float(liabilities_total),
            "capital": float(current_capital),
        }
        return JsonResponse(response)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
def money_logs_types(request):
    """Возвращает доступные типы операций для логов денежных средств"""
    types = [
        {"id": "cf", "name": "Движение ДС"},
        {"id": "dr", "name": "Погашение долга поставщика"},
        {"id": "cdr", "name": "Погашение долга клиента"},
        {"id": "io-withdrawal", "name": "Инвестор: Забор"},
        {"id": "io-deposit", "name": "Инвестор: Внесение"},
        {"id": "io-profit", "name": "Инвестор: Прибыль"},
    ]
    return JsonResponse(types, safe=False)

@forbid_supplier
@login_required
@require_GET
def investor_debt_problems(request):
    transactionsInvestors = [
        t for t in Transaction.objects.filter(paid_amount__gt=0)
        if getattr(t, 'bonus_debt', 0) == 0
        and getattr(t, 'client_debt', 0) == 0
        and getattr(t, 'profit', 0) > 0
    ]
    problem_transactions = [
        {
            "id": t.id,
            "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y %H:%M") if t.created_at else "",
            "client": str(t.client) if t.client else "",
            "amount": float(getattr(t, 'amount', 0)),
            "profit": float(getattr(t, 'profit', 0)),
            "returned_to_investor": float(getattr(t, 'returned_to_investor', 0)),
            "debt": float(getattr(t, 'profit', 0)) - float(getattr(t, 'returned_to_investor', 0)),
        }
        for t in transactionsInvestors
        if float(getattr(t, 'profit', 0)) - float(getattr(t, 'returned_to_investor', 0)) < 0
    ]

    cashflows = CashFlow.objects.filter(
        purpose__operation_type=PaymentPurpose.INCOME
    ).exclude(purpose__name__in=["Оплата", "Внесение инвестора"])

    problem_cashflows = [
        {
            "id": cf.id,
            "created_at": timezone.localtime(cf.created_at).strftime("%d.%m.%Y %H:%M") if cf.created_at else "",
            "purpose": cf.purpose.name if cf.purpose else "",
            "amount": float(cf.amount),
            "returned_to_investor": float(cf.returned_to_investor or 0),
            "debt": float(cf.amount) - float(cf.returned_to_investor or 0),
        }
        for cf in cashflows
        if float(cf.amount) - float(cf.returned_to_investor or 0) < 0
    ]

    return JsonResponse({
        "problem_transactions": problem_transactions,
        "problem_cashflows": problem_cashflows,
        "has_problems": bool(problem_transactions or problem_cashflows),
    })

@forbid_supplier
@login_required
@require_GET
def bonus_cash_needed(request):
    total_returned_bonus = (
        Transaction.objects.filter(paid_amount__gt=0)
        .aggregate(total=models.Sum('returned_bonus'))['total'] or 0
    )
    return JsonResponse({
        "total_cash_needed_for_bonuses": float(total_returned_bonus)
    })

@forbid_supplier
@login_required
@require_GET
def profit_by_month(request):
    try:
        month = int(request.GET.get("month", 0))
        year = int(request.GET.get("year", datetime.now().year))
        if not (1 <= month <= 12):
            return JsonResponse({"status": "error", "message": "Некорректный месяц"}, status=400)
    except Exception:
        return JsonResponse({"status": "error", "message": "Некорректный месяц"}, status=400)

    from calendar import monthrange
    from django.utils import timezone

    first_day = timezone.make_aware(datetime(year, month, 1, 0, 0, 0))
    last_day = timezone.make_aware(datetime(year, month, monthrange(year, month)[1], 23, 59, 59))

    transactions = Transaction.objects.filter(
        created_at__range=(first_day, last_day),
        paid_amount__gte=models.F('amount')
    )

    transactions = [
        t for t in transactions
        if (getattr(t, 'bonus_debt', 0) == 0 and
            getattr(t, 'client_debt', 0) == 0 and
            getattr(t, 'investor_debt', 0) == 0 and
            getattr(t, 'supplier_debt', 0) == 0)
    ]

    total_profit = sum(float(t.profit or 0) for t in transactions)

    return JsonResponse({
        "year": year,
        "month": month,
        "total_profit": total_profit
    })
