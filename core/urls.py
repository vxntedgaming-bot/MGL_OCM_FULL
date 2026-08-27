from django.urls import include, path

from mgl.views import home


urlpatterns = [
    path("", home, name="home"),
    path("mgl/", include("mgl.urls")),
]
