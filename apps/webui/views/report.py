from django.http import HttpResponseRedirect
from django.contrib import auth

from apps.webui.forms.login import LoginForm
from apps.webui.shortcuts import as_html, login_required
from apps.mctc.models.logs import log
from apps.mctc.models.general import Case, Zone, Provider, Facility
from apps.mctc.models.reports import ReportCHWStatus

from django.utils.translation import ugettext_lazy as _

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
from django.template import Template, Context
from django.template.loader import get_template
from django.core.paginator import Paginator, InvalidPage
from django.http import HttpResponse, HttpResponseRedirect

from tempfile import mkstemp

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
    
    def setTitle(self, title):
        if title:
           self.title = title
           
    def setPageIinfo(self, pageinfo):
        if title:
           self.pageinfo = pageinfo
           
    def setFilename(self, filename):
        if title:
           self.filename = filename
    
    def setPageBreak(self):
        self.data.append(PageBreak())
         
    def setData(self, queryset, fields, title):
        
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
        table.setStyle(TableStyle([
            ('ALIGNMENT', (0,0), (-1,-1), 'LEFT'),
            ('LINEBELOW', (0,0), (-1,-0), 2, colors.black),            
            ('LINEBELOW', (0,1), (-1,-1), 0.8, colors.lightgrey),
            ('FONT', (0,0), (-1, -1), "Helvetica", 8),
            ('ROWBACKGROUNDS', (0,0), (-1, -1), [colors.whitesmoke, colors.white]),
        ]))
        table.hAlign = "LEFT"
        self.data.append(table)
        
    def render(self):
        elements = []
        
        self.styles['Title'].alignment = TA_LEFT
        self.styles['Title'].fontName = self.styles['Heading2'].fontName = "Helvetica"
        self.styles["Normal"].fontName = "Helvetica"
        self.styles["Normal"].fontSize = 10
        self.styles["Normal"].fontWeight = "BOLD"
            
        filename = self.filename + ".pdf"
        doc = SimpleDocTemplate(filename)
        
        elements.append(Paragraph(self.title, self.styles['Title']))
        
        clinics = Provider.objects.values('clinic').distinct()
        
        for data in self.data:
            elements.append(data)
        
        #elements.append(Paragraph("Created: %s" % datetime.now().strftime("%d/%m/%Y"), styles["Normal"]))        
        #doc.pagesize = landscape(A4)
        doc.build(elements, onFirstPage=self.myFirstPage, onLaterPages=self.myLaterPages)
        
        response = HttpResponse(mimetype='application/pdf')
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
def last_30_days(request, object_id=None, per_page=0):
    pdfrpt = GenPDFRrepot()
    pdfrpt.setTitle("RapidResponse MVP Kenya: CHW Last 30 Days Perfomance Report")
    if object_id is None:
        clinics = Provider.objects.values('clinic').distinct()
        for clinic in clinics:
            queryset, fields = ReportCHWStatus.get_providers_by_clinic(clinic["clinic"])
            c = Facility.objects.filter(id=clinic["clinic"])[0]
            pdfrpt.setData(queryset, fields, c.name)
            if per_page == 1:
                pdfrpt.setPageBreak()
    else:
        queryset, fields = ReportCHWStatus.get_providers_by_clinic(object_id)
        c = Facility.objects.filter(id=object_id)[0]
        pdfrpt.setData(queryset, fields, c.name)
    
    return pdfrpt.render()
    return chwstatus_pdf(request)
    clinics = Provider.objects.values('clinic').distinct()
    
    context = {
        "app": app,
        "clinics": clinics,
    }

    return as_html(request, "reports/last_30_days.html", context)

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
        queryset, fields = ReportCHWStatus.get_providers_by_clinic(clinic["clinic"])
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
