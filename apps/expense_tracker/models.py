from symbol import except_clause
from django.db import models

# Create your Django models here, if you need them.

class Items(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    short_code = models.CharField(max_length=5)
    datecreated = models.DateTimeField("date created");

    def __unicode__(self):
        return self.name + " " + self.short_code
    
class Expense(models.Model):
    item = models.ForeignKey(Items)
    cost = models.FloatField()
    expense_date = models.DateTimeField("Expense Date")
    who = models.CharField(max_length=20)
    given_code = models.CharField(max_length=20)

    