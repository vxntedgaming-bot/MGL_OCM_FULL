from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User


class ManagerRegistrationForm(forms.Form):

    username = forms.CharField(
        max_length=150,
        label="Username"
    )

    email = forms.EmailField(
        label="Email"
    )

    display_name = forms.CharField(
        max_length=100,
        label="Display Name"
    )

    gamertag = forms.CharField(
        max_length=100,
        label="EA FC Gamertag"
    )

    preferred_team = forms.CharField(
        max_length=100,
        required=False,
        label="Preferred Team"
    )

    password = forms.CharField(
        widget=forms.PasswordInput,
        label="Password"
    )

    confirm_password = forms.CharField(
        widget=forms.PasswordInput,
        label="Confirm Password"
    )

    def clean_username(self):
        username = self.cleaned_data["username"]

        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(
                "This username is already registered."
            )

        return username

    def clean_email(self):
        email = self.cleaned_data["email"]

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                "This email is already registered."
            )

        return email

    def clean(self):
        cleaned_data = super().clean()

        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password:

            if password != confirm_password:
                raise ValidationError(
                    "The passwords do not match."
                )

            validate_password(password)

        return cleaned_data
