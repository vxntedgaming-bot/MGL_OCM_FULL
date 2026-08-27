"""
Django settings for the existing MGL Online Career Mode project.

Local development keeps working without a .env file (SQLite, DEBUG=True,
console email). Production values come from environment variables.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import (
    database_config,
    env_bool,
    env_csv,
    env_int,
    env_str,
    load_project_env,
)

BASE_DIR = Path(__file__).resolve().parent.parent
load_project_env(BASE_DIR)

# Development-only fallback. Production must set DJANGO_SECRET_KEY.
_DEV_SECRET_KEY = (
    "django-insecure-#ho(7keo$@uxg72t44a$1rlccicc@yl98(k!&yw8_8#ob&nhzc"
)

DEBUG = env_bool("DJANGO_DEBUG", True)

SECRET_KEY = env_str("DJANGO_SECRET_KEY", _DEV_SECRET_KEY if DEBUG else None)
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY when DJANGO_DEBUG is False."
    )
if not DEBUG and SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be a non-development value when DEBUG is False."
    )

if DEBUG:
    ALLOWED_HOSTS = env_csv(
        "DJANGO_ALLOWED_HOSTS",
        ["127.0.0.1", "localhost", "testserver"],
    )
else:
    ALLOWED_HOSTS = env_csv("DJANGO_ALLOWED_HOSTS")
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            "Set DJANGO_ALLOWED_HOSTS when DJANGO_DEBUG is False."
        )

CSRF_TRUSTED_ORIGINS = env_csv(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    ["http://127.0.0.1:8000", "http://localhost:8000"] if DEBUG else [],
)


INSTALLED_APPS = [
    "core",
    "accounts",
    "leagues",
    "teams",
    "managers",
    "players",
    "auctions",
    "mgl",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "mgl.context_processors.mgl_nav",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": database_config(BASE_DIR),
}


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


STATIC_URL = env_str("DJANGO_STATIC_URL", "/static/")
STATIC_ROOT = Path(env_str("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

MEDIA_URL = env_str("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = Path(env_str("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))

# Serve uploaded logos from Django when DEBUG, or when explicitly enabled
# for a single-process production host without a separate media server.
SERVE_MEDIA = DEBUG or env_bool("DJANGO_SERVE_MEDIA", False)

WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_AUTOREFRESH = DEBUG

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedStaticFilesStorage"
        ),
    },
}


CONSOLE_EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SMTP_EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

_email_backend = env_str(
    "DJANGO_EMAIL_BACKEND",
    CONSOLE_EMAIL_BACKEND if DEBUG else SMTP_EMAIL_BACKEND,
)

if _email_backend == CONSOLE_EMAIL_BACKEND:
    MAILERS = {
        "default": {
            "BACKEND": CONSOLE_EMAIL_BACKEND,
        },
    }
else:
    _email_options = {}
    if env_str("EMAIL_HOST"):
        _email_options["host"] = env_str("EMAIL_HOST")
    if env_str("EMAIL_PORT"):
        _email_options["port"] = env_int("EMAIL_PORT", 587)
    if env_str("EMAIL_HOST_USER"):
        _email_options["username"] = env_str("EMAIL_HOST_USER")
    if env_str("EMAIL_HOST_PASSWORD"):
        _email_options["password"] = env_str("EMAIL_HOST_PASSWORD")
    if env_str("EMAIL_TIMEOUT"):
        _email_options["timeout"] = env_int("EMAIL_TIMEOUT", 10)
    if env_bool("EMAIL_USE_TLS", False):
        _email_options["use_tls"] = True
    if env_bool("EMAIL_USE_SSL", False):
        _email_options["use_ssl"] = True
    MAILERS = {
        "default": {
            "BACKEND": _email_backend,
            "OPTIONS": _email_options,
        },
    }

DEFAULT_FROM_EMAIL = env_str(
    "DEFAULT_FROM_EMAIL",
    "webmaster@localhost" if DEBUG else "MGL <noreply@localhost>",
)
SERVER_EMAIL = env_str("SERVER_EMAIL", DEFAULT_FROM_EMAIL)


if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
else:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", True)
    SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
        True,
    )
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", True)
    if env_bool("DJANGO_USE_X_FORWARDED_PROTO", True):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
