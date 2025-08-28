from django.apps import AppConfig
from django.db.models.signals import post_migrate

class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'

    def ready(self):
        from django.contrib.auth import get_user_model
        from .models import UserType
        def create_default_usertypes(sender, **kwargs):
            UserType = sender.get_model("UserType")
            defaults = ['Администратор', 'Поставщик', 'Ассистент', 'Бухгалтер']
            for name in defaults:
                UserType.objects.get_or_create(name=name)

        post_migrate.connect(create_default_usertypes, sender=self)