from django.db import models
from django.utils.translation import ugettext

def _(txt): return txt

from django.contrib.auth.models import User, Group

import rapidsms

from rapidsms.parsers.keyworder import Keyworder
from rapidsms.message import Message
from rapidsms.connection import Connection

from models.general import Provider, User, MessageLog, Facility
from models.general import Case, CaseNote, Observation
from models.reports import ReportMalnutrition, ReportMalaria

import re, time, datetime

def authenticated (func):
    def wrapper (self, message, *args):
        if message.sender:
            return func(self, message, *args)
        else:
            message.respond(_("%s is not a registered number.")
                            % message.peer)
            return True
    return wrapper

class HandlerFailed (Exception):
    pass

class App (rapidsms.app.App):
    MAX_MSG_LEN = 140
    keyword = Keyworder()

    def start (self):
        """Configure your app in the start phase."""
        pass

    def parse (self, message):
        provider = Provider.by_mobile(message.peer)
        if provider:
            message.sender = provider.user
        else:
            message.sender = None
        message.was_handled = False

    def cleanup (self, message):
        log = MessageLog(mobile=message.peer,
                         sent_by=message.sender,
                         text=message.text,
                         was_handled=message.was_handled)
        log.save()

    def handle (self, message):
        try:
            func, captures = self.keyword.match(self, message.text)
        except TypeError:
            # didn't find a matching function
            return False
        try:
            handled = func(self, message, *captures)
        except HandlerFailed, e:
            message.respond(e.message)
            handled = True
        except Exception, e:
            # TODO: log this exception
            # FIXME: also, put the contact number in the config
            message.respond(_("An error occurred. Please call 999-9999."))
            raise
        message.was_handled = bool(handled)
        return handled

    @keyword("join (\S+) (\S+) (\S+)(?: ([a-z]\w+))?")
    def join (self, message, code, last_name, first_name, username=None):
        try:
            clinic = Facility.objects.get(codename__iexact=code)
        except Facility.DoesNotExist:
            raise HandlerFailed(_("The given password is not recognized."))

        if username is None:
            # FIXME: this is going to run into charset issues
            username = (first_name[0] + last_name).lower()
        else:
            # lower case usernames ... also see FIXME above?
            username = username.lower()
        if User.objects.filter(username__iexact=username).count():
            raise HandlerFailed(_(
                "Username '%s' is already in use. " +
                "Reply with: JOIN <last> <first> <username>") % username)
        
        info = {
            "username"   : username,
            "first_name" : first_name.title(),
            "last_name"  : last_name.title()
        }
        user = User(**info)
        user.save()

        mobile = message.peer
        in_use = Provider.by_mobile(mobile)
        provider = Provider(mobile=mobile, user=user,
                            clinic=clinic, active=not bool(in_use))
        provider.save()
    
        if in_use:
            info.update({
                "last_name"  : in_use.user.last_name.upper(),
                "first_name" : in_use.user.first_name,
                "other"      : in_use.user.username,
                "mobile"     : mobile,
                "clinic"     : provider.clinic.name, 
            })
            message.respond(_(
                "Phone %(mobile)s is already registered to %(last_name)s, " +
                "%(first_name)s. Reply with 'CONFIRM %(username)s'.") % info)
        else:
            info.update({
                "id"        : provider.id,
                "mobile"    : mobile,
                "clinic"    : provider.clinic.name, 
                "last_name" : last_name.upper()
            })
            self.respond_to_join(message, info)
        return True

    def respond_to_join(self, message, info):
        message.respond(
            _("%(mobile)s registered to *%(id)s %(username)s " +
              "(%(last_name)s, %(first_name)s) at %(clinic)s.") % info)

    @keyword(r'confirm (\w+)')
    def confirm_join (self, message, username):
        mobile   = message.peer
        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            self.respond_not_registered(username)
        for provider in Provider.objects.filter(mobile=mobile):
            if provider.user.id == user.id:
                provider.active = True
            else:
                provider.active = False
            provider.save()
        info = {
            "first_name"    : user.first_name,
            "last_name"     : user.last_name.upper(),
            "id"            : provider.id,
            "mobile"        : mobile,
            "clinic"        : provider.clinic.name,
            "username"      : username
        } 
        self.respond_to_join(message, info) 
        return True

    def respond_not_registered (self, message, target):
        raise HandlerFailed(_("User *%s is not registered.") % target)

    @keyword(r'\*(\w+) (.+)')
    @authenticated
    def direct_message (self, message, target, text):
        try:
            if re.match(r'^\d+$', target):
                provider = Provider.objects.get(id=target)
                user = provider.user
            else:
                user = User.objects.get(username__iexact=target)
        except models.ObjectDoesNotExist:
            # FIXME: try looking up a group
            self.respond_not_registered(message, target)
        try:
            mobile = user.provider.mobile
        except:
            self.respond_not_registered(message, target)
        sender = message.sender.username
        return message.forward(mobile, "*%s> %s" % (sender, text))

    @keyword(r'new (\S+) (\S+) ([MF]) ([\d\-]+)( \D+)?( \d+)?')
    @authenticated
    def new_case (self, message, last, first, gender, dob,
                  guardian="", contact=""):
        provider = message.sender.provider
        zone     = None
        if provider.clinic:
            zone = provider.clinic.zone

        dob = re.sub(r'\D', '', dob)
        try:
            dob = time.strptime(dob, "%y%m%d")
        except ValueError:
            try:
                dob = time.strptime(dob, "%Y%m%d")
            except ValueError:
                raise HandlerFailed(_("Couldn't understand date: %s") % dob)
        dob = datetime.date(*dob[:3])
        if guardian:
            guardian = guardian.title()
        info = {
            "first_name" : first.title(),
            "last_name"  : last.title(),
            "gender"     : gender.upper()[0],
            "dob"        : dob,
            "guardian"   : guardian,
            "mobile"     : contact,
            "provider"   : provider,
            "zone"       : zone
        }

        ## TODO: check to see if the case already exists

        case = Case(**info)
        case.save()

        info.update({
            "id": case.ref_id,
            "last_name": last.upper(),
            "age": case.age()
        })
        if zone:
            info["zone"] = zone.name
        message.respond(_(
            "New +%(id)s: %(last_name)s, %(first_name)s %(gender)s/%(age)s " +
            "(%(guardian)s) %(zone)s") % info)
        return True

    def find_case (self, ref_id):
        try:
            return Case.objects.get(ref_id=int(ref_id))
        except Case.DoesNotExist:
            raise HandlerFailed(_("Case +%s not found.") % ref_id)
 
    @keyword(r'cancel \+?(\d+)')
    @authenticated
    def cancel_case (self, message, ref_id):
        case = self.find_case(ref_id)
        if case.reportmalnutrition_set.count():
            raise HandlerFailed(_(
                "Cannot cancel +%s: case has diagnosis reports.") % ref_id)
        case.delete()
        message.respond(_("Case +%s cancelled.") % ref_id)
        return True

    @keyword(r'list(?: \+)?')
    @authenticated
    def list_cases (self, message):
        # FIXME: should only return active cases here
        # needs order by to cope with what unit tests expect
        cases = Case.objects.filter(provider=message.sender.provider).order_by("ref_id")
        text  = ""
        for case in cases:
            item = "+%s %s %s. %s/%s" % (case.ref_id, case.last_name.upper(),
                case.first_name[0].upper(), case.gender, case.age())
            if len(text) + len(item) + 2 >= self.MAX_MSG_LEN:
                message.respond(text)
                text = ""
            if text: text += ", "
            text += item
        if text:
            message.respond(text)
        return True

    @keyword(r'list\s@')
    @authenticated
    def list_providers (self, message):
        providers = Provider.objects.all()
        text  = ""
        for provider in providers:
            item = "*%s %s" % (provider.id, provider.user.username)
            if len(text) + len(item) + 2 >= self.MAX_MSG_LEN:
                message.respond(text)
                text = ""
            if text: text += ", "
            text += item
        if text:
            message.respond(text)
        return True

    @keyword(r's(?:how)? \+?(\d+)')
    @authenticated
    def show_case (self, message, ref_id):
        case = self.find_case(ref_id)
        info = {
            "id"            : case.ref_id,
            "last_name"     : case.last_name.upper(),
            "first_name"    : case.first_name,
            "gender"        : case.gender,
            "age"           : case.age(),
            "status"        : case.get_status_display(),
        }
        if case.guardian: info["guardian"] = "(%s) " % case.guardian
        if case.zone: info["zone"] = case.zone.name
        message.respond(_(
            "+%(id)s %(status)s %(last_name)s, %(first_name)s "
            "%(gender)s/%(age)s %(guardian)s%(zone)s") % info)
        return True

    @keyword(r'\+(\d+) ([\d\.]+)( [\d\.]+)?( [\d\.]+)?( (?:[a-z]\s*)+)')
    @authenticated
    def report_case (self, message, ref_id, muac,
                     weight, height, complications):
        case = self.find_case(ref_id)
        try:
            muac = float(muac)
            if muac < 30: # muac is in cm?
                muac *= 10
            muac = int(muac)
        except ValueError:
            raise HandlerFailed(
                _("Can't understand MUAC (mm): %s") % muac)

        if weight is not None:
            try:
                weight = float(weight)
                if weight > 100: # weight is in g?
                    weight /= 1000.0
            except ValueError:
                raise HandlerFailed("Can't understand weight (kg): %s" % weight)

        if height is not None:
            try:
                height = float(height)
                if height < 3: # weight height in m?
                    height *= 100
                height = int(height)
            except ValueError:
                raise HandlerFailed("Can't understand height (cm): %s" % height)

        observed, choices = self.get_observations(complications)
        self.delete_similar(case.reportmalnutrition_set)

        provider = message.sender.provider
        report = ReportMalnutrition(case=case, provider=provider, muac=muac,
                        weight=weight, height=height)
        report.save()
        for obs in observed:
            report.observed.add(obs)
        report.save()

        case.status = report.diagnosis()
        case.save()

        choice_term = dict(choices)
        info = {
            'ref_id'    : case.ref_id,
            'last'      : case.last_name.upper(),
            'first'     : case.first_name[0],
            'muac'      : "%d mm" % muac,
            'observed'  : ", ".join([k.name for k in observed]),
            'diagnosis' : case.get_status_display(),
        }
        msg = _("+%(ref_id)s: %(diagnosis)s, MUAC %(muac)s") % info

        if weight: msg += ", %.1f kg" % weight
        if height: msg += ", %.1d cm" % height
        if observed: msg += ", " + info["observed"]

        message.respond("Report " + msg)

        if case.status in (case.MODERATE_STATUS,
                           case.SEVERE_STATUS,
                           case.SEVERE_COMP_STATUS):
            alert = _("*%(username)s reports %(msg)s") % {"username":provider.user.username, "msg":msg}
            recipients = [provider]
            for query in (Provider.objects.filter(alerts=True),
                          Provider.objects.filter(clinic=provider.clinic)):
                for recipient in query:
                    if recipient in recipients: continue
                    recipients.append(recipient)
                    message.forward(recipient.mobile, alert)

        return True

    @keyword(r'n(?:ote)? \+(\d+) (.+)')
    @authenticated
    def note_case (self, message, ref_id, note):
        case = self.find_case(ref_id)
        CaseNote(case=case, created_by=message.sender, text=note).save()
        message.respond(_("Note added to case +%s.") % ref_id)
        return True

    @keyword(r'mrdt \+(\d+) ([yn]) ([yn])?(.*)')
    @authenticated
    def report_malaria(self, message, ref_id, result, bednet, observed):
        case = self.find_case(ref_id)
        observed, choices = self.get_observations(observed)
        self.delete_similar(case.reportmalaria_set)        
        provider = message.sender.provider
        
        result = result.lower() == "y"
        bednet = bednet.lower() == "y"

        report = ReportMalaria(case=case, provider=provider, result=result, bednet=bednet)
        report.save()
        for obs in observed:
            report.observed.add(obs)
        report.save()
        
        info = {
            'ref_id': case.ref_id,
            'last_name': case.last_name.upper(),
            'first_name': case.first_name,
            'gender': case.gender.upper()[0],
            'months': case.age(),
            'guardian': case.guardian,
            'village': case.village,
            'result': report.result,
            'result_text': report.result and "Y" or "N",
            'bednet': report.bednet,
            'bednet_text': report.bednet and "Y" or "N",
            'observed': ", ".join([k.name for k in observed]),
        }
        
        msg = _("+%(ref_id)s: %(result_text)s %(bednet_text)s") % info

        if observed: msg += ", " + info["observed"]        
        message.respond("Report " + msg)
                
        if not result:
            if observed: info["observed"] = ", (%s)" % info["observed"]            
            alert = _("MRDT> Child +%(ref_id)s, %(last_name)s, %(first_name)s, %(gender)s/%(months)s (%(guardian)s), %(village)s. RDT=%(result_text)s, Bednet=%(bednet_text)s%(observed)s. Please refer patient IMMEDIATELY for clinical evaluation" % info)
        else:
            years, months = case.years_months()
            tabs, yage = None, None
            if years < 1:
                if months < 2:
                    tabs, yage = None, None
                else:
                    tabs, yage = 1, "less than 3"
            elif years < 3:
                tabs, yage = 1, "less than 3"                    
            elif years < 9:
                tabs, yage = 2, years                        
            elif years < 15:
                tabs, yage = 3, years                        
            else:
                tabs, yage = 4, years                        
            
            dangers = report.observed.filter(uid__in=("vomiting", "fever", "appetite", "breathing", "confusion"))
            if dangers:
                info["danger"] = " and danger signs " + ",".join([ u.name for u in dangers ])
                if not tabs:
                    info["instructions"] = "Child is too young for treatment. Please refer immediately to clinic"
                else:
                    plural = (tabs > 1) and "s" or ""
                    info["instructions"] = "Refer to clinic immediately after first dose (%s tab%s) is given" % (tabs, plural)
            else:
                info["danger"] = ""
                if not tabs:
                    info["instructions"] = "Child is too young for treatment. Please refer immediately to clinic"
                else:
                    plural = (tabs > 1) and "s" or ""
                    info["instructions"] = "Child is %s. Please provide %s tab%s of Coartem (ACT) twice a day for 3 days" % (yage, tabs, plural)

            alert = _("MRDT> Child +%(ref_id)s, %(last_name)s, %(first_name)s, %(gender)s/%(months)s has MALARIA%(danger)s. %(instructions)s" % info)
    
        recipients = [message.sender.provider,]
        for recipient in Provider.objects.filter(clinic=provider.clinic):
            if recipient in recipients: continue
            recipients.append(recipient)
            message.forward(recipient.mobile, alert)

    
    def delete_similar(self, set):
        try:
            last_report = set.latest("entered_at")
            if (datetime.datetime.now() - last_report.entered_at).days == 0:
                # last report was today. so delete it before filing another.
                last_report.delete()
        except models.ObjectDoesNotExist:
            pass

    def get_observations(self, text):    
        choices  = dict( [ (o.letter, o) for o in Observation.objects.all() ] )
        observed = []
        if text:
            text = re.sub(r'\W+', ' ', text).lower()
            for observation in text.split(' '):
                obj = choices.get(observation, None)
                if not obj:
                    if observation != 'n':
                        raise HandlerFailed("Unknown observation code: %s" % observation)
                else:
                    observed.append(obj)
        return observed, choices
            
            
            
            
            
            
            
def message_users(mobile, message=None, groups=None, users=None):
    """ Matt wants to send a message from the web front end to the users """
    recipients = []
    # get all the users
    user_objects = [ User.objects.get(id=user) for user in users ]
    for user in user_objects:
        try:
            if user.provider not in recipients:
                recipients.append(user.provider)
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
    
    # not sure what's going on tbh, I think this needs reviewing
    from rapidsms.backends import spomc
    
    connection = Connection(spomc.Backend, mobile)
    smsmessage = Message(connection, message)
    for recipient in recipients:
        smsmessage.forward(recipient.mobile)