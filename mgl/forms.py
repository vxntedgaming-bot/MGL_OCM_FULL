from django import forms
from decimal import Decimal
from .models import TeamMatchStats, DefenderRating, GKSave

class TeamStatsForm(forms.ModelForm):
    class Meta:
        model=TeamMatchStats
        fields=["goals","shots","possession"]
        widgets={"goals":forms.NumberInput(attrs={"min":0,"max":30}),"shots":forms.NumberInput(attrs={"min":0,"max":100}),"possession":forms.NumberInput(attrs={"min":0,"max":100})}

class DefenderRatingForm(forms.ModelForm):
    class Meta:
        model=DefenderRating
        fields=["player","rating"]
        widgets={"rating":forms.NumberInput(attrs={"min":"0","max":"10","step":"0.1"})}

class GKSaveForm(forms.ModelForm):
    class Meta:
        model=GKSave
        fields=["player","saves"]
        widgets={"saves":forms.NumberInput(attrs={"min":1,"max":20})}
