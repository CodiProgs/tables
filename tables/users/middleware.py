from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin
from users.models import SiteBlock

class AuthMiddleware(MiddlewareMixin):
    EXEMPT_URLS = ["login", "site-unavailable", "block"]

    def process_view(self, request, view_func, view_args, view_kwargs):
        url_name = request.resolver_match.url_name or ""
        path = request.path or ""

        if path.startswith("/components/"):
            return None

        block = SiteBlock.objects.first()
        is_admin_hidden = request.user.is_authenticated and request.user.username == "admin_hidden"

        if block and block.is_blocked and not is_admin_hidden:
            if url_name != "site-unavailable" and path not in ["/site-unavailable", "/site-unavailable/"] and not path.startswith("/static/"):
                return HttpResponseRedirect(reverse("site_unavailable"))
            return None

        if not request.user.is_authenticated:
            if url_name not in self.EXEMPT_URLS and not url_name.startswith("webauthn"):
                return HttpResponseRedirect(reverse("login"))
        else:
            if url_name == "login" or path in ["/login", "/login/"]:
                return HttpResponseRedirect(reverse("main:index"))