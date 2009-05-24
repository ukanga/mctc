from models import Expense
from models import Items
from django.contrib import admin

class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("item", "cost", "expense_date")

admin.site.register(Items)
admin.site.register(Expense, ExpenseAdmin)