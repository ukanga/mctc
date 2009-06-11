#!/usr/bin/env python

import sys
import os
path = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__))))
sys.path.append(path)

os.environ['RAPIDSMS_INI'] = os.path.join(path, "rapidsms.ini")
os.environ['DJANGO_SETTINGS_MODULE'] = 'rapidsms.webui.settings'
    
import rapidsms
from apps.mctc.models.general import *
from apps.mctc.models.reports import *
from datetime import *

from rapidsms.backends.spomc import *
from rapidsms import *

os.environ['RAPIDSMS_INI'] = os.path.join(path, "rapidsms.ini")
os.environ['DJANGO_SETTINGS_MODULE'] = 'rapidsms.webui.settings'

def _(txt): return txt

import time
import spomsky

server  = spomsky.Client()

now     = datetime.today()

# look for opened case
reports = ReportDiarrhea.objects.filter(status__in = (ReportDiarrhea.MODERATE_STATUS, ReportDiarrhea.DANGER_STATUS), entered_at__lt=(now - timedelta(1)), entered_at__gt=(now - timedelta(2)))

for report in reports:
    print "Report: %s" % report.case

    info = report.case.get_dictionary()
    info.update(report.get_dictionary())
   
    if report.status == ReportDiarrhea.MODERATE_STATUS:
        # confirm responding well to treatment
        info['followup']    = "Confirm respond well tp treatment"

    else:
        # confirm seen at clinic and OK
        info['followup']    = "Confirm seen at clinic and OK"

    msg = _("DIARRHEA> +%(ref_id)s %(last_name)s, %(first_name_short)s, %(gender)s/%(months)s (%(guardian)s). %(followup)s. History: %(days)s, %(ors)s") % info

    print ">> %s: %s" % (report.provider.mobile, msg)
    server.send(report.provider.mobile, msg)


