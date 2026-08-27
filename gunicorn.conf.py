import os

port = os.environ.get("PORT")
bind = os.environ.get("GUNICORN_BIND") or (
    f"0.0.0.0:{port}" if port else "0.0.0.0:8000"
)
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
wsgi_app = "config.wsgi:application"
accesslog = "-"
errorlog = "-"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
