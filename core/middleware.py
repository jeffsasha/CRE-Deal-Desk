from django.contrib.auth.views import redirect_to_login

OPEN_PATH_PREFIXES = ("/accounts/login", "/static/", "/calendar/feed/")


class LoginRequiredMiddleware:
    """Every page requires sign-in except the login page, static files and the
    token-authenticated calendar feed."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(OPEN_PATH_PREFIXES):
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)
