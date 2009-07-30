#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4
from django.http import HttpResponseRedirect
from django.template import RequestContext
from django.shortcuts import get_object_or_404
from django.db.models import ObjectDoesNotExist, Q
from django.contrib.auth.models import User, Group
from django.db import connection

from apps.mctc.models.logs import MessageLog, EventLog
from apps.mctc.models.general import Case, Zone, Provider
from apps.mctc.models.reports import ReportMalnutrition, ReportMalaria, ReportDiagnosis, ReportDiarrhea

from apps.webui.shortcuts import as_html, login_required
from apps.webui.forms.general import MessageForm

from datetime import datetime, timedelta
import time

from urllib import quote, urlopen
from apps.reusable_tables.table import get

# reportlab
from django.template import Template, Context
from django.template.loader import get_template
from django.core.paginator import Paginator, InvalidPage
from django.http import HttpResponse, HttpResponseRedirect
try:
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph
    from reportlab.platypus import Table as PDFTable
    from reportlab.platypus import TableStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib import colors 
except ImportError:
    pass

import os
import csv
import StringIO

from tempfile import mkstemp

# some webui defaults
app = {}
app['name'] = "RapidReport:Health"

# not quite sure how to figure this out programatically
domain = "localhost"
port = "8080"

def message_users(mobile, message=None, groups=None, users=None):
    # problems that might still exist here
    # timeouts in the browser because we have to post all the messages
    # timeouts in the url request filtering up to the above
    recipients = []
    # get all the users
    provider_objects = [ Provider.objects.get(id=user) for user in users ]
    for provider in provider_objects:
        try:
            if provider not in recipients:
                recipients.append(provider)
        except models.ObjectDoesNotExist:
            pass
     # get all the users for the groups
    group_objects = [ Group.objects.get(id=group) for group in groups ]
    for group in group_objects:
        for user in group.user_set.all():
            try:
                if user.provider not in recipients:
                    recipients.append(user.provider)
            except models.ObjectDoesNotExist:
                pass
    
    passed = []
    failed = []
    for recipient in recipients:
        msg = quote("@%s %s" % (recipient.id, message))
        cmd = "http://%s:%s/spomc/%s/%s" % (domain, port, mobile, msg)
        try:
            urlopen(cmd).read()
            passed.append(recipient)
        except IOError:
            # if the mobile number is badly formed and the number regex fails
            # this is the error that is raised
            failed.append(recipient)
    
    results_text = ""
    if not passed and not failed:
        results_text = "No recipients were sent that message."
    elif not failed and passed:
        results_text = "The message was sent to %s recipients" % (len(passed))
    elif failed and passed:
        results_text = "The message was sent to %s recipients, but failed for the following: %s" % (len(passed), ", ".join([ str(f) for f in failed]))
    elif not passed and failed:
        results_text = "No-one was sent that message. Failed for the following: %s" % ", ".join([ str(f) for f in failed])
    return results_text

def get_graph(length=100, filter=Q()):
    end = datetime.now().date()
    start = end - timedelta(days=100)
    results = ReportMalnutrition.objects\
        .filter(Q()).exclude(muac=None)\
        .filter(entered_at__gt=start)\
        .filter(entered_at__lte=end)\
        .order_by("-entered_at")\
        .values_list("muac", "entered_at")
    results = [ [ time.mktime(r[1].timetuple()) * 1000,  r[0] ] for r in results ]
    results = { "start":'"%s"' % start.strftime("%Y/%m/%d"), "end":'"%s"' % end.strftime("%Y/%m/%d"), "results":results }
    return results
    
def get_summary():
    # i can't figure out a good way to do this, i'm sure it will all change, so
    # let's do slow and dirty right now
    seen = []
    status = {
        ReportMalnutrition.MODERATE_STATUS: 0,
        ReportMalnutrition.SEVERE_STATUS: 0,
        ReportMalnutrition.SEVERE_COMP_STATUS: 0,
        ReportMalnutrition.HEALTHY_STATUS: 0,
    }
    
    # please fix me
    for rep in ReportMalnutrition.objects.order_by("-entered_at"):
        if rep.status:
            if rep.id not in seen:
                seen.append(rep.id)
            status[rep.status] += 1

    data = {
        "mam": status[ReportMalnutrition.MODERATE_STATUS],
        "sam": status[ReportMalnutrition.SEVERE_STATUS],
        "samplus": status[ReportMalnutrition.SEVERE_COMP_STATUS],
    }
    return data

@login_required
def dashboard(request):
    nonhtml, tables = get(request, [
        ["case", Q()],
        ["event", Q()],
        ["message", Q()],
    ])
    if nonhtml:
        return nonhtml

    has_provider = True
    context = {
		"app": app,
        "case_table": tables[0],
        "event_table": tables[1],
        "message_table": tables[2]
    }    

    try:
        mobile = request.user.provider.mobile
        if request.method == "POST":
            messageform = MessageForm(request.POST)
            if messageform.is_valid():
                result = message_users(mobile, **messageform.cleaned_data)
                context["msg"] = result
        else:
            messageform = MessageForm()
    except ObjectDoesNotExist:
        has_provider = False
        messageform = None

    context.update({
			"app": app,
            "message_form": messageform,
            "has_provider": has_provider,
            "summary": get_summary(),
            "graph": get_graph()
        })

    return as_html(request, "dashboard.html", context)

@login_required
def search_view(request):
    term = request.GET.get("q")
    query = Q(id__icontains=term) | \
            Q(first_name__icontains=term) | \
            Q(last_name__icontains=term)

    nonhtml, tables = get(request, [ ["case", query], ])
    if nonhtml: 
        return nonhtml

    return as_html(request, "searchview.html", { "search": tables[0], })

@login_required
def case_view(request, object_id):
    case = get_object_or_404(Case, id=object_id)
    nonhtml, tables = get(request, [
        ["malnutrition", Q(case=case)],
        ["diagnosis", Q(case=case)],
        ["malaria", Q(case=case)],
        ["event", Q(content_type="case", object_id=object_id)],
        ["diarrhea", Q(case=case)],
        ])

    if nonhtml:
        return nonhtml

    context = {
		"app": app,
        "object": case,
        "malnutrition": tables[0],
        "diagnosis": tables[1],
        "malaria": tables[2],
        "event": tables[3],
        "diarrhea": tables[4],
    }
    return as_html(request, "caseview.html", context)

@login_required
def district_view(request):
    district = request.GET.get("d")
    context = {
		"app": app,
        "districts": Zone.objects.all(),
    }
    if district:
        nonhtml, tables = get(request, (["case", Q(zone=district)],))
        if nonhtml:
            return nonhtml
        context["cases"] = tables[0]

    return as_html(request, "districtview.html", context)

@login_required
def provider_list(request):
    nonhtml, tables = get(request, (["provider", Q()],))
    if nonhtml:
        return nonhtml
    context = {
		"app": app,
        "provider": tables[0],
    }
    return as_html(request, "providerlist.html", context)

@login_required
def provider_view(request, object_id):
    provider = get_object_or_404(Provider, id=object_id)
    nonhtml, tables = get(request, (
        ["case", Q(provider=provider)],
        ["message", Q(sent_by=provider.user)],
        ["event", Q(content_type="provider", object_id=provider.pk)]
        ))
    if nonhtml:
        return nonhtml
    context = {
		"app": app,
        "object": provider,
        "cases": tables[0],
        "messages": tables[1],
        "event": tables[2]
    }
    return as_html(request, "providerview.html", context)

def month_end(date):
    for n in (31,30,28):
        try:
            return date.replace(day=n)
        except: pass
    return date

def next_month(date):
    if date.day > 28:
        day     = 28
    else:
        day     = date.day
    if date.month == 12:
        month   = 1
        year    = date.year + 1
    else:
        month   = date.month + 1
        year    = date.year
        
    return date.replace(day=day, month=month, year=year)
    
def day_start(date):
    t   = date.time().replace(hour=0,minute=1)
    return datetime.combine(date.date(), t)

def day_end(date):
    t   = date.time().replace(hour=23,minute=59)
    return datetime.combine(date.date(), t)

@login_required
def globalreports_view(request):

    now = datetime.today()
    first   = Case.objects.order_by('created_at')[:1][0]
    date    = first.created_at

    months=[]
    while ((now - date).days > 0):
        months.append({'id': date.strftime("%m%Y"), 'label': date.strftime("%B %Y"), 'date': date})
        date = next_month(date)

    context = {
		"app": app,
	    "providers": Provider.objects.filter(active=True),
	    "months": months
    }
    return as_html(request, "globalreportsview.html", context)

@login_required
def report_view(request, report_name, object_id=None):
    part = report_name.partition('_')
    if part.__len__() == 3:
        report_name = part[0]
        format  = part[2]
    else:
        format  = 'csv'
        
    if report_name  == 'monitoring':
        month   = datetime(int(object_id[2:6]), int(object_id[:2]), 1)
        filename    = "%(report)s_%(date)s.%(ext)s" % {'report':report_name, 'date': month.strftime("%B-%Y"), 'ext':format}
        return report_monitoring_csv(request, object_id, filename)
        
    queryset, fields = build_report(report_name, object_id)
    filename    = "%(report)s_%(date)s.%(ext)s" % {'report':report_name, 'date': datetime.today().strftime("%Y-%m-%d"), 'ext':format}
    
    return eval("handle_%s" % format)(request, queryset, fields, filename)
    
def handle_csv(request, queryset, fields, file_name):
    output = StringIO.StringIO()
    csvio = csv.writer(output)
    header = False
    for row in queryset:
        ctx = Context({"object": row })
        if not header:
            csvio.writerow([f["name"] for f in fields])
            header = True
        values = [ Template(h["bit"]).render(ctx) for h in fields ]
        csvio.writerow(values)

    response = HttpResponse(mimetype='text/csv')
    response['Content-Disposition'] = "attachment; filename=%s" % file_name
    response.write(output.getvalue())
    return response
    
def handle_pdf(request, queryset, fields, file_name):

    # this is again some quick and dirty sample code    
    elements = []
    styles = getSampleStyleSheet()
    styles['Title'].alignment = TA_LEFT
    styles['Title'].fontName = styles['Heading2'].fontName = "Helvetica"
    styles["Normal"].fontName = "Helvetica"
    filename = mkstemp(".pdf")[-1]
    doc = SimpleDocTemplate(filename)

    elements.append(Paragraph("MCTC", styles['Title']))
    elements.append(Paragraph("%s List" % file_name, styles['Heading2'])) #

    data = []
    header = False
    for row in queryset:
        if not header:
            data.append([f["name"] for f in fields])
            header = True
        ctx = Context({"object": row })
        values = [ Template(h["bit"]).render(ctx) for h in fields ]
        data.append(values)

    table = PDFTable(data)
    table.setStyle(TableStyle([
        ('ALIGNMENT', (0,0), (-1,-1), 'LEFT'),
        ('LINEBELOW', (0,0), (-1,-0), 2, colors.black),            
        ('LINEBELOW', (0,1), (-1,-1), 0.8, colors.lightgrey),
        ('FONT', (0,0), (-1, -1), "Helvetica"),
        ('ROWBACKGROUNDS', (0,0), (-1, -1), [colors.whitesmoke, colors.white]),
    ]))
    elements.append(table)
    elements.append(Paragraph("-", styles["Normal"]))
    elements.append(Paragraph("Created: %s" % datetime.now().strftime("%d/%m/%Y"), styles["Normal"]))        
    doc.build(elements)

    response = HttpResponse(mimetype='application/pdf')
    response['Content-Disposition'] = "attachment; filename=%s" % file_name
    response.write(open(filename).read())
    os.remove(filename)
    return response
    
def build_report(report_name, object_id):

    qs      = []
    fields  = []

    # Patients Report
    if report_name  == 'all-patient':
        cases   = Case.objects.all()
    elif report_name == 'provider':
        provider    = Provider.objects.filter(id=object_id)
        cases   = Case.objects.filter(provider=provider)
                
    for case in cases:
        q   = {}
        q['case']   = case
        
        try:
            muacc   = ReportMalnutrition.objects.get(case=case)
            q['malnut'] = u"%(diag)s on %(date)s" % {'diag': muacc.diagnosis_msg(), 'date': muacc.entered_at.strftime("%Y-%m-%d")}
        except ObjectDoesNotExist:
            q['malnut'] = None

        try:
            orsc   = ReportDiarrhea.objects.get(case=case)
            q['diarrhea'] = u"%(diag)s on %(date)s" % {'diag': orsc.diagnosis_msg(), 'date': orsc.entered_at.strftime("%Y-%m-%d")}
        except ObjectDoesNotExist:
            q['diarrhea'] = None
            
        try:
            mrdtc   = ReportMalaria.objects.get(case=case)
            mrdtcd  = mrdtc.get_dictionary()
            q['malaria'] = u"result:%(res)s bednet:%(bed)s obs:%(obs)s on %(date)s" % {'res': mrdtcd['result_text'], 'bed': mrdtcd['bednet_text'], 'obs': mrdtcd['observed'], 'date': mrdtc.entered_at.strftime("%Y-%m-%d")}
        except ObjectDoesNotExist:
            q['malaria'] = None
            
        try:
            dc      = ReportDiagnosis.objects.get(case=case)
            dcd     = dc.get_dictionary()
            q['diagnosis'] = u"diag:%(diag)s labs:%(lab)s on %(date)s" % {'diag': dcd['diagnosis'], 'lab': dcd['labs_text'], 'date': dc.entered_at.strftime("%Y-%m-%d")}
        except ObjectDoesNotExist:
            q['diagnosis'] = None
        
        qs.append(q)
    
    fields.append({"name": 'Ref#', "column": None, "bit": "{{ object.case.ref_id }}" })
    fields.append({"name": 'Gender', "column": None, "bit": "{{ object.case.gender }}" })
    fields.append({"name": 'Age', "column": None, "bit": "{{ object.case.age }}" })
    fields.append({"name": 'Guardian', "column": None, "bit": "{{ object.case.guardian }}" })
    fields.append({"name": 'Provider', "column": None, "bit": "{{ object.case.provider.get_name_display }}" })
    fields.append({"name": 'Zone', "column": None, "bit": "{{ object.case.zone }}" })
    fields.append({"name": 'Village', "column": None, "bit": "{{ object.case.village }}" })
    fields.append({"name": 'District', "column": None, "bit": "{{ object.case.district }}" })
    fields.append({"name": 'Malnutrition', "column": None, "bit": "{{ object.malnut }}" })
    fields.append({"name": 'Diarrhea', "column": None, "bit": "{{ object.diarrhea }}" })
    fields.append({"name": 'Malaria', "column": None, "bit": "{{ object.malaria }}" })
    fields.append({"name": 'Diagnosis', "column": None, "bit": "{{ object.diagnosis }}" })
   
    return qs, fields

def report_monitoring_csv(request, object_id, file_name):
    output = StringIO.StringIO()
    csvio = csv.writer(output)
    header = False
    
    # parse parameter
    month   = datetime(int(object_id[2:6]), int(object_id[:2]), 1)
    
    # Header Line (days of month)
    eom = month_end(month)
    days= range(-1, eom.day + 1)
    days.remove(0)
    gdays   = days # store that good list
    csvio.writerow([d.__str__().replace("-1", month.strftime("%B")) for d in days])
    
    # Initialize Rows
    sms_num     = ["# SMS Sent"]
    sms_process = ["Processed"]
    sms_refused = ["Refused"]
    
    chw_tot     = ["Total CHWs in System"]
    chw_reg     = ["New CHWs Registered"]
    chw_reg_err = ["Failed Registration"]

    chw_on      = ["Active CHWS"]

    patient_reg = ["New Patients Registered"]
    patient_reg_err = ["Registration Failed"]

    malaria_tot = ["Total Malaria Reports"]
    malaria_err = ["Malaria Reports (Failed)"]

    malaria_pos = ["Malaria Tests Positive"]
    bednet_y_pos= ["Bednet Yes"]
    bednet_n_pos= ["Bednet No"]
    malaria_neg = ["Malaria Tests False"]
    bednet_y_neg= ["Bednet Yes"]
    bednet_n_neg= ["Bednet No"]

    malnut_tot  = ["Total Malnutrition Reports"]
    malnut_err  = ["Malnutrition Reports (Failed)"]

    sam_tot     = ["Total SAM+"]
    mam_tot     = ["Total MAM"]

    samp_new    = ["New SAM+"]
    sam_new     = ["New SAM"]
    mam_new     = ["New MAM"]

    user_msg    = ["User Messaging"]
    
    blank       = []

    # List all rows    
    rows    = [blank, sms_num, sms_process, sms_refused, blank, chw_tot, chw_reg, chw_reg_err, blank,
    chw_on, blank, patient_reg, patient_reg_err, blank, malaria_tot, malaria_err, blank, 
    malaria_pos, bednet_y_pos, bednet_n_pos, malaria_neg, bednet_y_neg, bednet_n_neg, blank,
    malnut_tot, malnut_err, blank, sam_tot, mam_tot, blank, samp_new, sam_new, mam_new, blank, user_msg]
    
    # Loop on days
    for d in gdays:
        if d == -1: continue
        ref_date    = datetime(month.year, month.month, d)
        morning     = day_start(ref_date)
        evening     = day_end(ref_date)
        
        # Number of SMS Sent
        sms_num.append(MessageLog.objects.filter(created_at__gte=morning, created_at__lte=evening).count())

    # Write rows on CSV
    for row in rows:
        csvio.writerow([cell for cell in row])
    
    response = HttpResponse(mimetype='text/csv')
    response['Content-Disposition'] = "attachment; filename=%s" % file_name
    response.write(output.getvalue())
    return response

