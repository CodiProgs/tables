import traceback

from django.shortcuts import redirect

from main.error_logger import write_error_log
from users.models import SiteBlock


class ServerErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        write_error_log("server", {
            "message": str(exception),
            "stack": traceback.format_exc(),
            "url": request.build_absolute_uri(),
            "method": request.method,
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "ip": request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")),
            "user": str(request.user) if request.user.is_authenticated else "anonymous",
        })
        return None


class BlockSiteMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        block = SiteBlock.objects.first()
        is_admin_hidden = request.user.is_authenticated and request.user.username == "admin_hidden"
        site_unavailable_paths = ['/site-unavailable', '/site-unavailable/']
        if (
            block and block.is_blocked
            and not is_admin_hidden
            and request.path not in site_unavailable_paths
            and not request.path.startswith('/static/')
        ):
            return redirect('/site-unavailable')
        if (
            (not block or not block.is_blocked)
            and request.path in site_unavailable_paths
        ):
            return redirect('/')
        return self.get_response(request)