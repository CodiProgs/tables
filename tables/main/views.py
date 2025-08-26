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

locale.setlocale(locale.LC_ALL, "ru_RU.UTF-8")
locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")


def forbid_supplier(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if hasattr(request.user, 'user_type') and getattr(request.user.user_type, 'name', None) == 'Поставщик':
            from django.shortcuts import redirect
            return redirect('main:debtors')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


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
    if user_type == 'Поставщик':
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

    supplier_debts = [getattr(t, 'supplier_debt', 0) for t in page.object_list]
    client_debts = [getattr(t, 'client_debt', 0) for t in page.object_list]
    bonus_debts = [getattr(t, 'bonus_debt', 0) for t in page.object_list]

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
        },
    }

    return render(request, "main/main.html", context)

def get_transaction_fields(is_accountant, is_assistant=False):
    excluded = [
        "id", "amount", "client_percentage", "bonus_percentage",
        "supplier_percentage", "paid_amount", "modified_by_accountant",
        "viewed_by_admin", "returned_date", "returned_by_supplier", "returned_bonus", "returned_to_client"
    ]

    field_order = [
        "created_at", "client", "supplier", "amount", "client_percentage",
        "remaining_amount", "bonus_percentage", "bonus",
    ]
    if not is_accountant:
        field_order.extend(["supplier_percentage", "profit"])
    field_order.extend(["paid_amount", "debt", "documents"])

    if is_assistant:
        field_order = [
            "created_at", "client", "supplier", "amount", "paid_amount", "documents"
        ]

    fields = get_model_fields(
        Transaction,
        excluded_fields=excluded,
        field_order=field_order,
    )

    insertions = [
        (3, {"name": "amount", "verbose_name": "Сумма", "is_amount": True, }),
        (4, {"name": "client_percentage", "verbose_name": "%", "is_percent": True, }),
        (5, {"name": "remaining_amount", "verbose_name": "Выдать", "is_amount": True }),
        (6, {"name": "bonus_percentage", "verbose_name": "%", "is_percent": True, }),
        (7, {"name": "bonus", "verbose_name": "Бонус", "is_amount": True}),
    ]

    if not is_accountant:
        insertions.extend([
            (8, {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True, }),
            (9, {"name": "profit", "verbose_name": "Прибыль", "is_amount": True}),
        ])

    insertions.extend([
        (10 if not is_accountant else 8, {"name": "paid_amount", "verbose_name": "Оплачено", "is_amount": True}),
        (11 if not is_accountant else 9, {"name": "debt", "verbose_name": "Долг", "is_amount": True}),
    ])

    if is_assistant:
        insertions = [
            (3, {"name": "amount", "verbose_name": "Сумма", "is_amount": True, }),
            (4, {"name": "paid_amount", "verbose_name": "Оплачено", "is_amount": True}),
        ]

    for pos, field in insertions:
        fields.insert(pos, field)

    return fields

@forbid_supplier
@login_required
def transaction_detail(request, pk: int):
    transaction = get_object_or_404(Transaction, id=pk)
    return JsonResponse({"data": model_to_dict(transaction)})

@forbid_supplier
@login_required
def client_list(request):
    clients_data = Client.objects.values('id', 'name')
    return JsonResponse(list(clients_data), safe=False)

@forbid_supplier
@login_required
def supplier_list(request):
    suppliers_data = Supplier.objects.select_related('default_account').values('id', 'name', 'default_account__name')
    result = [
        {
            'id': s['id'],
            'name': f"{s['name']} {s['default_account__name']}" if s['default_account__name'] else s['name']
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

            if not all([client_id, supplier_id, amount]):
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
                viewed_by_admin=not is_accountant
            )

            context = {
                "item": trans,
                "fields": get_transaction_fields(is_accountant, is_assistant),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": trans.id,
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

            is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False

            if not is_admin:
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно прав для выполнения действия"},
                    status=403
                )

            trans = get_object_or_404(Transaction, id=pk)

            client_id = request.POST.get("client")
            supplier_id = request.POST.get("supplier")
            amount = clean_currency(request.POST.get("amount"))
            client_percentage = clean_percentage(request.POST.get("client_percentage"))
            bonus_percentage = clean_percentage(request.POST.get("bonus_percentage", "0"))
            supplier_percentage = clean_percentage(request.POST.get("supplier_percentage"))

            if not all([client_id, supplier_id, amount]):
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

            client_percentage = client_percentage or client.percentage
            supplier_percentage = supplier_percentage or supplier.cost_percentage

            if not bonus_percentage:
                bonus_percentage = 0

            trans.client = client
            trans.supplier = supplier
            trans.amount = int(float(amount))
            trans.client_percentage = float(client_percentage)
            trans.bonus_percentage = float(bonus_percentage)
            trans.supplier_percentage = float(supplier_percentage)

            is_accountant = request.user.user_type.name == 'Бухгалтер' if hasattr(request.user, 'user_type') else False
            is_assistant = request.user.user_type.name == 'Ассистент' if hasattr(request.user, 'user_type') else False

            if is_accountant:
                trans.modified_by_accountant = True
                trans.viewed_by_admin = False
            trans.save()

            context = {
                "item": trans,
                "fields": get_transaction_fields(is_accountant, is_assistant),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": trans.id,
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

            paid_amount = clean_currency(request.POST.get("paid_amount"))
            documents = request.POST.get("documents") == "on"

            if not paid_amount:
                return JsonResponse(
                    {"status": "error", "message": "Сумма оплаты не может быть пустой"},
                    status=400,
                )

            try:
                amount_float = float(paid_amount)
                if amount_float <= 0:
                    return JsonResponse(
                        {"status": "error", "message": "Сумма должна быть больше нуля"},
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

            previous_paid_amount = trans.paid_amount or 0
            new_paid_amount = int(float(paid_amount))

            payment_difference = new_paid_amount - previous_paid_amount

            if payment_difference > 0 and trans.supplier:
                if not trans.supplier.default_account:
                    return JsonResponse(
                        {"status": "error", "message": "У поставщика не указан счет по умолчанию для платежей"},
                        status=400,
                    )

                account = trans.supplier.default_account
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

            trans.paid_amount = new_paid_amount
            trans.documents = documents
            is_accountant = request.user.user_type.name == 'Бухгалтер' if hasattr(request.user, 'user_type') else False
            is_assistant = request.user.user_type.name == 'Ассистент' if hasattr(request.user, 'user_type') else False

            if is_accountant:
                trans.modified_by_accountant = True
                trans.viewed_by_admin = False

            trans.save()

            context = {
                "item": trans,
                "fields": get_transaction_fields(is_accountant, is_assistant),
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": trans.id,
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
    is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False
    if not is_admin:
        raise PermissionDenied

    suppliers = Supplier.objects.all()

    context = {
        "fields": get_supplier_fields(),
        "data": suppliers,
        "data_ids": [t.id for t in suppliers],
    }

    return render(request, "main/suppliers.html", context)

def get_supplier_fields():
    excluded = [
        "id",
        "cost_percentage",
        "user",
        "visible_for_assistant"
    ]
    fields = get_model_fields(
        Supplier,
        excluded_fields=excluded,
    )

    insertions = [
        (2, {"name": "cost_percentage", "verbose_name": "%", "is_percent": True, }),
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

            if old_percentage != new_percentage:
                Transaction.objects.filter(
                    client=client,
                    client_percentage=old_percentage
                ).update(client_percentage=new_percentage)

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


def get_cash_flow_fields():
    excluded = [
        "id",
        "created_at",
        "amount",
        "transaction"
    ]
    fields = get_model_fields(
        CashFlow,
        excluded_fields=excluded,
    )

    insertions = [
        (2, {"name": "formatted_amount", "verbose_name": "Сумма", "is_text": True}),
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
    suppliers = Supplier.objects.all().order_by('name')

    bank_accounts = Account.objects.order_by('name')

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

    total_row = SupplierAccountRow("ИТОГО", 0)

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
    context = {
        "fields": supplier_fields,
        "data": rows,
        "is_grouped": {"accounts-table": True},
        "is_admin": is_admin,
        "supplier_ids": supplier_ids,
        "account_ids": account_ids
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
            account_id = request.POST.get("default_account")
            visible_for_assistant = request.POST.get("visible_for_assistant") == "on"

            username = request.POST.get("username")
            password = request.POST.get("password")

            if not all([name, branch_id, cost_percentage, account_id]):
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            account = get_object_or_404(Account, id=account_id)
            branch = get_object_or_404(Branch, id=branch_id)

            supplier = Supplier.objects.create(
                name=name,
                branch=branch,
                cost_percentage=float(cost_percentage),
                default_account=account,
                visible_for_assistant=visible_for_assistant,
            )

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

            context = {
                "item": supplier,
                "fields": get_supplier_fields(),
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
            if not pk:
                return JsonResponse(
                    {"status": "error", "message": "ID поставщика не указан"},
                    status=400,
                )

            supplier = get_object_or_404(Supplier, id=pk)
            name = request.POST.get("name")
            branch_id = request.POST.get("branch")
            cost_percentage = clean_percentage(request.POST.get("cost_percentage"))
            account_id = request.POST.get("default_account")
            visible_for_assistant = request.POST.get("visible_for_assistant") == "on"

            username = request.POST.get("username")
            password = request.POST.get("password")

            if not all([name, branch_id, cost_percentage, account_id]):
                return JsonResponse(
                    {"status": "error", "message": "Все поля должны быть заполнены"},
                    status=400,
                )

            account = get_object_or_404(Account, id=account_id)
            branch = get_object_or_404(Branch, id=branch_id)

            old_cost_percentage = float(supplier.cost_percentage)
            new_cost_percentage = float(cost_percentage)

            supplier.name = name
            supplier.branch = branch
            supplier.cost_percentage = float(cost_percentage)
            supplier.default_account = account
            supplier.visible_for_assistant = visible_for_assistant

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

            if old_cost_percentage != new_cost_percentage:
                Transaction.objects.filter(
                    supplier=supplier,
                    supplier_percentage=old_cost_percentage
                ).update(supplier_percentage=new_cost_percentage)

            supplier.save()

            context = {
                "item": supplier,
                "fields": get_supplier_fields(),
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

    data['created_at_formatted'] = cashflow.created_at.strftime("%d.%m.%Y %H:%M") if cashflow.created_at else ""

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

            if not all([amount, purpose_id, supplier_id]):
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

            amount_value = int(float(amount))
            if purpose.operation_type == PaymentPurpose.EXPENSE:
                amount_value = -abs(amount_value)
            else:
                amount_value = abs(amount_value)

            cashflow = CashFlow.objects.create(
                account=supplier.default_account,
                amount=amount_value,
                purpose=purpose,
                supplier=supplier,
            )
            supplier.default_account.balance += amount_value
            supplier.default_account.save()

            supplier_account, created = SupplierAccount.objects.get_or_create(
                supplier=supplier,
                account=supplier.default_account,
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

            if not all([new_supplier_id, new_amount, new_purpose_id]):
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

            new_account = new_supplier.default_account
            if not new_account:
                return JsonResponse({
                    "status": "error",
                    "message": "У поставщика не указан счет по умолчанию"
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
    accounts = Account.objects.all()

    is_collection = request.GET.get('collection') == 'true'
    if is_collection:
        accounts = accounts.exclude(name="Наличные")

    account_data = [
        {"id": acc.id, "name": acc.name} for acc in accounts
    ]
    return JsonResponse(account_data, safe=False)

@forbid_supplier
@login_required
def payment_purpose_list(request):
    payment_purpose_data = [
        {"id": acc.id, "name": acc.name}
        for acc in PaymentPurpose.objects.filter(operation_type=PaymentPurpose.EXPENSE)
    ]
    return JsonResponse(payment_purpose_data, safe=False)

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
            source_supplier_id = request.POST.get("source_supplier")
            source_account_id = request.POST.get("source_account")
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

            cash_supplier_account, created = SupplierAccount.objects.get_or_create(
                supplier=source_supplier,
                account=cash_account,
                defaults={'balance': 0}
            )
            cash_supplier_account.balance += amount_value
            cash_supplier_account.save()

            bank_accounts = Account.objects.order_by('name')

            class SupplierAccountRow:
                def __init__(self, supplier_name, supplier_id):
                    self.supplier = supplier_name
                    self.supplier_id = supplier_id

            balances = {}
            account_totals = {account.id: 0 for account in bank_accounts}
            grand_total = 0
            all_supplier_accounts = SupplierAccount.objects.select_related('supplier', 'account').all()

            for sa in all_supplier_accounts:
                balances[(sa.supplier_id, sa.account_id)] = sa.balance
                account_totals[sa.account_id] += sa.balance
                grand_total += sa.balance

            total_row = SupplierAccountRow("ИТОГО", 0)

            for account in bank_accounts:
                setattr(total_row, f'account_{account.id}', format_currency(account_totals[account.id]))

            setattr(total_row, 'total_balance', format_currency(grand_total))

            row = SupplierAccountRow(source_supplier.name, source_supplier.id)

            supplier_total_balance = 0
            for account in bank_accounts:
                balance = balances.get((source_supplier.id, account.id), 0)
                setattr(row, f'account_{account.id}', format_currency(balance))
                supplier_total_balance += balance

            setattr(row, 'total_balance', format_currency(supplier_total_balance))

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

            return JsonResponse({
                "html": render_to_string("components/table_row.html", context_row),
                "total_html": render_to_string("components/table_row.html", context_total),
                "id": source_supplier.id,
                "status": "success",
                "message": f"Инкассация на сумму {amount_value} р. успешно выполнена"
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

    data['created_at_formatted'] = money_transfer.created_at.strftime("%d.%m.%Y %H:%M") if hasattr(money_transfer, 'created_at') else ""

    return JsonResponse({"data": data})

@forbid_supplier
@login_required
@require_http_methods(["POST"])
def money_transfer_create(request):
    try:
        with transaction.atomic():
            source_supplier_id = request.POST.get("source_supplier")
            destination_supplier_id = request.POST.get("destination_supplier")
            amount = clean_currency(request.POST.get("amount"))

            if not all([source_supplier_id, destination_supplier_id, amount]):
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

            source_account = source_supplier.default_account
            destination_account = destination_supplier.default_account

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
                amount=amount_value
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

            suppliers = Supplier.objects.all().order_by('name')
            bank_accounts = Account.objects.order_by('name')

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

            total_row = SupplierAccountRow("ИТОГО", 0)
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
                {"name": "source_account", "verbose_name": "Счет отправителя"},
                {"name": "destination_account", "verbose_name": "Счет получателя"},
                {"name": "source_supplier", "verbose_name": "Поставщик отправитель"},
                {"name": "destination_supplier", "verbose_name": "Поставщик получатель"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True}
            ]

            context = {
                "item": row,
                "fields": fields
            }

            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": money_transfer.id,
                "status": "success",
                "message": f"Перевод на сумму {amount_value} р. успешно выполнен",
                "table_html": html_table
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

            source_supplier_id = request.POST.get("source_supplier")
            destination_supplier_id = request.POST.get("destination_supplier")
            amount = clean_currency(request.POST.get("amount"))

            if not all([source_supplier_id, destination_supplier_id, amount]):
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

            old_source_account = money_transfer.source_account
            old_destination_account = money_transfer.destination_account
            old_source_supplier = money_transfer.source_supplier
            old_destination_supplier = money_transfer.destination_supplier
            old_amount = money_transfer.amount

            new_source_supplier = get_object_or_404(Supplier, id=source_supplier_id)
            new_destination_supplier = get_object_or_404(Supplier, id=destination_supplier_id)

            new_source_account = new_source_supplier.default_account
            new_destination_account = new_destination_supplier.default_account

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

            new_source_supplier_account = SupplierAccount.objects.filter(
                supplier=new_source_supplier,
                account=new_source_account
            ).first()
            if not new_source_supplier_account or new_source_supplier_account.balance < amount_value:
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно средств на счете поставщика-отправителя"},
                    status=400,
                )

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

            money_transfer.source_account = new_source_account
            money_transfer.destination_account = new_destination_account
            money_transfer.source_supplier = new_source_supplier
            money_transfer.destination_supplier = new_destination_supplier
            money_transfer.amount = amount_value
            money_transfer.save()

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
                {"name": "source_account", "verbose_name": "Счет отправителя"},
                {"name": "destination_account", "verbose_name": "Счет получателя"},
                {"name": "source_supplier", "verbose_name": "Поставщик отправитель"},
                {"name": "destination_supplier", "verbose_name": "Поставщик получатель"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True}
            ]

            context = {
                "item": row,
                "fields": fields
            }

            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": money_transfer.id,
                "status": "success",
                "message": f"Перевод успешно обновлен"
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

            is_admin = request.user.user_type.name == 'Администратор' if hasattr(request.user, 'user_type') else False

            if not is_admin:
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно прав для выполнения действия"},
                    status=403
                )
            money_transfer = get_object_or_404(MoneyTransfer, id=pk)

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
                        {"status": "error", "message": "Недостаточно средств у получателя для отмены перевода"},
                        status=400,
                    )

            if destination_account.balance < amount:
                return JsonResponse(
                    {"status": "error", "message": "Недостаточно средств на счете получателя для отмены перевода"},
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

            money_transfer.delete()

            return JsonResponse({
                "status": "success",
                "message": f"Перевод на сумму {amount} р. успешно удален",
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@login_required
def debtors(request):
    user = request.user
    is_admin = hasattr(user, 'user_type') and user.user_type.name == 'Администратор'

    is_supplier = hasattr(request.user, 'user_type') and request.user.user_type.name == 'Поставщик'

    branches = list(Branch.objects.all().values('id', 'name'))

    if is_supplier:
        supplier = get_object_or_404(Supplier, user=user)
        branches = [branch for branch in branches if branch['id'] == supplier.branch_id]

    transactions = Transaction.objects.select_related('supplier__branch').filter(paid_amount__gt=0).all()

    branch_debts = defaultdict(float)
    for t in transactions:
        branch = t.supplier.branch if t.supplier and t.supplier.branch else None
        if branch:
            branch_debts[branch.name] += float(getattr(t, 'supplier_debt', 0))

    branch_debts_list = [
        {"branch": branch['name'], "debt": branch_debts.get(branch['name'], 0)}
        for branch in branches
    ]

    total_branch_debts = sum(branch['debt'] for branch in branch_debts_list)

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

    total_profit = sum(float(t.profit) for t in transactionsInvestors)

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

            if type_ != "investors" and type_ != "short_term_liabilities" and type_ != "credit" and type_ != "equipment":
                trans = get_object_or_404(Transaction, id=pk)

            if type_ == "branch":
                if (amount_value > trans.supplier_debt):
                    return JsonResponse({"status": "error", "message": "Сумма не может превышать долг поставщика"}, status=400)

                from django.utils import timezone

                trans.returned_by_supplier += amount_value
                trans.returned_date = timezone.now()
                trans.save()

                trans.refresh_from_db()

                debtRepayment = SupplierDebtRepayment.objects.create(
                    supplier=trans.supplier,
                    transaction=trans,
                    amount=amount_value,
                    comment=comment
                )

                branch = trans.supplier.branch if trans.supplier and trans.supplier.branch else None
                branch_total_debt = 0
                if branch:
                    supplier_ids = Supplier.objects.filter(branch=branch).values_list('id', flat=True)
                    branch_transactions = Transaction.objects.filter(
                        supplier_id__in=supplier_ids,
                        paid_amount__gt=0
                    )
                    branch_total_debt = sum(float(t.supplier_debt) for t in branch_transactions)
                import math
                row = type("DebtorRow", (), {})()
                row.created_at = trans.created_at.strftime("%d.%m.%Y") if trans.created_at else ""
                row.supplier = str(trans.supplier) if trans.supplier else ""
                row.supplier_percentage = trans.supplier_percentage

                paid = trans.paid_amount or Decimal(0)
                supplier_fee = Decimal(math.floor(float(trans.amount) * float(trans.supplier_percentage) / 100))

                row.supplier_debt = paid - supplier_fee - trans.returned_by_supplier

                fields = [
                    {"name": "created_at", "verbose_name": "Дата"},
                    {"name": "supplier", "verbose_name": "Поставщик"},
                    {"name": "supplier_debt", "verbose_name": "Сумма", "is_amount": True},
                    {"name": "supplier_percentage", "verbose_name": "%", "is_percent": True},
                ]

                html = render_to_string("components/table_row.html", {"item": row, "fields": fields})

                debtRepayment.created_at = debtRepayment.created_at.strftime("%d.%m.%Y %H:%M") if debtRepayment.created_at else ""
                debtRepayment.cost_percentage = debtRepayment.transaction.supplier_percentage if debtRepayment.transaction else ""

                html_debt_repayments = render_to_string("components/table_row.html", {
                    "item": debtRepayment,
                    "fields": [
                        {"name": "created_at", "verbose_name": "Дата"},
                        {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                        {"name": "cost_percentage", "verbose_name": "%", "is_percent": True},
                        {"name": "comment", "verbose_name": "Комментарий"}
                    ]
                })

                transactions = Transaction.objects.filter(paid_amount__gt=0)
                all_branches_total_debt = sum(float(t.supplier_debt) for t in transactions)

                return JsonResponse({
                    "html": html,
                    "html_debt_repayments": html_debt_repayments,
                    "debt_repayment_id": debtRepayment.id,
                    "id": trans.id,
                    "branch": trans.supplier.branch.name.replace(" ", "_") if trans.supplier and trans.supplier.branch else None,
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
                    "created_at": trans.created_at.strftime("%d.%m.%Y") if trans.created_at else "",
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

                total_profit = sum(float(t.profit) for t in transactionsInvestors)

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

                supplier_account = SupplierAccount.objects.filter(
                    supplier=trans.supplier,
                    account=cash_account
                ).first()

                if not supplier_account or supplier_account.balance < amount_value:
                    return JsonResponse({"status": "error", "message": "Недостаточно средств на счете 'Наличные' у поставщика"}, status=400)

                supplier_account.balance -= amount_value
                supplier_account.save()
                cash_account.balance -= amount_value
                cash_account.save()

                trans.returned_to_client += amount_value
                trans.save()

                row = type("Row", (), {
                    "created_at": trans.created_at.strftime("%d.%m.%Y") if trans.created_at else "",
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

                total_profit = sum(float(t.profit) for t in transactionsInvestors)

                summary = [
                    {"name": "Бонусы", "amount": total_bonuses},
                    {"name": "Выдачи клиентам", "amount": total_remaining},
                    {"name": "Инвесторам", "amount": total_profit},
                ]

                total_summary_debts = sum(item['amount'] for item in summary)

                return JsonResponse({
                    "html": html,
                    "id": trans.id,
                    "type": "Выдачи клиентам",
                    "total_debt": total_debt,
                    "total_summary_debts": total_summary_debts,
                    "total_profit": total_profit,
                })

            elif type_ == "investors":
                operation_type = request.POST.get("operation_type")
                if operation_type not in ["withdrawal", "deposit"]:
                    return JsonResponse({"status": "error", "message": "Некорректный тип операции"}, status=400)

                investor = get_object_or_404(Investor, id=pk)

                if operation_type == "deposit":
                    investor.balance += amount_value 
                elif operation_type == "withdrawal":
                    if investor.balance < amount_value:
                        return JsonResponse({"status": "error", "message": "Недостаточно средств для снятия"}, status=400)
                    investor.balance -= amount_value 

                investor.save()

                investorDebtOperation = InvestorDebtOperation.objects.create(
                    investor=investor,
                    amount=amount_value,
                    operation_type=operation_type,
                )

                row = type("InvestorRow", (), {
                    "name": investor.name,
                    "balance": investor.balance,
                })()
                fields = [
                    {"name": "name", "verbose_name": "Инвестор"},
                    {"name": "balance", "verbose_name": "Сумма", "is_amount": True},
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

                investorDebtOperation.created_at = investorDebtOperation.created_at.strftime("%d.%m.%Y %H:%M") if investorDebtOperation.created_at else ""
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
                    "type": "Инвесторы",
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
                    branch_debt = sum(
                        (t.supplier_debt or Decimal(0)) for t in Transaction.objects.filter(supplier__branch_id=branch_id)
                    )
                    debtors.append({"branch": branch_name, "amount": branch_debt})
                    
                    total_debtors += branch_debt
                
                safe_amount = MoneyTransfer.objects.filter(destination_account__name="Наличные").aggregate(total=Sum("amount"))["total"] or Decimal(0)
                safe_amount += MoneyTransfer.objects.filter(source_account__name="Наличные").aggregate(total=Sum("amount"))["total"] or Decimal(0)

                investors = list(Investor.objects.values("name", "balance"))
                investors = [{"name": inv["name"], "amount": inv["balance"]} for inv in investors]
                investors_total = sum([inv["amount"] for inv in investors], Decimal(0))

                bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.all())
                client_debts = sum((t.client_debt or Decimal(0)) for t in Transaction.objects.all())

                assets_total = equipment + Decimal(0) + total_debtors + safe_amount + investors_total
                liabilities_total = credit + client_debts + short_term + bonuses
                capital = assets_total - liabilities_total

                data = {
                    "non_current_assets": {
                        "total": equipment,
                        "items": [{"name": "Оборудование", "amount": equipment}]
                    },
                    "current_assets": {
                        "inventory": {"total": 0, "items": []},
                        "debtors": {"total": total_debtors, "items": debtors},
                        "cash": {"total": safe_amount + investors_total,
                                "items": [{"name": "Сейф", "amount": safe_amount}] + investors},
                    },
                    "assets": assets_total,
                    "liabilities": {
                        "total": liabilities_total,
                        "items": [
                            {"name": "Кредит", "amount": credit},
                            {"name": "Кредиторская задолженность", "amount": client_debts},
                            {"name": "Краткосрочные обязательства", "amount": short_term},
                            {"name": "Бонусы", "amount": bonuses},
                        ],
                    },
                    "capital": capital,
                    "type": "balance"
                }
                return JsonResponse(data, safe=False)

            else:
                return JsonResponse({"status": "error", "message": "Некорректный тип"}, status=400)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@forbid_supplier
@login_required
def debtor_detail(request, type, pk):
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
    elif type == "investors":
        if pk == -1:
            return JsonResponse({"error": "ID инвестора не указан"}, status=400)
        obj = get_object_or_404(Investor, id=pk)
        data = model_to_dict(obj)
    elif type == "transactions":
        if pk == -1:
            return JsonResponse({"error": "ID транзакции не указан"}, status=400)
        transaction = get_object_or_404(Transaction, id=pk)
        data = model_to_dict(transaction)
        if "amount" in data:
            del data["amount"]
    else:
        return JsonResponse({"error": "Unknown type"}, status=400)

    return JsonResponse({"data": data})

@forbid_supplier
@login_required
def profit_distribution(request):
    transactions = Transaction.objects.select_related('client', 'supplier').all().order_by('created_at')

    class ProfitRow:
        def __init__(self, t):
            self.created_at = t.created_at.strftime("%d.%m.%Y") if t.created_at else ""
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
            .select_related('supplier')
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
                "created_at": t.created_at.strftime("%d.%m.%Y") if t.created_at else "",
                "supplier": str(t.supplier) if t.supplier else "",
                "supplier_debt": t.supplier_debt,
                "supplier_percentage": t.supplier_percentage,
            })())

        repayments = SupplierDebtRepayment.objects.filter(supplier_id__in=supplier_ids)
        repayment_fields = [
            {"name": "created_at", "verbose_name": "Дата"},
            {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            {"name": "cost_percentage", "verbose_name": "%", "is_percent": True},
            {"name": "comment", "verbose_name": "Комментарий"}
        ]
        repayment_data = []
        for r in repayments:
            repayment_data.append(type("Row", (), {
                "created_at": r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "",
                "amount": r.amount,
                "cost_percentage": r.transaction.supplier_percentage if r.transaction else "",
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
                    "created_at": t.created_at.strftime("%d.%m.%Y") if t.created_at else "",
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
                    "created_at": t.created_at.strftime("%d.%m.%Y") if t.created_at else "",
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
            ]
            fields = [
                {"name": "created_at", "verbose_name": "Дата"},
                {"name": "client", "verbose_name": "Клиент"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                {"name": "profit", "verbose_name": "Прибыль", "is_amount": True},
            ]
            data = []
            for t in transactions:
                data.append(type("Row", (), {
                    "created_at": t.created_at.strftime("%d.%m.%Y") if t.created_at else "",
                    "client": str(t.client) if t.client else "",
                    "amount": t.amount,
                    "profit": getattr(t, 'profit', 0),
                })())
            table_id = "summary-profit"
            data_ids = [t.id for t in transactions]

            investor_fields = [
                {"name": "name", "verbose_name": "Инвестор"},
                {"name": "balance", "verbose_name": "Сумма", "is_amount": True},
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
                {"name": "created_at", "verbose_name": "Дата"},
                {"name": "investor", "verbose_name": "Инвестор"},
                {"name": "operation_type", "verbose_name": "Тип операции"},
                {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
            ]
            operation_data = []
            for op in investor_operations:
                operation_data.append(type("OperationRow", (), {
                    "created_at": op.created_at.strftime("%d.%m.%Y %H:%M") if op.created_at else "",
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
    payment_purpose = PaymentPurpose.objects.filter(name="Оплата").first()
    if not payment_purpose:
        return JsonResponse({"months": [], "values": []})

    cashflows = CashFlow.objects.filter(
        supplier_id=supplier_id,
        purpose=payment_purpose,
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
        branch_debt = sum(
            (t.supplier_debt or Decimal(0)) for t in Transaction.objects.filter(supplier__branch_id=branch_id, paid_amount__gt=0)
        )
        debtors.append({"branch": branch_name, "amount": branch_debt})
        total_debtors += branch_debt

    safe_amount = SupplierAccount.objects.filter(account__name="Наличные").aggregate(total=Sum("balance"))["total"] or Decimal(0)

    investors = list(Investor.objects.values("name", "balance"))
    investors = [{"name": inv["name"], "amount": inv["balance"]} for inv in investors]
    investors_total = sum([inv["amount"] for inv in investors], Decimal(0))

    bonuses = sum((t.bonus_debt or Decimal(0)) for t in Transaction.objects.all())

    client_debts = sum((t.client_debt or Decimal(0)) for t in Transaction.objects.filter(paid_amount__gt=0).all())

    assets_total = equipment + Decimal(0) + total_debtors + safe_amount + investors_total

    liabilities_total = credit + client_debts + short_term + bonuses
    
    current_capital = assets_total - liabilities_total

    current_year = datetime.now().year
    current_month = datetime.now().month
    capitals = []
    
    MONTHS_RU = [
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"
    ]
    months = [MONTHS_RU[month-1] for month in range(1, 13)]

    for month in range(1, 13):
        if month == current_month:
            capital = float(get_monthly_capital(current_year, month))
        else:
            mc = MonthlyCapital.objects.filter(year=current_year, month=month).first()
            capital = float(mc.capital) if mc else 0
        capitals.append(capital)

    data = {
        "non_current_assets": {
            "total": equipment,
            "items": [{"name": "Оборудование", "amount": equipment}]
        },
        "current_assets": {
            "inventory": {"total": 0, "items": []},
            "debtors": {"total": total_debtors, "items": debtors},
            "cash": {"total": safe_amount + investors_total,
                     "items": [{"name": "Сейф", "amount": safe_amount}] + investors},
        },
        "assets": assets_total,
        "liabilities": {
            "total": liabilities_total,
            "items": [
                {"name": "Кредит", "amount": credit},
                {"name": "Кредиторская задолженность", "amount": client_debts},
                {"name": "Краткосрочные обязательства", "amount": short_term},
                {"name": "Бонусы", "amount": bonuses},
            ],
        },
        "capital": current_capital,
        "capitals_by_month": {
            "months": months,
            "capitals": capitals
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
    dt_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))

    equipment = BalanceData.objects.filter(
        name="Оборудование",
        created_at__lte=dt_end
    ).aggregate(total=Sum("amount"))["total"] or Decimal(0)
    credit = BalanceData.objects.filter(
        name="Кредит",
        created_at__lte=dt_end
    ).aggregate(total=Sum("amount"))["total"] or Decimal(0)
    short_term = BalanceData.objects.filter(
        name="Краткосрочные обязательства",
        created_at__lte=dt_end
    ).aggregate(total=Sum("amount"))["total"] or Decimal(0)

    total_debtors = Decimal(0)
    for branch in Supplier.objects.exclude(branch=None).values_list("branch__id", "branch__name").distinct():
        branch_id, branch_name = branch
        branch_debt = sum(
            (t.supplier_debt or Decimal(0))
            for t in Transaction.objects.filter(
                supplier__branch_id=branch_id,
                paid_amount__gt=0,
                created_at__lte=dt_end
            )
        )
        total_debtors += branch_debt

    safe_amount = SupplierAccount.objects.filter(account__name="Наличные").aggregate(total=Sum("balance"))["total"] or Decimal(0)

    investors_total = sum([
        inv["balance"] for inv in Investor.objects.filter(
            created_at__lte=dt_end
        ).values("balance")
    ], Decimal(0))

    bonuses = sum(
        (t.bonus_debt or Decimal(0))
        for t in Transaction.objects.filter(created_at__lte=dt_end)
    )
    client_debts = sum(
        (t.client_debt or Decimal(0))
        for t in Transaction.objects.filter(paid_amount__gt=0, created_at__lte=dt_end)
    )

    assets_total = equipment + Decimal(0) + total_debtors + safe_amount + investors_total
    liabilities_total = credit + client_debts + short_term + bonuses
    capital = assets_total - liabilities_total

    return capital

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

    users = User.objects.all()

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

            if not all([username, password, user_type_id]):
                return JsonResponse(
                    {"status": "error", "message": "Логин, пароль и тип пользователя обязательны"},
                    status=400,
                )

            if User.objects.filter(username=username).exists():
                return JsonResponse(
                    {"status": "error", "message": "Пользователь с таким логином уже существует"},
                    status=400,
                )

            user_type = get_object_or_404(UserType, id=user_type_id)

            user = User.objects.create(
                email=email,
                username=username,
                first_name=first_name,
                last_name=last_name,
                patronymic=patronymic,
                user_type=user_type,
                is_active=is_active,
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

            if not all([username, user_type_id]):
                return JsonResponse(
                    {"status": "error", "message": "Логин и тип пользователя обязательны"},
                    status=400,
                )

            if User.objects.exclude(pk=user.pk).filter(username=username).exists():
                return JsonResponse(
                    {"status": "error", "message": "Пользователь с таким логином уже существует"},
                    status=400,
                )

            user_type = get_object_or_404(UserType, id=user_type_id)

            user.email = email
            user.username = username
            if password:
                user.set_password(password)
            user.first_name = first_name
            user.last_name = last_name
            user.patronymic = patronymic
            user.user_type = user_type
            user.is_active = is_active
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
    types = UserType.objects.all()

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

            debt_repay.cost_percentage = debt_repay.transaction.supplier_percentage if debt_repay.transaction else None

            context = {
                "item": debt_repay,
                "fields": [
                    {"name": "created_at", "verbose_name": "Дата"},
                    {"name": "amount", "verbose_name": "Сумма", "is_amount": True},
                    {"name": "cost_percentage", "verbose_name": "%", "is_percent": True},
                    {"name": "comment", "verbose_name": "Комментарий"}
                ]
            }
            return JsonResponse({
                "html": render_to_string("components/table_row.html", context),
                "id": debt_repay.id,
            })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
