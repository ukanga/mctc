#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4

import os
from django.conf.urls.defaults import patterns

from apps.mctc.models.general import Case
from apps.webui.forms.general import CaseForm

urlpatterns = patterns('',
    (r'^$', "apps.webui.views.general.dashboard"),
    (r'^search/$', "apps.webui.views.general.search_view"),
    (r'^district/$', "apps.webui.views.general.district_view"),    
    (r'^providers/$', "apps.webui.views.general.provider_list"),    
    (r'^provider/view/(?P<object_id>\d+)/$', "apps.webui.views.general.provider_view"),        
    (r'^case/(?P<object_id>\d+)/$', "apps.webui.views.general.case_view"),
    (r'^case/edit/(?P<object_id>\d+)/$', "django.views.generic.create_update.update_object", {
        "template_name": "caseedit.html",
        "form_class": CaseForm
    },
),
    (r'^status/$', "apps.webui.views.general.chwstatus_view"),
    (r'^reports/$', "apps.webui.views.report.reports"),
    (r'^report/(?P<report_name>[a-z\-\_]+)/(?P<object_id>\d*)$', "apps.webui.views.general.report_view"),
    
    (r'^reportlist/$', "apps.webui.views.report.reports"),
    #last_30_days
    (r'^last_30_days/$', "apps.webui.views.report.last_30_days"),
    (r'^last_30_days/(?P<object_id>\d*)$', "apps.webui.views.report.last_30_days"),
    (r'^last_30_days/per_page/(?P<per_page>\d*)$', "apps.webui.views.report.last_30_days"),
    #patients_by_chw
    (r'^patients_by_chw/$', "apps.webui.views.report.patients_by_chw"),
    (r'^patients_by_chw/(?P<object_id>\d*)$', "apps.webui.views.report.patients_by_chw"),
    (r'^patients_by_chw/per_page/(?P<per_page>\d*)$', "apps.webui.views.report.patients_by_chw"),
    # since we can't change settings, we have to do this as accounts/login
    (r'^accounts/login/$', "apps.webui.views.login.login"),    
    (r'^logout/$', "apps.webui.views.login.logout"),
    
    (r'^static/webui/(?P<path>.*)$', "django.views.static.serve",
        {"document_root": os.path.dirname(__file__) + "/static"})
)

