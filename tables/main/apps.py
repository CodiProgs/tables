from django.apps import AppConfig
from django.db.models.signals import post_migrate


class MainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "main"

    def ready(self):
        from django.apps import apps

        def create_initial_data(sender, **kwargs):
            # Импорты моделей внутри обработчика (иначе при ready может быть слишком рано)
            Investor = apps.get_model("main", "Investor")
            PaymentPurpose = apps.get_model("main", "PaymentPurpose")
            AccountType = apps.get_model("main", "AccountType")
            Account = apps.get_model("main", "Account")
            Branch = apps.get_model("main", "Branch")

            for name in ["Инвестор 1", "Инвестор 2"]:
                Investor.objects.get_or_create(name=name)

            PaymentPurpose.objects.get_or_create(
                name="Оплата", operation_type=PaymentPurpose.INCOME
            )

            for name in ["Банковская карта", "Банковский счет", "Наличные"]:
                AccountType.objects.get_or_create(name=name)

            accounts = [
                ("Карта физ 1", "Банковская карта"),
                ("Карта физ 2", "Банковская карта"),
                ("Наличные", "Наличные"),
                ("Р/C Сбер", "Банковский счет"),
                ("Р/с Авангард", "Банковский счет"),
                ("Р/с Альфа", "Банковский счет"),
                ("Р/с Втб", "Банковский счет"),
            ]
            for acc_name, type_name in accounts:
                acc_type, _ = AccountType.objects.get_or_create(name=type_name)
                Account.objects.get_or_create(name=acc_name, account_type=acc_type)

            for name in ["Филиал 1", "Филиал 2"]:
                Branch.objects.get_or_create(name=name)

        post_migrate.connect(create_initial_data, sender=self)
