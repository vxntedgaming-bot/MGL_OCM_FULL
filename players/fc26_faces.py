"""FC26 player-face helpers.

Face URLs come from `fc26_players_raw.csv` (`player_face_url` on cdn.sofifa.net).
Sofifa blocks hotlinking from other origins, so cards load faces through a
same-origin view that fetches the stored Sofifa URL and caches the PNG.
"""

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET

from players.models import Player

SOFIFA_HOST = "cdn.sofifa.net"
SOFIFA_PATH_PREFIX = "/players/"
SOFIFA_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Referer": "https://sofifa.com/",
    "Accept": "image/png",
    "Accept-Encoding": "identity",
}
FACE_CACHE_DIRNAME = "player_faces"
MAX_FACE_BYTES = 400_000
ALLOWED_SIZES = {"60", "120"}


def stored_face_url(player):
    url = (getattr(player, "player_face_url", None) or "").strip()
    if is_http_url(url):
        return url
    url = (getattr(player, "image_url", None) or "").strip()
    if is_http_url(url):
        return url
    return ""


def is_http_url(value):
    value = (value or "").strip()
    return value.startswith("https://") or value.startswith("http://")


def is_sofifa_face_url(value):
    value = (value or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.netloc != SOFIFA_HOST:
        return False
    if parsed.query or parsed.fragment:
        return False
    path = parsed.path or ""
    return path.startswith(SOFIFA_PATH_PREFIX) and path.endswith(".png")


def sofifa_url_for_size(url, size):
    size = str(size)
    if size not in ALLOWED_SIZES or not is_sofifa_face_url(url):
        return url
    if url.endswith("_120.png") and size == "60":
        return url[:-8] + "_60.png"
    if url.endswith("_60.png") and size == "120":
        return url[:-7] + "_120.png"
    return url


def card_face_src(player, size="standard"):
    raw = stored_face_url(player)
    if not raw or not getattr(player, "pk", None):
        return ""
    if is_sofifa_face_url(raw):
        url = reverse("player_face_image", args=[player.pk])
        if size == "small":
            return f"{url}?s=60"
        return url
    return raw


def face_cache_dir():
    path = Path(settings.MEDIA_ROOT) / FACE_CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def face_cache_path(player, size):
    ident = "".join(
        char for char in str(player.fc27_id or player.pk) if char.isalnum()
    )
    if not ident:
        ident = str(player.pk)
    return face_cache_dir() / f"{ident}_{size}.png"


def fetch_sofifa_png(url):
    if not is_sofifa_face_url(url):
        return None
    request = Request(url, headers=SOFIFA_FETCH_HEADERS)
    try:
        with urlopen(request, timeout=8) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            payload = response.read(MAX_FACE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None
    if not payload or len(payload) > MAX_FACE_BYTES:
        return None
    if payload.startswith(b"\x89PNG"):
        return payload
    if "png" in content_type:
        return payload
    return None


@require_GET
def player_face_image(request, player_id):
    player = get_object_or_404(Player, pk=player_id)
    source = stored_face_url(player)
    if not is_sofifa_face_url(source):
        raise Http404("No FC26 face")

    size = request.GET.get("s", "120")
    if size not in ALLOWED_SIZES:
        size = "120"

    cache_file = face_cache_path(player, size)
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return _png_response(cache_file)

    payload = fetch_sofifa_png(sofifa_url_for_size(source, size))
    if payload is None and size != "120":
        payload = fetch_sofifa_png(sofifa_url_for_size(source, "120"))
        cache_file = face_cache_path(player, "120")
    if payload is None:
        raise Http404("Face unavailable")

    cache_file.write_bytes(payload)
    return _png_response(cache_file)


def _png_response(path):
    response = HttpResponse(path.read_bytes(), content_type="image/png")
    response["Cache-Control"] = "public, max-age=604800, immutable"
    return response
