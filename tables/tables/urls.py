from django.contrib import admin
from django.urls import path, include
from . import views
from django.contrib.auth.views import LogoutView

handler404 = "tables.views.error_404_view"
handler403 = "tables.views.error_403_view"

urlpatterns = [
    path('admin/', admin.site.urls),
	path(
        "login/",
        views.CustomLoginView.as_view(),
        name="login",
    ),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
	path("", include("main.urls")),
	path('', include('users.urls', namespace='users')),
	path(
        "components/<str:template_name>/",
        views.ComponentView.as_view(),
        name="global_component_view",
    ),
    path(
        "components/<str:app_name>/<str:template_name>/",
        views.ComponentView.as_view(),
        name="app_component_view",
    ),
	path("block/", views.block_site, name="block_site"),
	path("site-unavailable/", views.site_unavailable, name="site_unavailable"),
]
