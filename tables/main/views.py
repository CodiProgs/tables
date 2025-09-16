from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from tables.utils import get_model_fields
from django.db import transaction, models
from .models import Transaction, Client, Supplier, Account, CashFlow, SupplierAccount, PaymentPurpose, MoneyTransfer, Branch, SupplierDebtRepayment, Investor, InvestorDebtOperation, BalanceData, MonthlyCapital
from django.http import JsonResponse
from django.forms.models import model_to_dict
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
import locale
import json
from decimal import Decimal
from django.db.models import Sum, F
from collections import defaultdict
from functools import wraps
from django.core.exceptions import PermissionDenied
from datetime import datetime
from calendar import monthrange
from django.core.cache import cache
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from users.models import User, UserType
import math


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

@login_required
def index(request):
    user_type = getattr(getattr(request.user, 'user_type', None), 'name', None)
    if user_type == 'Поставщик' or user_type == 'Филиал':
        return redirect('main:debtors')

    is_accountant = user_type == 'Бухгалтер'
    is_assistant = user_type == 'Ассистент'

    fields = get_transaction_fields(is_accountant, is_assistant)

    transactions_qs = Transaction.objects.select_related('client', 'supplier').all().order_by('created_at')
    if is_assistant:
        transactions_qs = transactions_qs.filter(supplier__visible_for_assistant=True)

    paginator = Paginator(transactions_qs, 500)
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
        getattr(t, 'supplier_debt', 0) 
        for t in page.object_list 
    ]

    client_debts = [
        getattr(t, 'client_debt', 0) 
        for t in page.object_list 
    ]

    bonus_debts = [
        round(float(t.amount or 0) * float(t.bonus_percentage or 0) / 100 - float(t.returned_bonus or 0), 2)
        for t in page.object_list
    ]

    investor_debts = [
        getattr(t, 'investor_debt', 0) 
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
        "remaining_amount", "bonus_percentage", "bonus",
    ]
    if not is_accountant:
        field_order.extend(["supplier_percentage", "profit"])
    field_order.extend(["paid_amount", "debt", "documents"])

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
    ]

    if not is_accountant:
        insertions.extend([
            (9, {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True, }),
            (10, {"name": "profit", "verbose_name": "Прибыль", "is_amount": True}),
        ])

    insertions.extend([
        (11 if not is_accountant else 8, {"name": "paid_amount", "verbose_name": "Оплачено", "is_amount": True}),
        (12 if not is_accountant else 9, {"name": "debt", "verbose_name": "Долг", "is_amount": True}),
    ])

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
                    old_supplier_account = SupplierAccount.objects.filter(
                        supplier=old_supplier,
                        account=old_account
                    ).first()
                    if old_supplier_account:
                        old_supplier_account.balance -= old_paid_amount
                        old_supplier_account.save()
                    old_account.balance -= old_paid_amount
                    old_account.save()

                new_supplier_account, _ = SupplierAccount.objects.get_or_create(
                    supplier=supplier,
                    account=account_supplier,
                    defaults={'balance': 0}
                )
                new_supplier_account.balance += old_paid_amount
                new_supplier_account.save()
                account_supplier.balance += old_paid_amount
                account_supplier.save()

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

                supplier_account = SupplierAccount.objects.filter(
                    supplier=trans.supplier,
                    account=account
                ).first()

                cashflows = CashFlow.objects.filter(transaction=trans, purpose__name="Оплата")
                to_remove = abs(payment_difference)
                for cf in cashflows:
                    if to_remove <= 0:
                        break
                    cf_amount = cf.amount
                    if to_remove >= cf_amount:
                        to_remove -= cf_amount
                        account.balance -= cf_amount
                        account.save()
                        if supplier_account:
                            supplier_account.balance -= cf_amount
                            supplier_account.save()
                        cf.delete()
                    else:
                        cf.amount -= to_remove
                        account.balance -= to_remove
                        account.save()
                        if supplier_account:
                            supplier_account.balance -= to_remove
                            supplier_account.save()
                        cf.save()
                        to_remove = 0

            if payment_difference > 0 and trans.supplier:
                if not trans.account:
                    return JsonResponse(
                        {"status": "error", "message": "У транзакции не указан счет для проведения оплаты"},
                        status=400,
                    )

                account = trans.account
                account.balance += payment_difference
                account.save()

                supplier_account, created = SupplierAccount.objects.get_or_create(
                    supplier=trans.supplier,
                    account=account,
                    defaults={'balance': 0}
                )
                supplier_account.balance += payment_difference
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
                    transaction=trans
                )

            if new_paid_amount == 0 and previous_paid_amount > 0 and trans.supplier and trans.account:
                account = trans.account
                supplier_account = SupplierAccount.objects.filter(
                    supplier=trans.supplier,
                    account=account
                ).first()
                cashflows = CashFlow.objects.filter(transaction=trans, purpose__name="Оплата")
                for cf in cashflows:
                    account.balance -= cf.amount
                    account.save()
                    if supplier_account:
                        supplier_account.balance -= cf.amount
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
        acc_data = BankAccountData(
            name=acc.name,
            balance=format_currency(acc.balance),
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
    ]
    fields = get_model_fields(
        Client,
        excluded_fields=excluded,
    )

    insertions = [
        (1, {"name": "percentage", "verbose_name": "%", "is_percent": True, }),
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

            if not name or not percentage:
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            client = Client.objects.create(
                name=name,
                percentage=float(percentage),
                comment=comment,
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

            # if old_percentage != new_percentage:
            #     Transaction.objects.filter(
            #         client=client,
            #         client_percentage=old_percentage
            #     ).update(client_percentage=new_percentage)

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
    cash_flow = CashFlow.objects.all().order_by('created_at')

    paginator = Paginator(cash_flow, 500)
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
    cash_flow = CashFlow.objects.all().order_by('created_at')
    paginator = Paginator(cash_flow, 500)
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
    # fields = get_model_fields(
    #     CashFlow,
    #     excluded_fields=excluded,
    # )
    fields = [
        {"name": "created_at", "verbose_name": "Дата", "is_date": True},
        {"name": "account", "verbose_name": "Счет", "is_relation": True},
        {"name": "supplier", "verbose_name": "Поставщик", "is_relation": True},
        {"name": "purpose", "verbose_name": "Назначение", "is_relation": True},
        {"name": "comment", "verbose_name": "Комментарий"},
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
    transactions = Transaction.objects.select_related('client', 'supplier').all().order_by('created_at')
    paginator = Paginator(transactions, 500)
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
    return JsonResponse({
        "html": html,
        "context": {
            "total_pages": paginator.num_pages,
            "current_page": page.number,
            "transaction_ids": transaction_ids,
            "changed_cells": changed_cells,
        },
    })

@forbid_supplier
@login_required
def supplier_accounts(request):
    suppliers = Supplier.objects.filter(visible_in_summary=True).order_by('name')
    bank_accounts = Account.objects.exclude(name__iexact="Наличные").order_by('name')  # исключаем "Наличные"

    class SupplierAccountRow:
        def __init__(self, supplier_name, supplier_id):
            self.supplier = supplier_name
            self.supplier_id = supplier_id

    balances = {}
    supplier_accounts_qs = SupplierAccount.objects.select_related('supplier', 'account').all()
    for sa in supplier_accounts_qs:
        balances[(sa.supplier_id, sa.account_id)] = sa.balance

    rows = []
    account_totals = {account.id: 0 for account in bank_accounts}
    grand_total = 0

    for supplier in suppliers:
        row = SupplierAccountRow(supplier.name, supplier.id)
        total_balance = 0
        for account in bank_accounts:
            balance = balances.get((supplier.id, account.id), 0)
            setattr(row, f'account_{account.id}', format_currency(balance))
            account_totals[account.id] += balance
            total_balance += balance
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

    is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False
    supplier_ids = [supplier.id for supplier in suppliers]
    account_ids = [account.id for account in bank_accounts]

    cash_account = Account.objects.filter(name__iexact="Наличные").first()
    cash_balance = cash_account.balance if cash_account else 0

    grand_total_with_cash = grand_total + cash_balance

    context = {
        "fields": supplier_fields,
        "data": rows,
        "is_grouped": {"accounts-table": True},
        "is_admin": is_admin,
        "supplier_ids": supplier_ids,
        "account_ids": account_ids,
        "cash_balance": format_currency(cash_balance),
        "grand_total_with_cash": format_currency(grand_total_with_cash),
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

            supplier.accounts.set(Account.objects.filter(id__in=account_ids.split(',')))

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
            new_account_ids = set(account_ids.split(','))

            removed_account_ids = old_account_ids - new_account_ids
            if removed_account_ids:
                for acc_id in removed_account_ids:
                    supplier_account = SupplierAccount.objects.filter(supplier=supplier, account_id=acc_id).first()
                    if supplier_account and supplier_account.balance != 0:
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
            supplier.accounts.set(Account.objects.filter(id__in=account_ids.split(',')))

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

            # if old_cost_percentage != new_cost_percentage:
            #     Transaction.objects.filter(
            #         supplier=supplier,
            #         supplier_percentage=old_cost_percentage
            #     ).update(supplier_percentage=new_cost_percentage)

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
                if sa.balance != 0:
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

    data['created_at_formatted'] = timezone.localtime(cashflow.created_at).strftime("%d.%m.%Y %H:%M") if cashflow.created_at else ""

    return JsonResponse({"data": data})

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def cash_flow_create(request):
    try:
        with transaction.atomic():
            amount = clean_currency(request.POST.get("amount"))
            purpose_id = request.POST.get("purpose")
            supplier_id = request.POST.get("supplier")
            account_id = request.POST.get("account")
            comment = request.POST.get("comment", "")

            if not all([amount, purpose_id, supplier_id, account_id]):
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
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

            purpose = get_object_or_404(PaymentPurpose, id=purpose_id)
            supplier = get_object_or_404(Supplier, id=supplier_id)
            account = get_object_or_404(Account, id=account_id)

            amount_value = int(float(amount))
            if purpose.operation_type == PaymentPurpose.EXPENSE:
                amount_value = -abs(amount_value)
            else:
                amount_value = abs(amount_value)

            cashflow = CashFlow.objects.create(
                account=account,
                amount=amount_value,
                purpose=purpose,
                supplier=supplier,
                comment=comment
            )
            account.balance += amount_value
            account.save()

            supplier_account, created = SupplierAccount.objects.get_or_create(
                supplier=supplier,
                account=account,
                defaults={'balance': 0}
            )

            supplier_account.balance += amount_value
            supplier_account.save()

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

@forbid_supplier
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

            if not all([new_supplier_id, new_amount, new_purpose_id, new_account_id]):
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
                    if new_amount_value > cashflow.transaction.amount:
                        return JsonResponse({
                            "status": "error",
                            "message": "Сумма не может превышать общую сумму транзакции",
                        }, status=400)
            except ValueError:
                return JsonResponse({
                    "status": "error",
                    "message": "Некорректная сумма",
                }, status=400)

            old_account_id = cashflow.account_id
            old_supplier_id = cashflow.supplier_id if cashflow.supplier else None
            old_amount = cashflow.amount
            old_purpose_id = cashflow.purpose_id

            new_supplier = get_object_or_404(Supplier, id=new_supplier_id)
            new_purpose = get_object_or_404(PaymentPurpose, id=new_purpose_id)
            new_account = get_object_or_404(Account, id=new_account_id)

            if not new_account:
                return JsonResponse({
                    "status": "error",
                    "message": "У операции должен быть выбран счет",
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

            updated_amount = -abs(new_amount_value) if new_purpose.operation_type == PaymentPurpose.EXPENSE else abs(new_amount_value)

            old_account = Account.objects.get(id=old_account_id)
            old_account.balance -= old_amount
            old_account.save()

            if old_supplier_id:
                old_supplier = Supplier.objects.get(id=old_supplier_id)
                old_supplier_account = SupplierAccount.objects.filter(
                    supplier=old_supplier,
                    account=old_account
                ).first()

                if old_supplier_account:
                    old_supplier_account.balance -= old_amount
                    old_supplier_account.save()

            new_account.balance += updated_amount
            new_account.save()

            new_supplier_account, _ = SupplierAccount.objects.get_or_create(
                supplier=new_supplier,
                account=new_account,
                defaults={'balance': 0}
            )

            new_supplier_account.balance += updated_amount
            new_supplier_account.save()

            if cashflow.purpose.name == "Оплата" and cashflow.transaction:
                transaction_obj = cashflow.transaction
                transaction_obj.paid_amount -= old_amount
                transaction_obj.paid_amount += updated_amount
                transaction_obj.save()

            cashflow.account = new_account
            cashflow.supplier = new_supplier
            cashflow.amount = updated_amount
            cashflow.purpose = new_purpose
            cashflow.comment = comment
            cashflow.created_at = parse_datetime_string(created_at_str) if created_at_str else cashflow.created_at
            cashflow.save()

            cashflow.refresh_from_db()

            context = {
                "item": cashflow,
                "fields": get_cash_flow_fields()
            }

            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": cashflow.id,
                "status": "success",
                "message": "Движение средств успешно обновлено"
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
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
            amount = cashflow.amount
            purpose = cashflow.purpose
            transaction_obj = cashflow.transaction

            is_payment = purpose and purpose.name == "Оплата"

            account.balance -= amount
            account.save()

            if supplier:
                try:
                    supplier_account = SupplierAccount.objects.get(
                        supplier=supplier,
                        account=account
                    )
                    supplier_account.balance -= amount

                    supplier_account.save()
                except SupplierAccount.DoesNotExist:
                    pass

                if is_payment and transaction_obj is not None:
                    payment_amount = abs(amount)

                    if transaction_obj.paid_amount >= payment_amount:
                        transaction_obj.paid_amount -= payment_amount
                        transaction_obj.save()

            cashflow.delete()

            return JsonResponse({
                "status": "success",
                "message": f"Транзакция успешно удалена",
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
    
@forbid_supplier
@login_required
def account_list(request):
    supplier_id = request.GET.get('supplier_id')
    is_collection = request.GET.get('is_collection') == 'true'
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

    if cash_account and not is_collection:
        account_data.append({"id": cash_account.id, "name": "Наличные"})

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
            for acc in PaymentPurpose.objects.all().exclude(name="Оплата").exclude(name="Перевод").exclude(name="Инкассация").exclude(name="Погашение долга поставщика").order_by('operation_type', 'name')
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

            if not source_supplier_account or source_supplier_account.balance < amount_value:
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

            source_account.balance -= amount_value
            source_account.save()

            source_supplier_account.balance -= amount_value
            source_supplier_account.save()

            cash_account.balance += amount_value
            cash_account.save()

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
                comment=f"Инкассация: перевод на счет 'Наличные'"
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
                balances[(sa.supplier_id, sa.account_id)] = sa.balance

            rows = []
            account_totals = {account.id: 0 for account in bank_accounts}
            grand_total = 0

            for supplier in suppliers:
                row = SupplierAccountRow(supplier.name, supplier.id)
                total_balance = 0
                for account in bank_accounts:
                    balance = balances.get((supplier.id, account.id), 0)
                    setattr(row, f'account_{account.id}', format_currency(balance))
                    account_totals[account.id] += balance
                    total_balance += balance
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
            cash_balance = cash_account.balance if cash_account else 0

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

            if not source_account or not destination_account:
                return JsonResponse(
                    {"status": "error", "message": "У одного из поставщиков не указан счет по умолчанию"},
                    status=400,
                )

            if source_account.id == destination_account.id and source_supplier.id == destination_supplier.id:
                return JsonResponse(
                    {"status": "error", "message": "Нельзя переводить средства на тот же счет того же поставщика"},
                    status=400,
                )

            source_supplier_account = SupplierAccount.objects.filter(
                supplier=source_supplier,
                account=source_account
            ).first()

            if not source_supplier_account or source_supplier_account.balance < amount_value:
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
                is_counted=is_counted if is_exchange else None
            )

            source_account.balance -= amount_value
            source_account.save()

            destination_account.balance += amount_value
            destination_account.save()

            source_supplier_account.balance -= amount_value
            source_supplier_account.save()

            destination_supplier_account, created = SupplierAccount.objects.get_or_create(
                supplier=destination_supplier,
                account=destination_account,
                defaults={'balance': 0}
            )
            destination_supplier_account.balance += amount_value
            destination_supplier_account.save()

            transfer_purpose = PaymentPurpose.objects.filter(name="Перевод").first()
            if not transfer_purpose:
                transfer_purpose = PaymentPurpose.objects.create(
                    name="Перевод",
                    operation_type=PaymentPurpose.EXPENSE
                )
            CashFlow.objects.create(
                account=source_account,
                supplier=source_supplier,
                amount=-amount_value,
                purpose=transfer_purpose,
                comment=f"Перевод {destination_supplier.name} на счет {destination_account.name}"
            )
            CashFlow.objects.create(
                account=destination_account,
                supplier=destination_supplier,
                amount=amount_value,
                purpose=transfer_purpose,
                comment=f"Получено от {source_supplier.name} со счета {source_account.name}"
            )

            suppliers = Supplier.objects.filter(visible_in_summary=True).order_by('name')
            bank_accounts = Account.objects.exclude(name__iexact="Наличные").order_by('name')  # исключаем "Наличные"

            class SupplierAccountRow:
                def __init__(self, supplier_name, supplier_id):
                    self.supplier = supplier_name
                    self.supplier_id = supplier_id

            balances = {}
            supplier_accounts = SupplierAccount.objects.select_related('supplier', 'account').all()
            for sa in supplier_accounts:
                balances[(sa.supplier_id, sa.account_id)] = sa.balance

            rows = []
            account_totals = {account.id: 0 for account in bank_accounts}
            grand_total = 0

            for supplier in suppliers:
                row = SupplierAccountRow(supplier.name, supplier.id)
                total_balance = 0
                for account in bank_accounts:
                    balance = balances.get((supplier.id, account.id), 0)
                    setattr(row, f'account_{account.id}', format_currency(balance))
                    account_totals[account.id] += balance
                    total_balance += balance
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

            grand_total_with_cash = grand_total + cash_balance
            
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
                "cash_balance": format_currency(cash_balance),
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
            old_amount = money_transfer.amount

            new_source_supplier = get_object_or_404(Supplier, id=source_supplier_id)
            new_destination_supplier = get_object_or_404(Supplier, id=destination_supplier_id)

            new_source_account = get_object_or_404(Account, id=source_account_id)
            new_destination_account = get_object_or_404(Account, id=destination_account_id)

            if not new_source_account or not new_destination_account:
                return JsonResponse(
                    {"status": "error", "message": "У одного из поставщиков не указан счет по умолчанию"},
                    status=400,
                )

            if new_source_account.id == new_destination_account.id and new_source_supplier.id == new_destination_supplier.id:
                return JsonResponse(
                    {"status": "error", "message": "Нельзя переводить средства на тот же счет того же поставщика"},
                    status=400,
                )

            new_source_supplier_account = SupplierAccount.objects.filter(
                supplier=new_source_supplier,
                account=new_source_account
            ).first()
            if not new_source_supplier_account or new_source_supplier_account.balance < amount_value:
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно средств на счете поставщика-отправителя"},
                    status=400,
                )

            old_source_account.balance += old_amount
            old_source_account.save()
            old_destination_account.balance -= old_amount
            old_destination_account.save()

            if old_source_supplier:
                old_source_supplier_account, _ = SupplierAccount.objects.get_or_create(
                    supplier=old_source_supplier,
                    account=old_source_account,
                    defaults={'balance': 0}
                )
                old_source_supplier_account.balance += old_amount
                old_source_supplier_account.save()

            if old_destination_supplier:
                old_destination_supplier_account = SupplierAccount.objects.filter(
                    supplier=old_destination_supplier,
                    account=old_destination_account
                ).first()
                if old_destination_supplier_account:
                    old_destination_supplier_account.balance -= old_amount
                    old_destination_supplier_account.save()

            new_source_account.balance -= amount_value
            new_source_account.save()
            new_destination_account.balance += amount_value
            new_destination_account.save()

            new_source_supplier_account.balance -= amount_value
            new_source_supplier_account.save()

            new_destination_supplier_account, _ = SupplierAccount.objects.get_or_create(
                supplier=new_destination_supplier,
                account=new_destination_account,
                defaults={'balance': 0}
            )
            new_destination_supplier_account.balance += amount_value
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
            money_transfer.save()

            transfer_purpose = PaymentPurpose.objects.filter(name="Перевод").first()
            if not transfer_purpose:
                transfer_purpose = PaymentPurpose.objects.create(
                    name="Перевод",
                    operation_type=PaymentPurpose.EXPENSE
                )

            CashFlow.objects.filter(
                account=old_source_account,
                supplier=old_source_supplier,
                amount=-old_amount,
                purpose=transfer_purpose,
                comment__icontains=old_destination_supplier.name if old_destination_supplier else ""
            ).delete()
            CashFlow.objects.filter(
                account=old_destination_account,
                supplier=old_destination_supplier,
                amount=old_amount,
                purpose=transfer_purpose,
                comment__icontains=old_source_supplier.name if old_source_supplier else ""
            ).delete()

            CashFlow.objects.create(
                account=new_source_account,
                supplier=new_source_supplier,
                amount=-amount_value,
                purpose=transfer_purpose,
                comment=f"Перевод {new_destination_supplier.name} на счет {new_destination_account.name}"
            )
            CashFlow.objects.create(
                account=new_destination_account,
                supplier=new_destination_supplier,
                amount=amount_value,
                purpose=transfer_purpose,
                comment=f"Получено от {new_source_supplier.name} со счета {new_source_account.name}"
            )

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
            amount = money_transfer.amount

            destination_supplier_account = None
            if destination_supplier:
                destination_supplier_account = SupplierAccount.objects.filter(
                    supplier=destination_supplier,
                    account=destination_account
                ).first()

                if not destination_supplier_account or destination_supplier_account.balance < amount:
                    return JsonResponse(
                        {"status": "error", "message": "Недостаточно средств у отправителя для отмены перевода"},
                        status=400,
                    )

            source_account.balance += amount
            source_account.save()

            destination_account.balance -= amount
            destination_account.save()

            if source_supplier:
                source_supplier_account, created = SupplierAccount.objects.get_or_create(
                    supplier=source_supplier,
                    account=source_account,
                    defaults={'balance': 0}
                )
                source_supplier_account.balance += amount
                source_supplier_account.save()

            if destination_supplier and destination_supplier_account:
                destination_supplier_account.balance -= amount
                destination_supplier_account.save()
            transfer_type = money_transfer.transfer_type
            money_transfer.delete()

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
        if branch and branch.name != "Филиал 1" and branch.name != "Наши Ип":
            branch_debts[branch.name] += float(getattr(t, 'supplier_debt', 0))

    branch_debts_list = [
        {"branch": branch['name'], "debt": branch_debts.get(branch['name'], 0)}
        for branch in branches
    ]

    total_branch_debts = sum(
        branch['debt'] for branch in branch_debts_list if branch['branch'] != "Филиал 1" and branch['branch'] != "Наши Ип"
    )

    total_bonuses = sum(float(t.bonus_debt) for t in transactions)
    total_remaining = sum(float(t.client_debt_paid) for t in transactions)
    total_profit = sum(float(t.profit) for t in transactions if float(t.paid_amount) - float(t.amount) == 0)

    transactionsInvestors = [
        t for t in Transaction.objects.filter(paid_amount__gt=0)
        if getattr(t, 'bonus_debt', 0) == 0
        and getattr(t, 'client_debt', 0) == 0
        # and getattr(t, 'supplier_debt', 0) == 0
        and getattr(t, 'profit', 0) > 0
    ]

    cashflows = CashFlow.objects.filter(
        purpose__operation_type=PaymentPurpose.INCOME
    ).exclude(purpose__name="Оплата")

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
                amount_value = Decimal(amount)
                if amount_value < 0:
                    return JsonResponse({"status": "error", "message": "Сумма должна быть больше нуля"}, status=400)
            except Exception:
                return JsonResponse({"status": "error", "message": "Некорректная сумма"}, status=400)

            if type_ != "balance" and type_ != "initial" and type_ != "short_term_liabilities" and type_ != "credit" and type_ != "equipment" and type_ != "profit":
                trans = get_object_or_404(Transaction, id=pk)

            if type_ == "branch":
                branch = trans.supplier.branch

                supplier_ids = Supplier.objects.filter(branch=branch).values_list('id', flat=True)
                branch_transactions = Transaction.objects.filter(
                    supplier_id__in=supplier_ids,
                    paid_amount__gt=0
                ).order_by('created_at')
                branch_total_debt = sum(float(t.supplier_debt) for t in branch_transactions)

                if amount_value > branch_total_debt:
                    return JsonResponse({"status": "error", "message": "Сумма не может превышать долг филиала"}, status=400)

                remaining = Decimal(str(amount_value))
                repayments = []
                changed_html_rows = []
                changed_ids = []

                for t in branch_transactions:
                    debt = Decimal(str(t.supplier_debt))
                    if debt <= 0 or remaining <= 0:
                        continue
                    repay_amount = min(debt, remaining)
                    t.returned_by_supplier += repay_amount
                    t.returned_date = timezone.now()
                    t.save()
                    remaining -= repay_amount

                    row = type("DebtorRow", (), {})()
                    row.created_at = timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else ""
                    row.supplier = str(t.supplier) if t.supplier else ""
                    row.supplier_percentage = t.supplier_percentage
                    paid = t.paid_amount or Decimal(0)
                    supplier_fee = Decimal(math.floor(float(t.amount) * float(t.supplier_percentage) / 100))
                    row.supplier_debt = paid - supplier_fee - t.returned_by_supplier
                    fields = [
                        {"name": "created_at", "verbose_name": "Дата"},
                        {"name": "supplier", "verbose_name": "Поставщик"},
                        {"name": "supplier_debt", "verbose_name": "Сумма", "is_amount": True},
                        {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True},
                    ]
                    changed_html_rows.append(render_to_string("components/table_row.html", {"item": row, "fields": fields}))
                    changed_ids.append(t.id)

                branch_total_debt = sum(float(t.supplier_debt) for t in branch_transactions)

                cash_account = Account.objects.filter(name__iexact="Наличные").first()
                if cash_account:
                    cash_account.balance += amount_value
                    cash_account.save()

                    # repayment_purpose = PaymentPurpose.objects.filter(name="Погашение долга поставщика").first()
                    # if not repayment_purpose:
                    #     repayment_purpose = PaymentPurpose.objects.create(
                    #         name="Погашение долга поставщика",
                    #         operation_type=PaymentPurpose.INCOME
                    #     )
                    # CashFlow.objects.create(
                    #     account=cash_account,
                    #     amount=amount_value,
                    #     purpose=repayment_purpose,
                    #     supplier=t.supplier,
                    #     comment=f"Погашение долга филиала {branch.name}"
                    # )

                debtRepayment = SupplierDebtRepayment.objects.create(
                    supplier=t.supplier,
                    amount=amount_value,
                    comment=comment
                )
                repayments.append(debtRepayment)
                
                html_debt_repayments = []
                for debtRepayment in repayments:
                    debtRepayment.created_at = timezone.localtime(debtRepayment.created_at).strftime("%d.%m.%Y %H:%M") if debtRepayment.created_at else ""
                    html_debt_repayments.append(render_to_string("components/table_row.html", {
                        "item": debtRepayment,
                        "fields": [
                            {"name": "created_at", "verbose_name": "Дата"},
                            {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                            {"name": "comment", "verbose_name": "Комментарий"}
                        ]
                    }))

                transactions = Transaction.objects.filter(paid_amount__gt=0).exclude(supplier__branch__name="Филиал 1").exclude(supplier__branch__name="Наши Ип")
                all_branches_total_debt = sum(float(t.supplier_debt) for t in transactions)

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

                if amount_value > trans.bonus_debt:
                    return JsonResponse({"status": "error", "message": "Сумма не может превышать долг по бонусам"}, status=400)

                trans.returned_bonus += amount_value
                trans.save()
                row = type("Row", (), {
                    "created_at": timezone.localtime(trans.created_at).strftime("%d.%m.%Y") if trans.created_at else "",
                    "client": str(trans.client) if trans.client else "",
                    "bonus_percentage": trans.bonus_percentage,
                    "bonus_debt": trans.bonus_debt,
                })()
                fields = [
                    {"name": "created_at", "verbose_name": "Дата"},
                    {"name": "client", "verbose_name": "Клиент"},
                    {"name": "bonus_percentage", "verbose_name": "%", "is_percent": True},
                    {"name": "bonus_debt", "verbose_name": "Бонус", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                total_debt = sum(float(t.bonus_debt) for t in Transaction.objects.filter(paid_amount__gt=0))

                transactions = Transaction.objects.filter(paid_amount__gt=0)

                total_bonuses = sum(float(t.bonus_debt) for t in transactions)
                total_remaining = sum(float(t.client_debt_paid) for t in transactions)
                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    # and getattr(t, 'supplier_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                cashflows = CashFlow.objects.filter(
                    purpose__operation_type=PaymentPurpose.INCOME
                ).exclude(purpose__name="Оплата")

                total_profit = sum(float(t.profit - t.returned_to_investor) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

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

                if amount_value > trans.client_debt_paid:
                    return JsonResponse({"status": "error", "message": "Сумма не может превышать долг по выдачам"}, status=400)

                cash_account = Account.objects.filter(name="Наличные").first()
                if not cash_account:
                    return JsonResponse({"status": "error", "message": 'Счет "Наличные" не найден'}, status=400)

                # supplier_account = SupplierAccount.objects.filter(
                #     supplier=trans.supplier,
                #     account=cash_account
                # ).first()

                if not cash_account or cash_account.balance < amount_value:
                    return JsonResponse({"status": "error", "message": "Недостаточно средств на счете 'Наличные'"}, status=400)

                # supplier_account.balance -= amount_value
                # supplier_account.save()
                cash_account.balance -= amount_value
                cash_account.save()

                trans.returned_to_client += amount_value
                trans.save()

                row = type("Row", (), {
                    "created_at": timezone.localtime(trans.created_at).strftime("%d.%m.%Y") if trans.created_at else "",
                    "client": str(trans.client) if trans.client else "",
                    "client_percentage": trans.client_percentage,
                    "client_debt_paid": trans.client_debt_paid,
                })()
                fields = [
                    {"name": "created_at", "verbose_name": "Дата"},
                    {"name": "client", "verbose_name": "Клиент"},
                    {"name": "client_percentage", "verbose_name": "%", "is_percent": True},
                    {"name": "client_debt_paid", "verbose_name": "Выдать", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                total_debt = sum(float(t.client_debt_paid) for t in Transaction.objects.filter(paid_amount__gt=0))

                transactions = Transaction.objects.filter(paid_amount__gt=0)

                total_bonuses = sum(float(t.bonus_debt) for t in transactions)
                total_remaining = sum(float(t.client_debt_paid) for t in transactions)
                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    # and getattr(t, 'supplier_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                cashflows = CashFlow.objects.filter(
                    purpose__operation_type=PaymentPurpose.INCOME
                ).exclude(purpose__name="Оплата")

                total_profit = sum(float(t.profit - t.returned_to_investor) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

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
                    investor.balance += amount_value
                    # cash_account.balance += amount_value
                elif operation_type == "withdrawal":
                    if investor.balance < amount_value:
                        return JsonResponse({"status": "error", "message": "Недостаточно средств для снятия"}, status=400)
                    investor.balance -= amount_value
                    # cash_account.balance -= amount_value

                investor.save()
                # cash_account.save()

                investorDebtOperation = InvestorDebtOperation.objects.create(
                    investor=investor,
                    amount=amount_value,
                    operation_type=operation_type,
                )

                row = type("InvestorRow", (), {
                    "name": investor.name,
                    "initial_balance": investor.initial_balance,
                    "balance": investor.balance,
                })()
                fields = [
                    {"name": "name", "verbose_name": "Инвестор"},
                    {"name": "initial_balance", "verbose_name": "Изначальные инвест", "is_amount": True},
                    {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                transactions = Transaction.objects.filter(paid_amount__gt=0)

                total_bonuses = sum(float(t.bonus_debt) for t in transactions)
                total_remaining = sum(float(t.client_debt_paid) for t in transactions)
                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    # and getattr(t, 'supplier_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                total_profit = sum(float(t.profit) for t in transactionsInvestors)

                investorDebtOperation.created_at = timezone.localtime(investorDebtOperation.created_at).strftime("%d.%m.%Y %H:%M") if investorDebtOperation.created_at else ""
                investorDebtOperation.operation_type = "Внесение" if investorDebtOperation.operation_type == "deposit" else "Забор"

                html_investor_debt_operation = render_to_string("components/table_row.html", {
                    "item": investorDebtOperation,
                    "fields": [
                        {"name": "created_at", "verbose_name": "Дата"},
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

            elif type_ == "initial":
                investor = get_object_or_404(Investor, id=pk)
                investor.initial_balance = amount_value

                investor.save()

                row = type("InvestorRow", (), {
                    "name": investor.name,
                    "initial_balance": investor.initial_balance,
                    "balance": investor.balance,
                })()
                fields = [
                    {"name": "name", "verbose_name": "Инвестор"},
                    {"name": "initial_balance", "verbose_name": "Изначальные инвест", "is_amount": True},
                    {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                transactions = Transaction.objects.filter(paid_amount__gt=0)

                total_bonuses = sum(float(t.bonus_debt) for t in transactions)
                total_remaining = sum(float(t.client_debt_paid) for t in transactions)
                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    # and getattr(t, 'supplier_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                total_profit = sum(float(t.profit) for t in transactionsInvestors)

                summary = [
                    {"name": "Бонусы", "amount": total_bonuses},
                    {"name": "Выдачи клиентам", "amount": total_remaining},
                    {"name": "Инвесторам", "amount": total_profit},
                ]

                total_summary_debts = sum(item['amount'] for item in summary)

                return JsonResponse({
                    "html": html,
                    "id": investor.id,
                    "type": "initial",
                    "total_summary_debts": total_summary_debts,
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
                    if branch_name != "Филиал 1" and branch_name != "Наши Ип":
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
                cash_balance = cash_account.balance if cash_account else Decimal(0)

                safe_amount += cash_balance

                # investors = list(Investor.objects.values("name", "balance"))
                # investors = [{"name": inv["name"], "amount": inv["balance"]} for inv in investors]
                # investors_total = sum([inv["amount"] for inv in investors], Decimal(0))

                bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.all())

                client_debts = sum((t.client_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0).all())

                # assets_total = equipment + Decimal(0) + total_debtors + safe_amount + investors_total

                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    # and getattr(t, 'supplier_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                cashflows = CashFlow.objects.filter(
                    purpose__operation_type=PaymentPurpose.INCOME
                ).exclude(purpose__name="Оплата")

                total_profit = sum(float(t.profit - t.returned_to_investor) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

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
                        # "cash": {"total": safe_amount + investors_total,
                        "cash": {"total": safe_amount,
                                # "items": [{"name": "Счета, Карты и Сейф", "amount": safe_amount}] + investors},
                                "items": [{"name": "Счета, Карты и Сейф", "amount": safe_amount}]},
                    },
                    "assets": assets_total,
                    "liabilities": {
                        "total": liabilities_total,
                        "items": [
                            {"name": "Кредит", "amount": credit},
                            {"name": "Кредиторская задолженность", "amount": client_debts},
                            {"name": "Краткосрочные обязательства", "amount": short_term},
                            {"name": "Бонусы", "amount": bonuses},
                            {"name": "Долг инвесторам", "amount": total_profit},
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
                    trans = get_object_or_404(Transaction, id=pk)

                if trans:
                    if amount_value > (trans.profit - trans.returned_to_investor):
                        return JsonResponse({"status": "error", "message": "Сумма не может превышать долг инвестору"}, status=400)
                elif cashflow:
                    if amount_value > (cashflow.amount - (cashflow.returned_to_investor if cashflow.returned_to_investor is not None else 0)):
                        return JsonResponse({"status": "error", "message": "Сумма не может превышать долг инвестору"}, status=400)
                else:
                    return JsonResponse({"status": "error", "message": "Транзакция или денежный поток не найдены"}, status=400)

                investor_id = request.POST.get("investor_select")

                if not investor_id:
                    return JsonResponse({"status": "error", "message": "Инвестор обязателен"}, status=400)
                
                investor = get_object_or_404(Investor, id=investor_id)

                investor.balance += amount_value
                investor.save()

                investorDebtOperation = InvestorDebtOperation.objects.create(
                    investor=investor,
                    amount=amount_value,
                    operation_type="deposit",
                )

                if trans:
                    trans.returned_to_investor += amount_value
                    trans.save()

                    row = type("Row", (), {
                        "created_at": timezone.localtime(trans.created_at).strftime("%d.%m.%Y") if trans.created_at else "",
                        "client": str(trans.client) if trans.client else "",
                        "amount": trans.amount,
                        "profit": trans.profit - trans.returned_to_investor
                    })()
                elif cashflow:
                    if cashflow.returned_to_investor is None:
                        cashflow.returned_to_investor = Decimal(0)
                    cashflow.returned_to_investor += amount_value
                    cashflow.save()

                    row = type("Row", (), {
                        "created_at": timezone.localtime(cashflow.created_at).strftime("%d.%m.%Y") if cashflow.created_at else "",
                        "client": None,
                        "amount": None,
                        "profit": cashflow.amount - (cashflow.returned_to_investor if cashflow.returned_to_investor is not None else 0)
                    })()

                
                fields = [
                    {"name": "created_at", "verbose_name": "Дата"},
                    {"name": "client", "verbose_name": "Клиент"},
                    {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                    {"name": "profit", "verbose_name": "Прибыль", "is_amount": True},
                ]
                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                investorDebtOperation.created_at = timezone.localtime(investorDebtOperation.created_at).strftime("%d.%m.%Y %H:%M") if investorDebtOperation.created_at else ""
                investorDebtOperation.operation_type = "Внесение" if investorDebtOperation.operation_type == "deposit" else "Забор"

                html_investor_debt_operation = render_to_string("components/table_row.html", {
                    "item": investorDebtOperation,
                    "fields": [
                        {"name": "created_at", "verbose_name": "Дата"},
                        {"name": "investor", "verbose_name": "Инвестор"},
                        {"name": "operation_type", "verbose_name": "Тип операции"},
                        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                    ]
                })

                transactions = Transaction.objects.filter(paid_amount__gt=0)

                total_bonuses = sum(float(t.bonus_debt) for t in transactions)
                total_remaining = sum(float(t.client_debt_paid) for t in transactions)
                transactionsInvestors = [
                    t for t in Transaction.objects.filter(paid_amount__gt=0)
                    if getattr(t, 'bonus_debt', 0) == 0
                    and getattr(t, 'client_debt', 0) == 0
                    # and getattr(t, 'supplier_debt', 0) == 0
                    and getattr(t, 'profit', 0) > 0
                ]

                cashflows = CashFlow.objects.filter(
                    purpose__operation_type=PaymentPurpose.INCOME
                ).exclude(purpose__name="Оплата")

                total_debt = sum(float(t.profit - t.returned_to_investor) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)
                total_profit = sum(float(t.profit - t.returned_to_investor) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

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
                    {"name": "initial_balance", "verbose_name": "Изначальные инвест", "is_amount": True},
                    {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
                ]
                investors = Investor.objects.all()
                investor_data = []
                for inv in investors:
                    investor_data.append(type("InvestorRow", (), {
                        "name": inv.name,
                        "initial_balance": inv.initial_balance,
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

        data['amount'] = float(cashflow.amount - (cashflow.returned_to_investor or 0))
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
    elif type == "investors" or type == "balance" or type == "initial":
        if pk == -1:
            return JsonResponse({"error": "ID инвестора не указан"}, status=400)
        obj = get_object_or_404(Investor, id=pk)
        data = model_to_dict(obj)

        if type == "initial" and obj.initial_balance != 0:
            data["amount"] = float(getattr(obj, "initial_balance", 0))
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
            ).exclude(purpose__name="Оплата")
            total_cashflow_income = sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows if cf.amount > 0)
            data = {}
            data["amount"] = total_investor_debt + total_cashflow_income
            return JsonResponse({"data": data})
        transaction = get_object_or_404(Transaction, id=pk)
        data = model_to_dict(transaction)
        if "amount" in data:
            if "." in type:
                suffix = type.split(".")[1]
                if suffix == "bonus":
                    data["amount"] = float(getattr(transaction, "bonus_debt", 0))
                elif suffix == "remaining":
                    data["amount"] = float(getattr(transaction, "client_debt_paid", 0))
                elif suffix == "investors":
                    data["amount"] = float(getattr(transaction, "investor_debt", 0))
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
        {"name": "created_at", "verbose_name": "Дата"},
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
            {"name": "created_at", "verbose_name": "Дата"},
            {"name": "supplier", "verbose_name": "Поставщик"},
            {"name": "supplier_debt", "verbose_name": "Сумма", "is_amount": True},
            {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True},
        ]
        transaction_data = []
        for t in transactions:
            transaction_data.append(type("Row", (), {
                "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else "",
                "supplier": str(t.supplier) if t.supplier else "",
                "supplier_debt": t.supplier_debt,
                "supplier_percentage": t.supplier_percentage,
            })())

        repayments = SupplierDebtRepayment.objects.filter(supplier_id__in=supplier_ids)
        repayment_fields = [
            {"name": "created_at", "verbose_name": "Дата"},
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
                {"name": "created_at", "verbose_name": "Дата"},
                {"name": "client", "verbose_name": "Клиент"},
                {"name": "client_percentage", "verbose_name": "%", "is_percent": True},
                {"name": "client_debt_paid", "verbose_name": "Выдать", "is_amount": True},
            ]
            data = []
            for t in transactions:
                data.append(type("Row", (), {
                    "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else "",
                    "client": str(t.client) if t.client else "",
                    "client_percentage": t.client_percentage,
                    "client_debt_paid": t.client_debt_paid,
                })())
            table_id = "summary-remaining"
            data_ids = [t.id for t in transactions]

            html = render_to_string(
                "components/table.html",
                {"id": table_id, "fields": fields, "data": data}
            )

            return JsonResponse({"html": html, "table_id": table_id, "data_ids": data_ids})
        elif value == "Бонусы":
            transactions = Transaction.objects.filter(paid_amount__gt=0)
            fields = [
                {"name": "created_at", "verbose_name": "Дата"},
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
                # and getattr(t, 'supplier_debt', 0) == 0 TODO:
                and getattr(t, 'profit', 0) > 0
                and (getattr(t, 'profit', 0) - getattr(t, 'returned_to_investor', 0)) > 0
            ]

            cashflows = CashFlow.objects.filter(
                purpose__operation_type=PaymentPurpose.INCOME,
            ).exclude(purpose__name="Оплата")

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
                {"name": "created_at", "verbose_name": "Дата"},
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
                {"name": "initial_balance", "verbose_name": "Изначальные инвест", "is_amount": True},
                {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
            ]
            investors = Investor.objects.all()
            investor_data = []
            for inv in investors:
                investor_data.append(type("InvestorRow", (), {
                    "name": inv.name,
                    "initial_balance": inv.initial_balance,
                    "balance": inv.balance,
                })())
            investor_ids = [inv.id for inv in investors]
            html_investors = render_to_string(
                "components/table.html",
                {"id": "investors-table", "fields": investor_fields, "data": investor_data}
            )

            investor_operations = InvestorDebtOperation.objects.all()
            operation_fields = [
                {"name": "created_at", "verbose_name": "Дата"},
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
    # payment_purpose = PaymentPurpose.objects.filter(name="Оплата").first()
    # if not payment_purpose:
    #     return JsonResponse({"months": [], "values": []})

    cashflows = CashFlow.objects.filter(
        supplier_id=supplier_id,
        # purpose=payment_purpose,
        created_at__year=current_year
    )

    stats = {month: 0 for month in months}
    for cf in cashflows:
        stats[cf.created_at.month] += float(cf.amount)

    return JsonResponse({
        "months": [datetime(current_year, m, 1).strftime('%b') for m in months],
        "values": [stats[m] for m in months]
    })

@forbid_supplier
@login_required
@require_GET
def company_balance_stats(request):
    equipment = BalanceData.objects.filter(name="Оборудование").aggregate(total=Sum("amount"))["total"] or Decimal(0)
    credit = BalanceData.objects.filter(name="Кредит").aggregate(total=Sum("amount"))["total"] or Decimal(0)
    short_term = BalanceData.objects.filter(name="Краткосрочные обязательства").aggregate(total=Sum("amount"))["total"] or Decimal(0)

    debtors = []
    total_debtors = Decimal(0)
    for branch in Supplier.objects.exclude(branch=None).values_list("branch__id", "branch__name").distinct():
        branch_id, branch_name = branch
        if branch_name != "Филиал 1" and branch_name != "Наши Ип":
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
    cash_balance = cash_account.balance if cash_account else Decimal(0)

    safe_amount += cash_balance

    bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.all())

    client_debts = sum((t.client_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0).all())

    assets_total = equipment + Decimal(0) + total_debtors + safe_amount

    transactionsInvestors = [
        t for t in Transaction.objects.filter(paid_amount__gt=0)
        if getattr(t, 'bonus_debt', 0) == 0
        and getattr(t, 'client_debt', 0) == 0
        # and getattr(t, 'supplier_debt', 0) == 0
        and getattr(t, 'profit', 0) > 0
    ]

    cashflows = CashFlow.objects.filter(
        purpose__operation_type=PaymentPurpose.INCOME
    ).exclude(purpose__name="Оплата")

    total_profit = sum(float(t.profit - t.returned_to_investor) for t in transactionsInvestors) + sum(float(cf.amount - (cf.returned_to_investor or 0)) for cf in cashflows)

    liabilities_total = credit + client_debts + short_term + bonuses + Decimal(total_profit)
    
    current_capital = assets_total - liabilities_total

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
            "inventory": {"total": 0, "items": []},
            "debtors": {"total": total_debtors, "items": debtors},
            "cash": {"total": safe_amount,
                     "items": [{"name": "Счета, Карты и Сейф", "amount": safe_amount}]},
        },
        "assets": assets_total,
        "liabilities": {
            "total": liabilities_total,
            "items": [
                {"name": "Кредит", "amount": credit},
                {"name": "Кредиторская задолженность", "amount": client_debts},
                {"name": "Краткосрочные обязательства", "amount": short_term},
                {"name": "Бонусы", "amount": bonuses},
                {"name": "Выплата инвесторам", "amount": total_profit}
            ],
        },
        "capital": current_capital,
        "capitals_by_month": {
            "months": months,
            "capitals": capitals,
            "total": total_capital
        },
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
    last_day = monthrange(year, month)[1]
    dt_start = timezone.make_aware(datetime(year, month, 1, 0, 0, 0))
    dt_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

    investors_total = sum([
        inv["initial_balance"] for inv in Investor.objects.filter(
            created_at__lte=dt_end
        ).values("initial_balance")
    ], Decimal(0))

    transactions = Transaction.objects.filter(created_at__range=(dt_start, dt_end))
    profit_total = sum((t.profit or Decimal(0)) for t in transactions)

    if profit_total > 0 and investors_total > 0:
        capital_percent = float(profit_total) / float(investors_total) * 100
    else:
        capital_percent = 0

    return round(capital_percent, 1)

def calculate_and_save_monthly_capital(year, month):
    capital = get_monthly_capital(year, month)
    MonthlyCapital.objects.update_or_create(
        year=year, month=month,
        defaults={'capital': capital, 'calculated_at': datetime.now()}
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
            last_name = request.POST.get("last_name")
            first_name = request.POST.get("first_name")
            patronymic = request.POST.get("patronymic")
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
                first_name=first_name,
                last_name=last_name,
                patronymic=patronymic,
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
            last_name = request.POST.get("last_name")
            first_name = request.POST.get("first_name")
            patronymic = request.POST.get("patronymic")
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
            user.first_name = first_name
            user.last_name = last_name
            user.patronymic = patronymic
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
                    {"name": "created_at", "verbose_name": "Дата"},
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
    # transactions = Transaction.objects.select_related('client', 'supplier', 'account').exclude(paid_amount=0)
    cash_flows = CashFlow.objects.select_related('account', 'supplier', 'purpose', 'transaction').all()
    # money_transfers = MoneyTransfer.objects.select_related('source_account', 'destination_account', 'source_supplier', 'destination_supplier').all()
    debt_repayments = SupplierDebtRepayment.objects.select_related('supplier').all()
    investor_ops = InvestorDebtOperation.objects.select_related('investor').all()

    class LogRow:
        def __init__(self, dt, type, info, amount, comment=""):
            self.dt = dt  
            self.date = timezone.localtime(dt).strftime("%d.%m.%Y %H:%M")
            self.type = type
            self.info = info
            self.amount = amount
            self.comment = comment

    rows = []

    # for t in transactions:
    #     rows.append(LogRow(
    #         dt=t.created_at,
    #         type="Транзакция",
    #         info=f"Клиент: {t.client}, Поставщик: {t.supplier}, Счет: {t.account}",
    #         amount=t.paid_amount,
    #         comment=""
    #     ))

    for cf in cash_flows:
        rows.append(LogRow(
            dt=cf.created_at,
            type="Движение ДС",
            info=f"Счет: {cf.account}, Поставщик: {cf.supplier}, Назначение: {cf.purpose}",
            amount=cf.amount,
            comment=cf.comment or ""
        ))

    # for mt in money_transfers:
    #     rows.append(LogRow(
    #         dt=mt.created_at,
    #         type="Перевод",
    #         info=f"От: {mt.source_supplier} ({mt.source_account}) → Кому: {mt.destination_supplier} ({mt.destination_account})",
    #         amount=mt.amount,
    #         comment=""
    #     ))

    for dr in debt_repayments:
        rows.append(LogRow(
            dt=dr.created_at,
            type="Погашение долга",
            info=f"Поставщик: {dr.supplier}",
            amount=dr.amount,
            comment=dr.comment or ""
        ))

    for io in investor_ops:
        rows.append(LogRow(
            dt=io.created_at,
            type=f"Инвестор: {io.get_operation_type_display()}",
            info=f"Инвестор: {io.investor}",
            amount=io.amount,
            comment=""
        ))

    rows.sort(key=lambda x: x.dt, reverse=True)

    fields = [
        {"name": "date", "verbose_name": "Дата"},
        {"name": "type", "verbose_name": "Тип"},
        {"name": "info", "verbose_name": "Инфо"},
        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
        {"name": "comment", "verbose_name": "Комментарий"},
    ]

    html = render_to_string("components/table.html", {
        "id": "money-logs-table",
        "fields": fields,
        "data": rows,
    })

    return JsonResponse({"html": html})

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

            amount_value = Decimal(amount)
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
                        closed.append({"id": item_id, "closed": repay})
                        remaining -= repay
                        if repay < debt:
                            row = type("Row", (), {
                                "created_at": timezone.localtime(obj.created_at).strftime("%d.%m.%Y") if obj.created_at else "",
                                "client": obj.purpose.name if obj.purpose else "",
                                "amount": obj.amount,
                                "profit": obj.amount - obj.returned_to_investor,
                            })()
                            fields = [
                                {"name": "created_at", "verbose_name": "Дата"},
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
                        closed.append({"id": item_id, "closed": repay})
                        remaining -= repay
                        if repay < debt:
                            row = type("Row", (), {
                                "created_at": timezone.localtime(t.created_at).strftime("%d.%m.%Y") if t.created_at else "",
                                "client": str(t.client) if t.client else "",
                                "amount": t.amount,
                                "profit": t.profit - t.returned_to_investor,
                            })()
                            fields = [
                                {"name": "created_at", "verbose_name": "Дата"},
                                {"name": "client", "verbose_name": "Клиент"},
                                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                                {"name": "profit", "verbose_name": "Прибыль", "is_amount": True},
                            ]
                            html_row = render_to_string("components/table_row.html", {"item": row, "fields": fields})
                            changed_html_rows.append({"id": item_id, "html": html_row})

            investor.balance += (amount_value - remaining)
            investor.save()
            investorDebtOperation = InvestorDebtOperation.objects.create(
                investor=investor,
                amount=(amount_value - remaining),
                operation_type="deposit",
            )

            investorDebtOperation.created_at = timezone.localtime(investorDebtOperation.created_at).strftime("%d.%m.%Y %H:%M") if investorDebtOperation.created_at else ""
            investorDebtOperation.operation_type = "Внесение" if investorDebtOperation.operation_type == "deposit" else "Забор"
            html_investor_debt_operation = render_to_string("components/table_row.html", {
                "item": investorDebtOperation,
                "fields": [
                    {"name": "created_at", "verbose_name": "Дата"},
                    {"name": "investor", "verbose_name": "Инвестор"},
                    {"name": "operation_type", "verbose_name": "Тип операции"},
                    {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                ]
            })

            investor_fields = [
                {"name": "name", "verbose_name": "Инвестор"},
                {"name": "initial_balance", "verbose_name": "Изначальные инвест", "is_amount": True},
                {"name": "balance", "verbose_name": "Фактические инвест", "is_amount": True},
            ]
            investor_row = type("InvestorRow", (), {
                "name": investor.name,
                "initial_balance": investor.initial_balance,
                "balance": investor.balance,
            })()
            html_investor_row = render_to_string("components/table_row.html", {"item": investor_row, "fields": investor_fields})

            return JsonResponse({
                "status": "success",
                "closed": closed,
                "amount_closed": float(amount_value - remaining),
                "amount_left": float(remaining),
                "changed_html_rows": changed_html_rows,
                "html_investor_debt_operation": html_investor_debt_operation,
                "html_investor_row": html_investor_row,
                "investor_id": investor.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)