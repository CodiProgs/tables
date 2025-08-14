from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.contrib.auth import authenticate


class CustomAuthForm(AuthenticationForm):
    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username and password:
            self.user_cache = authenticate(
                request=self.request, username=username, password=password
            )

            if self.user_cache is None:
                raise ValidationError("Неверный логин или пароль")

        return self.cleaned_data
