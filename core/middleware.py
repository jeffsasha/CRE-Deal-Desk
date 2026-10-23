from django.contrib.auth.views import redirect_to_login

OPEN_PATH_PREFIXES = ("/accounts/login", "/static/", "/calendar/feed/", "/i18n/")


class LoginRequiredMiddleware:
    """Every page requires sign-in except the login page, static files and the
    token-authenticated calendar feed."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(OPEN_PATH_PREFIXES):
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)


class AutoLoginMiddleware:
    """Single-user local mode (DEALDESK_AUTO_LOGIN, on by default outside demo mode):
    every request is signed in as the first active administrator, so there is no
    login page. The site only listens on 127.0.0.1. Roles and permission checks
    still apply to that account."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.contrib.auth import login
        from django.shortcuts import redirect

        if settings.AUTO_LOGIN:
            if not request.user.is_authenticated and not request.path.startswith(("/static/", "/calendar/feed/")):
                from .models import User

                owner = User.objects.filter(is_active=True, role="admin").order_by("pk").first()
                if owner is not None:
                    login(request, owner, backend="django.contrib.auth.backends.ModelBackend")
            if request.user.is_authenticated and request.path.startswith("/accounts/"):
                return redirect("hero")
        return self.get_response(request)
