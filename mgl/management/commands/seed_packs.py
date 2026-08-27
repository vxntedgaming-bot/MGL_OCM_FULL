from django.core.management.base import BaseCommand
from decimal import Decimal
from mgl.models import Pack
class Command(BaseCommand):
    def handle(self,*args,**opts):
        data=[("Gold Pack","GOLD",0), ("Silver Pack","SILVER",0),("Bronze Pack","BRONZE",0),("Elite Pack","ELITE",20),("Youth Academy","YOUTH",0)]
        for name,t,c in data: Pack.objects.update_or_create(pack_type=t,defaults={"name":name,"cost":Decimal(str(c))})
        self.stdout.write(self.style.SUCCESS("Packs created/updated."))
