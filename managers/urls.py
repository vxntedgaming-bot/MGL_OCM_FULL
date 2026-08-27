from django.contrib.auth import views as auth_views
from django.urls import path

from .views import manager_register


urlpatterns = [
    path("register/", manager_register, name="manager_register"),

    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="managers/login.html"
        ),
        name="manager_login",
    ),

    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="manager_logout",
    ),
]
