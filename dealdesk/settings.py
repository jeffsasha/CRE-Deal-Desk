"""SKW DealDesk settings.

Configuration comes from environment variables so that secrets never live in the
repository. See README.md for the full list.
"""
import os
import secrets
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# --- Mode -----------------------------------------------------------------
# Demo mode runs against its own database file and storage directory so sample
# records can never appear in real reports.
DEMO_MODE = env_bool("DEALDESK_DEMO")

DATA_DIR = Path(env("DEALDESK_DATA_DIR", BASE_DIR / ("var-demo" if DEMO_MODE else "var")))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key():
    key = env("DJANGO_SECRET_KEY")
    if key:
        return key
    key_file = DATA_DIR / "secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(64))
        key_file.chmod(0o600)
    return key_file.read_text().strip()


SECRET_KEY = _secret_key()
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "crm",
    "properties",
    "deals",
    "documents",
    "deadlines",
    "checklists",
    "commissions",
    "imports",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.AutoLoginMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "dealdesk.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.workspace",
            ],
            "builtins": ["core.templatetags.desk"],
        },
    },
]

WSGI_APPLICATION = "dealdesk.wsgi.application"


def _database_from_url(url):
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": 60,
        }
    if parsed.scheme == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": parsed.path or ":memory:"}
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")


if env("DATABASE_URL") and not DEMO_MODE:
    DATABASES = {"default": _database_from_url(env("DATABASE_URL"))}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / ("demo.sqlite3" if DEMO_MODE else "dealdesk.sqlite3"),
            "OPTIONS": {"init_command": "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;"},
        }
    }

AUTH_USER_MODEL = "core.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Owner shown on the opening page and badge.
OWNER_NAME = env("DEALDESK_OWNER_NAME", "Jeff Lu")
OWNER_GITHUB = env("DEALDESK_OWNER_GITHUB", "https://github.com/jeffsasha")
# The owner's photo stays on this machine (var/brand/photo.*), never in Git.
BRAND_DIR = BASE_DIR / "var" / "brand"

LOGIN_URL = "login"
# Local single-user mode: no login page; requests run as the first administrator.
# Demo mode keeps sign-in so its role accounts can be tried.
AUTO_LOGIN = env_bool("DEALDESK_AUTO_LOGIN", not DEMO_MODE)
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("zh-hans", "简体中文")]
LOCALE_PATHS = [BASE_DIR / "locale"]
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365
TIME_ZONE = "America/Chicago"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = DATA_DIR / "staticfiles"

# Private document storage. Files are never served from a public URL; downloads go
# through a permission-checked view that issues short-lived signed links.
PRIVATE_STORAGE_ROOT = DATA_DIR / "private_storage"
PRIVATE_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
MEDIA_ROOT = PRIVATE_STORAGE_ROOT
DOWNLOAD_LINK_MAX_AGE_SECONDS = int(env("DEALDESK_DOWNLOAD_LINK_SECONDS", "600"))
MAX_UPLOAD_BYTES = int(env("DEALDESK_MAX_UPLOAD_MB", "60")) * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 12
X_FRAME_OPTIONS = "SAMEORIGIN"  # the document viewer embeds our own file stream
SECURE_CONTENT_TYPE_NOSNIFF = True
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30

# --- Integrations ---------------------------------------------------------
# Email reminders are only sent when SMTP is configured.
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "dealdesk@localhost")
EMAIL_CONFIGURED = bool(EMAIL_HOST)

DEALDESK_DEFAULT_TIME_ZONE = "America/Chicago"
DEALDESK_FIRM_NAME = env("DEALDESK_FIRM_NAME", "SKW Realty LLC")
DEALDESK_DEFAULT_REMINDER_DAYS = [7, 3, 1, 0]
DEALDESK_REMINDER_HOUR = 8

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}
