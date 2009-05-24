#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4
#from django.http import HttpResponseRedirect
#from django.template import RequestContext
#from django.shortcuts import get_object_or_404
from django.db.models import Q
#from django.contrib.auth.models import User, Group
#from django.db import connection


from apps.webui.shortcuts import as_html, login_required
from apps.reusable_table.table import get

# some webui defaults
app = {}
app['name'] = "RapidResponse"


@login_required
def expense_list(request):
    nonhtml, tables = get(request, (["expense", Q()],))
    if nonhtml:
        return nonhtml
    context = {
		"app": app,
        "expense": tables[0],
    }    
    return as_html(request, "expenselist.html", context)