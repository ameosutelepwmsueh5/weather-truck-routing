import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")

def _env_list(name, default):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


# Configuration comes from environment variables (see .env.example).
# Safe by default: DEBUG is on only for a zero-config local checkout. As soon as a real
# DJANGO_SECRET_KEY is configured (i.e. a deployment) it defaults to off, so forgetting
# DJANGO_DEBUG can never ship a debug server.
_HAS_SECRET = bool(os.environ.get("DJANGO_SECRET_KEY"))
DEBUG = os.environ.get("DJANGO_DEBUG", "false" if _HAS_SECRET else "true").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
if not DEBUG and not _HAS_SECRET:
    raise RuntimeError("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=false.")
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,0.0.0.0")
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):  # set automatically by Render
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # hosts terminate TLS at a proxy
    SECURE_CONTENT_TYPE_NOSNIFF = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "corsheaders",
    "routing",
]
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = []
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CORS_ALLOWED_ORIGINS = _env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "routing.views.api_exception_handler",
    # Per-IP limits. Every analysis fans out to OSRM/Open-Meteo and every keystroke batch
    # to Photon, so a public URL needs a ceiling to protect the free upstream quotas.
    "DEFAULT_THROTTLE_RATES": {
        "analyze": os.environ.get("ANALYZE_RATE_LIMIT", "15/min"),
        "places": os.environ.get("PLACES_RATE_LIMIT", "60/min"),
    },
}
