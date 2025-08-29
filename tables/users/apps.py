from django.apps import AppConfig
from django.db.models.signals import post_migrate

class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'

    # def ready(self):
    #     def create_default_usertypes(sender, **kwargs):
    #         apps = kwargs.get("apps")
    #         UserType = apps.get_model("users", "UserType")

    #         defaults = ['Администратор', 'Поставщик', 'Ассистент', 'Бухгалтер']
    #         for name in defaults:
    #             UserType.objects.get_or_create(name=name)


    #     post_migrate.connect(create_default_usertypes, sender=self)
