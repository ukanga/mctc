#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4
from django.http import HttpResponseRedirect
from django.template import RequestContext
from django.shortcuts import get_object_or_404
from django.db.models import ObjectDoesNotExist, Q
from django.contrib.auth.models import User, Group
from django.db import connection

from apps.mctc.models.logs import MessageLog, EventLog
from apps.mctc.models.general import Case, Zone, Provider, Facility
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
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.platypus import Table as PDFTable
    from reportlab.platypus import TableStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib import colors 
    from reportlab.lib.pagesizes import A4, LETTER, landscape, portrait
    from reportlab.rl_config import defaultPageSize
    from reportlab.lib.units import inch
    PAGE_HEIGHT=defaultPageSize[1]; PAGE_WIDTH=defaultPageSize[0]
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
def chwstatus_view(request, output="html"):
    if output == "pdf":
        return chwstatus_pdf(request)
    
    now = datetime.today()
    first   = Case.objects.order_by('created_at')[:1][0]
    date    = first.created_at

    months=[]
    while ((now - date).days > 0):
        months.append({'id': date.strftime("%m%Y"), 'label': date.strftime("%B %Y"), 'date': date})
        date = next_month(date)

    #YO
    providers = Provider.objects.order_by("clinic").all()

    duration_start = datetime.today().replace(day=1,month=7)
    duration_end = datetime.now()
    # providers array
    ps = []

    for provider in providers:
        # create provider dict
        p = {}
        p['provider'] = provider
        cases   = Case.objects.filter(provider=provider)
        p['num_cases'] = cases.count()
        p['num_malaria_reports'] = ReportMalaria.objects.filter(entered_at__lte=duration_end, entered_at__gte=duration_start).filter(provider=provider).count()
        p['num_muac_reports'] = ReportMalnutrition.objects.filter(entered_at__lte=duration_end, entered_at__gte=duration_start).filter(provider=provider).count()
        p['sms_sent'] = MessageLog.objects.filter(created_at__lte=duration_end, created_at__gte=duration_start).filter(sent_by=provider.user_id).count()
        p['sms_processed'] = MessageLog.objects.filter(created_at__lte=duration_end, created_at__gte=duration_start).filter(sent_by=provider.user_id, was_handled=True).count()
        p['sms_refused'] = MessageLog.objects.filter(created_at__lte=duration_end, created_at__gte=duration_start).filter(sent_by=provider.user_id,was_handled=False).count()
        if p['sms_sent'] != 0:
            p['sms_rate'] = round(float(p['sms_processed'])/float(p['sms_sent'])*100)
        else:
            p['sms_rate'] = 0
        ps.append(p)
            
    context = {
        "app": app,
        "providers": ps,
        "months": months
    }

    return as_html(request, "chwstatusview.html", context)

def chwstatus_build_report(object_id = None):
    ps      = []
    fields  = []
    counter = 0

    # Providers
    if object_id is None:
        providers = Provider.objects.order_by("clinic").all()
    else:
        providers = Provider.objects.order_by("user").filter(clinic=object_id).all()
    import datetime
    thirty_days = datetime.timedelta(days=30)
    today = datetime.date.today()
    
    duration_start = today - thirty_days
    duration_end = today
    
    for provider in providers:
        p = {}
        counter = counter + 1
        p['counter'] = "%d"%counter
        p['provider'] = provider
        cases   = Case.objects.filter(provider=provider)
        p['num_cases'] = cases.count()
        p['num_malaria_reports'] = ReportMalaria.objects.filter(entered_at__lte=duration_end, entered_at__gte=duration_start).filter(provider=provider).count()
        p['num_muac_reports'] = ReportMalnutrition.objects.filter(entered_at__lte=duration_end, entered_at__gte=duration_start).filter(provider=provider).count()
        p['sms_sent'] = MessageLog.objects.filter(created_at__lte=duration_end, created_at__gte=duration_start).filter(sent_by=provider.user_id).count()
        p['sms_processed'] = MessageLog.objects.filter(created_at__lte=duration_end, created_at__gte=duration_start).filter(sent_by=provider.user_id, was_handled=True).count()
        p['sms_refused'] = MessageLog.objects.filter(created_at__lte=duration_end, created_at__gte=duration_start).filter(sent_by=provider.user_id,was_handled=False).count()
        if p['sms_sent'] != 0:
            p['sms_rate'] = int(float(float(p['sms_processed'])/float(p['sms_sent'])*100))
        else:
            p['sms_rate'] = 0
        #p['sms_rate'] = "%s%%"%p['sms_rate']
        try:
            last_activity_date = MessageLog.objects.order_by("created_at").filter(created_at__lte=today,sent_by=provider.user_id).reverse()[0]
            days_since_last_activity = today - last_activity_date.created_at.date()
            p['days_since_last_activity'] = days_since_last_activity.days 
        except:
            p['days_since_last_activity'] = ""
            
        ps.append(p)
            # caseid +|Y lastname firstname | sex | dob/age | guardian | provider  | date
    fields.append({"name": '#', "column": None, "bit": "{{ object.counter }}" })
    fields.append({"name": 'PROVIDER', "column": None, "bit": "{{ object.provider }}" })
    fields.append({"name": 'NUMBER OF CASES', "column": None, "bit": "{{ object.num_cases}}" })
    fields.append({"name": 'MRDT', "column": None, "bit": "{{ object.num_malaria_reports }}" })
    fields.append({"name": 'MUAC', "column": None, "bit": "{{ object.num_muac_reports }}" })
    fields.append({"name": 'RATE', "column": None, "bit": "{{ object.sms_rate }}% ({{ object.sms_processed }}/{{ object.sms_sent }})" })
    fields.append({"name": 'LAST ACTVITY', "column": None, "bit": "{{ object.days_since_last_activity }}" })
    return ps, fields

def chwstatus_pdf(request):
    # this is again some quick and dirty sample code    
    elements = []
    styles = getSampleStyleSheet()
    styles['Title'].alignment = TA_LEFT
    styles['Title'].fontName = styles['Heading2'].fontName = "Helvetica"
    styles["Normal"].fontName = "Helvetica"
    styles["Normal"].fontSize = 10
    styles["Normal"].fontWeight = "BOLD"
        
    filename = mkstemp(".pdf")[-1]
    doc = SimpleDocTemplate(filename)

    elements.append(Paragraph("RapidResponse MVP Kenya: CHW Last 30 Days Perfomance Report", styles['Title']))
    
    clinics = Provider.objects.values('clinic').distinct()
    for clinic in clinics:
        queryset, fields = chwstatus_build_report(clinic["clinic"])
        c = Facility.objects.filter(id=clinic["clinic"])[0]
        elements.append(Paragraph("%s" % c.name, styles['Heading3']))
        data = []
        header = False
        for row in queryset:
            if not header:
                data.append([f["name"] for f in fields])
                header = True
            ctx = Context({"object": row })
            values = [ Template(h["bit"]).render(ctx) for h in fields ]
            data.append(values)
        
        table = PDFTable(data,None,None,None,1)
        table.setStyle(TableStyle([
            ('ALIGNMENT', (0,0), (-1,-1), 'LEFT'),
            ('LINEBELOW', (0,0), (-1,-0), 2, colors.black),            
            ('LINEBELOW', (0,1), (-1,-1), 0.8, colors.lightgrey),
            ('FONT', (0,0), (-1, -1), "Helvetica", 8),
            ('ROWBACKGROUNDS', (0,0), (-1, -1), [colors.whitesmoke, colors.white]),
        ]))
        table.hAlign = "LEFT"
        elements.append(table)
    '''ctable = PDFTable(cdata)
    ctable.setStyle(TableStyle([
        ('ALIGNMENT', (0,0), (-1,-1), 'LEFT'),
        ('FONT', (0,0), (-1, -1), "Helvetica", 8)
    ]))
    elements.append(ctable)
    '''
    #elements.append(Paragraph("Created: %s" % datetime.now().strftime("%d/%m/%Y"), styles["Normal"]))        
    #doc.pagesize = landscape(A4)
    doc.build(elements, onFirstPage=myFirstPage, onLaterPages=myLaterPages)

    response = HttpResponse(mimetype='application/pdf')
    response['Content-Disposition'] = "attachment; filename=%s" % filename
    response.write(open(filename).read())
    os.remove(filename)
    return response

    
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
    if report_name == "all-patient":        
        filename    = "%(report)s_%(date)s.%(ext)s" % {'report':report_name, 'date': datetime.today().strftime("%Y-%m-%d"), 'ext':format}
        if object_id == "1":
            return all_providers_list_pdf(request, filename,True)
        else:
            return all_providers_list_pdf(request, filename)
    if report_name == "chwstatus":
        return chwstatus_pdf(request)
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

    table = PDFTable(data,None,None,None,1)
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
    doc.pagesize = landscape(A4)
    doc.build(elements)


    response = HttpResponse(mimetype='application/pdf')
    response['Content-Disposition'] = "attachment; filename=%s" % file_name
    response.write(open(filename).read())
    os.remove(filename)
    return response
def myFirstPage(canvas, doc):
    pageinfo = "mCTC"
    canvas.saveState()
    '''canvas.setFont('Times-Bold',16)
    canvas.drawCentredString(PAGE_WIDTH/2.0, PAGE_HEIGHT-108, "RapidResponse MVP Kenya")
    canvas.setFont('Times-Roman',9)
    canvas.drawString(inch, 0.75 * inch, "First Page / %s" % pageinfo)
    '''
    '''textobject = canvas.beginText()
    textobject.setTextOrigin(inch, 0.75*inch)
    textobject.setFont("Times-Roman", 9)
    textobject.textLine("Page %d" % (doc.page))
    textobject.setFillGray(0.4)
    textobject.textLines(pageinfo)
    canvas.hAlign = "CENTER"
    canvas.drawText(textobject)'''
    canvas.restoreState()

def myLaterPages(canvas, doc):
    pageinfo = "RapidResponse MVP Kenya"
    canvas.saveState()
    '''canvas.setFont('Times-Roman',9)
    canvas.drawString(inch, 0.75 * inch, "Page %d %s" % (doc.page, pageinfo))
    '''
    textobject = canvas.beginText()
    textobject.setTextOrigin(inch, 0.75*inch)
    textobject.setFont("Times-Roman", 9)
    textobject.textLine("Page %d" % (doc.page))
    textobject.setFillGray(0.4)
    textobject.textLines(pageinfo)
    canvas.hAlign = "CENTER"
    canvas.drawText(textobject)
    canvas.restoreState()

def all_providers_list_pdf(request, file_name, chw=False):
    zones = Case.objects.values('zone').distinct()
    
    # this is again some quick and dirty sample code    
    elements = []
    styles = getSampleStyleSheet()
    styles['Title'].alignment = TA_LEFT
    styles['Title'].fontName = styles['Heading2'].fontName = "Helvetica"
    styles["Normal"].fontName = "Helvetica"
    styles["Normal"].fontSize = 10
    styles["Normal"].fontWeight = "BOLD"
        
    filename = mkstemp(".pdf")[-1]
    doc = SimpleDocTemplate(filename)

    elements.append(Paragraph("RapidResponse MVP Kenya: %s" % datetime.today().strftime("%Y-%m-%d"), styles['Title']))
    #elements.append(Paragraph(, styles['Heading2'])) #
    for z in zones:
        zone = Zone.objects.filter(id=z['zone'])[0]
        #elements.append(Paragraph("%s" % zone.name, styles['Heading3']))
        providers = Case.objects.filter(zone=z['zone']).values('provider').distinct()
        for p in providers:
            provider    = Provider.objects.filter(id=p['provider'])[0]
            queryset, fields = build_report("provider", p['provider'])
            data = []
            header = False
            for row in queryset:
                if not header:
                    data.append([f["name"] for f in fields])
                    header = True
                ctx = Context({"object": row })
                values = [ Template(h["bit"]).render(ctx) for h in fields ]
                data.append(values)
            
            table = PDFTable(data,None,None,None,1)
            table.setStyle(TableStyle([
                ('ALIGNMENT', (0,0), (-1,-1), 'LEFT'),
                ('LINEBELOW', (0,0), (-1,-0), 2, colors.black),            
                ('LINEBELOW', (0,1), (-1,-1), 0.8, colors.lightgrey),
                ('FONT', (0,0), (-1, -1), "Helvetica", 8),
                ('ROWBACKGROUNDS', (0,0), (-1, -1), [colors.whitesmoke, colors.white]),
            ]))
            table.hAlign = "LEFT"
            elements.append(Paragraph("%s" % zone.name, styles['Heading3']))
            sms_sent = MessageLog.objects.filter(sent_by=provider.user_id).count()
            sms_processed = MessageLog.objects.filter(sent_by=provider.user_id, was_handled=True).count()
            sms_refused = MessageLog.objects.filter(sent_by=provider.user_id,was_handled=False).count()
            if sms_sent != 0:
                sms_rate = round(float(sms_processed)/float(sms_sent)*100)
            else:
                sms_rate = 0
            elements.append(Paragraph("%s : %s SMS Accuracy Rate %s%% (%s/%s)" % (provider.get_name_display(), provider.mobile, sms_rate, sms_processed,sms_sent), styles['Normal'])) 
            
            elements.append(table)
            if chw is True:
                elements.append(PageBreak())
            #elements.append(Paragraph("-", styles["Normal"]))
        elements.append(PageBreak())

    elements.append(Paragraph("Created: %s" % datetime.now().strftime("%d/%m/%Y"), styles["Normal"]))        
    doc.pagesize = landscape(A4)
    doc.build(elements, onFirstPage=myFirstPage, onLaterPages=myLaterPages)

    response = HttpResponse(mimetype='application/pdf')
    response['Content-Disposition'] = "attachment; filename=%s" % file_name
    response.write(open(filename).read())
    os.remove(filename)
    return response

def build_report(report_name, object_id):

    qs      = []
    fields  = []
    counter = 0

    # Patients Report
    if report_name  == 'all-patient':
        cases   = Case.objects.order_by("provider").all()
    elif report_name == 'provider':
        provider    = Provider.objects.filter(id=object_id)
        cases   = Case.objects.order_by("last_name").filter(provider=provider)
                    
    for case in cases:
        q   = {}
        q['case']   = case
        counter = counter + 1
        q['counter'] = "%d"%counter
        try:
            muacc   = ReportMalnutrition.objects.filter(case=case).latest()
            #q['malnut'] = u"%(diag)s on %(date)s" % {'diag': muacc.diagnosis_msg(), 'date': muacc.entered_at.strftime("%Y-%m-%d")}
            q['malnut_muac'] = "%s (%smm)"%(muacc.get_status_display(), muacc.muac)
            q['malnut_symptoms'] = muacc.symptoms()
        except ObjectDoesNotExist:
            q['malnut_muac'] = ""
            q['malnut_symptoms'] = ""

        try:
            orsc   = ReportDiarrhea.objects.filter(case=case).latest()
            q['diarrhea'] = u"%(diag)s on %(date)s" % {'diag': orsc.diagnosis_msg(), 'date': orsc.entered_at.strftime("%Y-%m-%d")}
        except ObjectDoesNotExist:
            q['diarrhea'] = None
            
        try:
            mrdtc   = ReportMalaria.objects.filter(case=case).latest()
            mrdtcd  = mrdtc.get_dictionary()
            #q['malaria'] = u"result:%(res)s bednet:%(bed)s obs:%(obs)s on %(date)s" % {'res': mrdtcd['result_text'], 'bed': mrdtcd['bednet_text'], 'obs': mrdtcd['observed'], 'date': mrdtc.entered_at.strftime("%Y-%m-%d")}
            q['malaria_result'] = mrdtc.results_for_malaria_result()
            q['malaria_bednet'] = mrdtc.results_for_malaria_bednet()
        except ObjectDoesNotExist:
            q['malaria_result'] = ""
            q['malaria_bednet'] = ""
            
        try:
            dc      = ReportDiagnosis.objects.filter(case=case).latest('entered_at')
            dcd     = dc.get_dictionary()
            q['diagnosis'] = u"diag:%(diag)s labs:%(lab)s on %(date)s" % {'diag': dcd['diagnosis'], 'lab': dcd['labs_text'], 'date': dc.entered_at.strftime("%Y-%m-%d")}
        except ObjectDoesNotExist:
            q['diagnosis'] = None
        
        qs.append(q)
    # caseid +|Y lastname firstname | sex | dob/age | guardian | provider  | date
    fields.append({"name": '#', "column": None, "bit": "{{ object.counter }}" })
    fields.append({"name": 'PID#', "column": None, "bit": "{{ object.case.ref_id }}" })
    fields.append({"name": 'NAME', "column": None, "bit": "{{ object.case.last_name }} {{ object.case.first_name }}" })
    fields.append({"name": 'SEX', "column": None, "bit": "{{ object.case.gender }}" })
    fields.append({"name": 'AGE', "column": None, "bit": "{{ object.case.age }}" })
    fields.append({"name": 'REGISTERED', "column": None, "bit": "{{ object.case.date_registered }}" })
    fields.append({"name": 'MRDT', "column": None, "bit": "{{ object.malaria_result }}" })
    fields.append({"name": 'BEDNET', "column": None, "bit": "{{ object.malaria_bednet }}" })
    fields.append({"name": 'CMAM', "column": None, "bit": "{{ object.malnut_muac }}" })
    fields.append({"name": 'SYMPTOMS', "column": None, "bit": "{{ object.malnut_symptoms}}" })
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

    samp_tot     = ["Total SAM+"]
    sam_tot     = ["Total SAM"]
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
    malnut_tot, malnut_err, blank, samp_tot, sam_tot, mam_tot, blank, samp_new, sam_new, mam_new, blank, user_msg]
    
    # Loop on days
    for d in gdays:
        if d == -1: continue
        ref_date    = datetime(month.year, month.month, d)
        morning     = day_start(ref_date)
        evening     = day_end(ref_date)
        
        # Number of SMS Sent
        sms_num.append(MessageLog.objects.filter(created_at__gte=morning, created_at__lte=evening).count())
        
        # Number of SMS Processed
        sms_process.append(MessageLog.objects.filter(created_at__gte=morning, created_at__lte=evening, was_handled=True).count())
        
        # Number of SMS Refused
        sms_refused.append(MessageLog.objects.filter(created_at__gte=morning, created_at__lte=evening, was_handled=False).count())
        
        # Total # of CHW in System
        chw_tot.append(Provider.objects.filter(role=Provider.CHW_ROLE,user__in=User.objects.filter(date_joined__lte=ref_date)).count())
        
        # New Registered CHW
        chw_reg.append(Provider.objects.filter(role=Provider.CHW_ROLE,user__in=User.objects.filter(date_joined__gte=morning, date_joined__lte=evening)).count())
        
        # Failed CHW Registration
        chw_reg_err.append(EventLog.objects.filter(created_at__gte=morning, created_at__lte=evening, message="provider_registered").count() - EventLog.objects.filter(created_at__gte=morning, created_at__lte=evening, message="confirmed_join").count())
        
        # Active CHWs
        a = Case.objects.filter(created_at__gte=morning, created_at__lte=evening)
        a.query.group_by = ['mctc_case.provider_id']
        chw_on.append(a.__len__())
        
        # New Patient Registered
        patient_reg.append(EventLog.objects.filter(created_at__gte=morning, created_at__lte=evening, message="patient_created").count())
        
        # Failed Patient Registration
        patient_reg_err.append(MessageLog.objects.filter(created_at__gte=morning, created_at__lte=evening, text__startswith="new").count() - patient_reg[-1])
        
        # Total Malaria Reports
        malaria_tot.append(EventLog.objects.filter(created_at__gte=morning, created_at__lte=evening, message="mrdt_taken").count())
        
        # Failed Malaria Reports
        malaria_err.append(MessageLog.objects.filter(created_at__gte=morning, created_at__lte=evening, text__startswith="mrdt").count() - malaria_tot[-1])
        
        # Malaria Test Positive
        malaria_pos.append(ReportMalaria.objects.filter(entered_at__gte=morning, entered_at__lte=evening, result=True).count())
        
        # Malaria Positive with Bednets
        bednet_y_pos.append(ReportMalaria.objects.filter(entered_at__gte=morning, entered_at__lte=evening, result=True, bednet=True).count())
        
        # Malaria Positive without Bednets
        bednet_n_pos.append(ReportMalaria.objects.filter(entered_at__gte=morning, entered_at__lte=evening, result=True, bednet=False).count())
        
        # Malaria Test Negative
        malaria_neg.append(ReportMalaria.objects.filter(entered_at__gte=morning, entered_at__lte=evening, result=False).count())
        
        # Malaria Negative with Bednets
        bednet_y_neg.append(ReportMalaria.objects.filter(entered_at__gte=morning, entered_at__lte=evening, result=False, bednet=True).count())
        
        # Malaria Negative without Bednets
        bednet_n_neg.append(ReportMalaria.objects.filter(entered_at__gte=morning, entered_at__lte=evening, result=False, bednet=False).count())
        
        # Total Malnutrition Reports
        malnut_tot.append(EventLog.objects.filter(created_at__gte=morning, created_at__lte=evening, message="muac_taken").count())
        
        # Failed Malnutrition Reports
        malnut_err.append(MessageLog.objects.filter(created_at__gte=morning, created_at__lte=evening, text__startswith="muac").count() - malnut_tot[-1])
        
        # Total SAM+
        samp_tot.append(ReportMalnutrition.objects.filter(entered_at__lte=evening, status=ReportMalnutrition.SEVERE_COMP_STATUS).count())
        
        # Total SAM
        sam_tot.append(ReportMalnutrition.objects.filter(entered_at__lte=evening, status=ReportMalnutrition.SEVERE_STATUS).count())
        
        # Total MAM
        mam_tot.append(ReportMalnutrition.objects.filter(entered_at__lte=evening, status=ReportMalnutrition.MODERATE_STATUS).count())
        
        # New SAM+
        samp_new.append(ReportMalnutrition.objects.filter(entered_at__gte=morning, entered_at__lte=evening, status=ReportMalnutrition.SEVERE_COMP_STATUS).count())
        
        # New SAM
        sam_new.append(ReportMalnutrition.objects.filter(entered_at__gte=morning, entered_at__lte=evening, status=ReportMalnutrition.SEVERE_STATUS).count())
        
        # New MAM
        mam_new.append(ReportMalnutrition.objects.filter(entered_at__gte=morning, entered_at__lte=evening, status=ReportMalnutrition.MODERATE_STATUS).count())
        
        # User Messaging
        user_msg.append(MessageLog.objects.filter(created_at__gte=morning, created_at__lte=evening, text__startswith="@").count())

    # Write rows on CSV
    for row in rows:
        csvio.writerow([cell for cell in row])
    
    response = HttpResponse(mimetype='text/csv')
    response['Content-Disposition'] = "attachment; filename=%s" % file_name
    response.write(output.getvalue())
    return response

