from django.contrib.auth import get_user_model
from django.shortcuts import render

from .forms import ManagerRegistrationForm
from .models import ManagerApplication


User = get_user_model()


def manager_register(request):

    if request.method == "POST":
        form = ManagerRegistrationForm(request.POST)

        if form.is_valid():

            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )

            user.role = User.MANAGER
            user.is_active = False
            user.save()

            ManagerApplication.objects.create(
                user=user,
                display_name=form.cleaned_data["display_name"],
                gamertag=form.cleaned_data["gamertag"],
                preferred_team=form.cleaned_data["preferred_team"],
            )

            return render(
                request,
                "managers/registration_success.html",
            )

    else:
        form = ManagerRegistrationForm()

    return render(
        request,
        "managers/register.html",
        {"form": form},
    )
