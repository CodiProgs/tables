from django.shortcuts import render, redirect
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from users.forms import CustomAuthForm
from django.views.generic import TemplateView
from django.http import HttpResponseForbidden, Http404

from django.views.decorators.csrf import csrf_exempt

from django.shortcuts import render, redirect
from users.models import SiteBlock
from django.contrib.auth.decorators import user_passes_test

def is_admin_hidden(user):
    return user.is_authenticated and user.username == "admin_hidden"

def site_unavailable(request):
    return render(request, "site_unavailable.html")

def block_site(request):
    if not is_admin_hidden(request.user):
        raise Http404("Страница не найдена")
    block = SiteBlock.objects.first()
    if not block:
        block = SiteBlock.objects.create(is_blocked=False)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "block":
            block.is_blocked = True
            block.save()
        elif action == "unblock":
            block.is_blocked = False
            block.save()
    return render(request, "block_site.html", {"is_blocked": block.is_blocked})

class CustomLoginView(LoginView):
    template_name = "login.html"
    authentication_form = CustomAuthForm

    def get_success_url(self):
        return reverse_lazy("main:index")
    
def error_404_view(request, exception):
    return render(request, "errors/404.html", status=404)


def error_403_view(request, exception=None):
    return render(request, "errors/403.html", status=403)

class ComponentView(TemplateView):
    def dispatch(self, request, *args, **kwargs):
        if not request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        app_name = kwargs.get("app_name")
        template_name = kwargs.get("template_name")

        if app_name:
            self.template_name = f"{app_name}/components/{template_name}.html"
        else:
            self.template_name = f"components/{template_name}.html"

        context = request.GET.dict()
        return super().render_to_response(context=context)
