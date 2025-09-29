from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('webauthn/register/begin/', views.register_options, name='webauthn_register_begin'),
    path('webauthn/register/complete/', views.register_complete, name='webauthn_register_complete'),
    path('webauthn/authenticate/begin/', views.authenticate_options, name='webauthn_authenticate_begin'),
    path('webauthn/authenticate/complete/', views.authenticate_complete, name='webauthn_authenticate_complete'),
	path('users/list/', views.user_list, name='user_list'),
]