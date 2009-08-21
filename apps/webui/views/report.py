from django.http import HttpResponseRedirect
from django.contrib import auth

from apps.webui.forms.login import LoginForm
from apps.webui.shortcuts import as_html, login_required
from apps.mctc.models.logs import log
from apps.mctc.models.general import Case, Zone, Provider, Facility
from apps.mctc.models.reports import ReportCHWStatus, ReportAllPatients
from apps.webui.views.general import next_month
from django.utils.translation import ugettext_lazy as _

try:
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, CondPageBreak
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
from django.template import Template, Context
from django.template.loader import get_template
from django.core.paginator import Paginator, InvalidPage
from django.http import HttpResponse, HttpResponseRedirect

from tempfile import mkstemp
from datetime import datetime, timedelta, date
import os
import csv
import StringIO

app = {}
app['name'] = "RapidResponse:Health"

class GenPDFRrepot():
    title = "Report"
    pageinfo = ""
    filename = "report"
    styles = getSampleStyleSheet()
    data = []
    landscape = False
    hasfooter = False
    
    def setLandscape(self, state):
        self.landscape = state
        
    def enableFooter(self, state):
        self.hasfooter = state
        
    def setTitle(self, title):
        if title:
           self.title = title
           
    def setPageIinfo(self, pageinfo):
        if pageinfo:
           self.pageinfo = pageinfo
           
    def setFilename(self, filename):
        if filename:
           self.filename = filename
    
    def setPageBreak(self):
        #self.data.append(Paragraph("Page Break", self.styles['Normal']))
        self.data.append(PageBreak())
         
    def setTableData(self, queryset, fields, title):
        
        self.data.append(Paragraph("%s" % title, self.styles['Heading3']))
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
        ts = [
            ('ALIGNMENT', (0,0), (-1,-1), 'LEFT'),
            ('LINEBELOW', (0,0), (-1,-0), 2, colors.black),            
            ('LINEBELOW', (0,1), (-1,-1), 0.8, colors.lightgrey),
            ('FONT', (0,0), (-1, -1), "Helvetica", 8),
            ('ROWBACKGROUNDS', (0,0), (-1, -1), [colors.whitesmoke, colors.white]),            
        ]
        if self.hasfooter is True:
            ts.append(('LINEABOVE', (0,-1), (-1,-1), 1, colors.red))
            ts.append(('LINEBELOW', (0,-1), (-1,-1), 2, colors.red))            
            ts.append(('LINEBELOW', (0,-1), (-1,-1), 0.8, colors.lightgrey))
            ts.append(('FONT', (0,-1), (-1, -1), "Helvetica", 8))
            
        table.setStyle(TableStyle(ts))

        table.hAlign = "LEFT"
        self.data.append(table)
        
    def render(self):
        elements = []
        
        self.styles['Title'].alignment = TA_LEFT
        self.styles['Title'].fontName = self.styles['Heading2'].fontName = "Helvetica"
        self.styles["Normal"].fontName = "Helvetica"
        self.styles["Normal"].fontSize = 10
        self.styles["Normal"].fontWeight = "BOLD"
            
        filename = self.filename + datetime.now().strftime("%Y%m%d%H%M%S") + ".pdf"
        doc = SimpleDocTemplate(filename)
        
        elements.append(Paragraph(self.title, self.styles['Title']))
        
        clinics = Provider.objects.values('clinic').distinct()
        
        for data in self.data:
            elements.append(data)
        
        #elements.append(Paragraph("Created: %s" % datetime.now().strftime("%d/%m/%Y"), styles["Normal"]))        
        if self.landscape is True:
            doc.pagesize = landscape(A4)
        
        doc.build(elements, onFirstPage=self.myFirstPage, onLaterPages=self.myLaterPages)
        
        response = HttpResponse(mimetype='application/pdf')
        response['Cache-Control'] = ""
        response['Content-Disposition'] = "attachment; filename=%s" % filename
        response.write(open(filename).read())
        os.remove(filename)
        return response
         
    def myFirstPage(self, canvas, doc):
        pageinfo = self.pageinfo
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
    
    def myLaterPages(self, canvas, doc):
        pageinfo = self.pageinfo
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

@login_required
def reports(request):
    clinics = Provider.objects.values('clinic__id','clinic__name').distinct()
    
    zones = Case.objects.order_by("zone").values('zone', 'zone__name').distinct()
    p = Case.objects.order_by("zone").values('provider', 'provider__user__first_name', 'provider__user__last_name', 'zone').distinct()
    providers = []
    for provider in p:
        tmp = {}
        tmp['id'] = provider['provider']
        tmp['name'] = provider['provider__user__last_name'] + " " + provider['provider__user__first_name']
        tmp['zone'] = provider['zone']
        providers.append(tmp)  
        
    now = datetime.today()
    first   = Case.objects.order_by('created_at')[:1][0]
    date    = first.created_at

    months=[]
    while ((now - date).days > 0):
        months.append({'id': date.strftime("%m%Y"), 'label': date.strftime("%B %Y"), 'date': date})
        date = next_month(date)
    
    context = {
        "app": app,
        "clinics": clinics,
        "providers": providers,
        "zones": zones,
        "months": months
    }
    return as_html(request, "reports/reports.html", context)

@login_required
def last_30_days(request, object_id=None, per_page="0", rformat="pdf"):
    pdfrpt = GenPDFRrepot()
    
    pdfrpt.enableFooter(True)
    thirty_days = timedelta(days=30)
    sixty_days = timedelta(days=60)
    today = date.today()
    
    duration_start = today - thirty_days
    muac_duration_start = today - sixty_days
    duration_end = today
    
    pdfrpt.setTitle("RapidResponse MVP Kenya: CHW 30 Day Performance Report, from %s to %s"%(duration_start, duration_end))
    if object_id is None:
        clinics = Provider.objects.values('clinic').distinct()
        for clinic in clinics:
            queryset, fields = ReportCHWStatus.get_providers_by_clinic(duration_start, duration_end, muac_duration_start, clinic["clinic"])
            c = Facility.objects.filter(id=clinic["clinic"])[0]
            pdfrpt.setTableData(queryset, fields, c.name)
            if (int(per_page) == 1) is True:
                pdfrpt.setPageBreak()
                pdfrpt.setFilename("report_per_page")
    else:
        if request.POST['clinic']:
            object_id = request.POST['clinic']
        queryset, fields = ReportCHWStatus.get_providers_by_clinic(duration_start, duration_end, muac_duration_start, object_id)
        c = Facility.objects.filter(id=object_id)[0]
        
        if rformat == "csv" or (request.POST and request.POST["format"].lower() == "csv"):
            file_name = c.name + ".csv"
            file_name = file_name.replace(" ","_").replace("'","")
            return handle_csv(request, queryset, fields, file_name)
        
        pdfrpt.setTableData(queryset, fields, c.name)
    
    return pdfrpt.render()

@login_required
def patients_by_chw(request, object_id=None, per_page="0", rformat="pdf"):
    pdfrpt = GenPDFRrepot()
    pdfrpt.setLandscape(True)
    pdfrpt.setTitle("RapidResponse MVP Kenya: Patients by CHW")
    if object_id is None:        
        if request.POST and request.POST['zone']:
            providers = Case.objects.filter(zone=request.POST['zone']).values('provider', 'zone__name').distinct()
            per_page = "1"
        else:
            providers = Case.objects.order_by("zone").values('provider', 'zone__name').distinct()
        for provider in providers:
            queryset, fields = ReportAllPatients.by_provider(provider['provider'])
            c = Provider.objects.get(id=provider["provider"])
            pdfrpt.setTableData(queryset, fields, provider['zone__name']+": "+c.get_name_display())
            if (int(per_page) == 1) is True:
                pdfrpt.setPageBreak()
                pdfrpt.setFilename("report_per_page")
    else:        
        if request.POST and request.POST['provider']:
            object_id = request.POST['provider']
        
        queryset, fields = ReportAllPatients.by_provider(object_id)
        
        c = Provider.objects.get(id=object_id)
        
        if rformat == "csv" or (request.POST and request.POST["format"].lower() == "csv"):
            file_name = c.get_name_display() + ".csv"
            file_name = file_name.replace(" ","_").replace("'","")
            return handle_csv(request, queryset, fields, file_name)
        
        pdfrpt.setTableData(queryset, fields, c.get_name_display())
    
    return pdfrpt.render()

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