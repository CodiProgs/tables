from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager
from django.apps import apps
from fido2.utils import websafe_encode, websafe_decode
import base64

def ensure_bytes(data):
    """Преобразует данные в байты с лучшей обработкой ошибок"""
    if data is None:
        return b''
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        try:
            if len(data) % 4 == 0 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in data):
                return base64.b64decode(data)
            else:
                return bytes(data, 'utf-8')
        except Exception as e:
            print(f"Ошибка преобразования в байты: {str(e)}")
            return bytes(data, 'utf-8')
    try:
        return bytes(data)
    except:
        return bytes(str(data), 'utf-8')

class SiteBlock(models.Model):
    is_blocked = models.BooleanField(default=False)

class UserType(models.Model):
    name = models.CharField(max_length=50, verbose_name="Группа пользователей")
    
    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Тип пользователя"
        verbose_name_plural = "Типы пользователей"

class User(AbstractUser):
    username = models.CharField(max_length=150, unique=True, verbose_name="Логин")
    last_name = models.CharField(
        max_length=150, blank=True, null=True, verbose_name="Фамилия"
    )
    first_name = models.CharField(
        max_length=150, blank=True, null=True, verbose_name="Имя"
    )
    patronymic = models.CharField(
        max_length=150, blank=True, null=True, verbose_name="Отчество"
    )
    date_joined = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    user_type = models.ForeignKey(
        UserType,
        on_delete=models.CASCADE,
        verbose_name="Тип пользователя",
        null=True,
        blank=True,
    )

    branch = models.ForeignKey(
        "main.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profile"
    )

    user_permissions = None
    groups = None

    def __str__(self):
        return self.username

    class Meta:
        default_permissions = ()
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

class WebAuthnCredential(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='webauthn_credentials')
    credential_id = models.BinaryField()
    public_key = models.BinaryField()   
    sign_count = models.IntegerField(default=0)

    def credential_id_b64(self):
        return websafe_encode(self.credential_id)

    def public_key_b64(self):
        return websafe_encode(self.public_key)

    def get_credential_id_bytes(self):
        if isinstance(self.credential_id, str):
            return base64.b64decode(self.credential_id)
        return self.credential_id

    def save(self, *args, **kwargs):
        if isinstance(self.credential_id, str):
            self.credential_id = ensure_bytes(self.credential_id)
        if isinstance(self.public_key, str):
            self.public_key = ensure_bytes(self.public_key)
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=['user']),
        ]
        verbose_name = "WebAuthn Credential"
        verbose_name_plural = "WebAuthn Credentials"
