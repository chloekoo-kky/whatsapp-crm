"""
Django settings for Clinic CRM (clinic_crm project).
"""

from pathlib import Path
from urllib.parse import unquote, urlparse

import environ
import os

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
_env_file = BASE_DIR / ".env"
if _env_file.is_file():
    environ.Env.read_env(_env_file)

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default=os.getenv("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me"),
)

DEBUG = str(env("DJANGO_DEBUG", default="True")).lower() in ("1", "true", "yes")

_allowed = env(
    "DJANGO_ALLOWED_HOSTS",
    default=os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,testserver,https://advance-ronald-complexity-omissions.trycloudflare.com",
    ),
)
ALLOWED_HOSTS = [
    h.strip().removeprefix("https://").removeprefix("http://").split("/")[0]
    for h in str(_allowed).split(",")
    if h.strip()
]

_csrf_origins = env(
    "CSRF_TRUSTED_ORIGINS",
    default=os.getenv("CSRF_TRUSTED_ORIGINS", ""),
)
CSRF_TRUSTED_ORIGINS = []
for _raw in str(_csrf_origins).split(","):
    _o = _raw.strip()
    if not _o:
        continue
    if _o.startswith("http://") or _o.startswith("https://"):
        CSRF_TRUSTED_ORIGINS.append(_o)
    else:
        _host = _o.removeprefix("https://").removeprefix("http://").split("/")[0]
        if _host:
            CSRF_TRUSTED_ORIGINS.append(f"https://{_host}")

SERPER_API_KEY = env("SERPER_API_KEY", default="")
# Reserved for future AI features (not used by the app today).
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")

# Serper Maps hunt: default total leads to import; max per hunt (paginated in 20-result pages).
HUNT_DEFAULT_LIMIT = env.int("HUNT_DEFAULT_LIMIT", default=100)
HUNT_MAX_LIMIT = env.int("HUNT_MAX_LIMIT", default=100)

def _env_str(name: str, *, default: str = "") -> str:
    """Prefer live process env (Docker env_file), then django-environ / mounted .env."""
    direct = (os.environ.get(name) or "").strip()
    if direct:
        return direct
    return (env(name, default=default) or "").strip()


YCLOUD_API_KEY = (os.environ.get("YCLOUD_API_KEY") or _env_str("YCLOUD_API_KEY")).strip()
YCLOUD_WEBHOOK_SECRET = (os.environ.get("YCLOUD_WEBHOOK_SECRET") or _env_str("YCLOUD_WEBHOOK_SECRET")).strip()
YCLOUD_WABA_ID = (os.environ.get("YCLOUD_WABA_ID") or _env_str("YCLOUD_WABA_ID")).strip()
# E.164 business sender (e.g. +60126336529). Required for YCloud outbound ``from``.
WHATSAPP_FROM_NUMBER = (
    os.environ.get("WHATSAPP_FROM_NUMBER") or _env_str("WHATSAPP_FROM_NUMBER")
).strip() or (
    os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or _env_str("WHATSAPP_PHONE_NUMBER_ID")
).strip()
WHATSAPP_BUSINESS_ACCOUNT_ID = (
    os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID") or _env_str("WHATSAPP_BUSINESS_ACCOUNT_ID")
).strip()
WHATSAPP_TEMPLATE_NAME = "just_to_say_hi"
WHATSAPP_TEMPLATE_LANGUAGE = "en"
# Legacy Meta direct API (optional fallback for old webhooks only).
WHATSAPP_ACCESS_TOKEN = (os.environ.get("WHATSAPP_ACCESS_TOKEN") or _env_str("WHATSAPP_ACCESS_TOKEN")).strip()
WHATSAPP_PHONE_NUMBER_ID = (
    os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or _env_str("WHATSAPP_PHONE_NUMBER_ID")
).strip()
WHATSAPP_GRAPH_API_VERSION = _env_str("WHATSAPP_GRAPH_API_VERSION", default="v20.0")
WHATSAPP_APP_SECRET = (os.environ.get("WHATSAPP_APP_SECRET") or _env_str("WHATSAPP_APP_SECRET")).strip()
WHATSAPP_WEBHOOK_VERIFY_TOKEN = (
    os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
    or _env_str("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
    or "CLINIC_CRM_WEBHOOK_73R469Mf"
).strip()
WHATSAPP_CAMPAIGN_TIMEZONE = _env_str(
    "WHATSAPP_CAMPAIGN_TIMEZONE", default="Asia/Kuala_Lumpur"
)


def _database_from_env() -> dict:
    url = env("DATABASE_URL", default=os.getenv("DATABASE_URL", "")).strip()
    if not url:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ValueError(
            "When DATABASE_URL is set, scheme must be postgres or postgresql."
        )
    path = parsed.path or ""
    name = unquote(path.lstrip("/"))
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or 5432),
    }


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "leads.apps.LeadsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "clinic_crm.urls"

_template_ctx = [
    "django.template.context_processors.request",
    "django.contrib.auth.context_processors.auth",
    "django.contrib.messages.context_processors.messages",
]

# When DEBUG is True, skip django.template.loaders.cached.Loader so edits to HTML
# templates are visible on refresh without restarting Gunicorn/Docker workers.
if DEBUG:
    TEMPLATES = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": False,
            "OPTIONS": {
                "context_processors": _template_ctx,
                "loaders": [
                    "django.template.loaders.filesystem.Loader",
                    "django.template.loaders.app_directories.Loader",
                ],
            },
        },
    ]
else:
    TEMPLATES = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": _template_ctx,
            },
        },
    ]

WSGI_APPLICATION = "clinic_crm.wsgi.application"

DATABASES = {"default": _database_from_env()}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

NINJA_PAGINATION_PER_PAGE = 50
