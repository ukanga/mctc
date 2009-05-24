#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4

import datetime
from models import Expense
from models import Items
import rapidsms
import re

class App(rapidsms.app.App):
    prefix = re.compile(r'^exp\s+', re.I)
    def handle(self, message):
        #sc, gotit, exp, tkn, kw, cost
        self.debug("got message %s", message.text)
        if self.prefix.search(message.text):
            response = self.prefix.sub("", message.text)
            self.debug("responding with %s", response)                      
            try:
                tkn = response.split()
                number_of_items = len(tkn)
                if number_of_items >= 2 and number_of_items%2 == 0:
                    counter, i = 0, 0
                    reply = ""
                    tstamp = datetime.datetime.now()
                    total_cost = 0
                    while i < (number_of_items/2):
                        kw = tkn[counter]
                        # self.debug(tkn[counter])
                        cost = float(tkn[counter+1])
                        sc = self.get_item_by_shortcode(kw)
                        exp = Expense(expense_date=tstamp, item=sc, cost=cost, who=message.peer, given_code=kw)
                        exp.save()
                        the_item = sc.name
                        if sc.short_code == "NONE":
                            the_item = kw
                        reply = reply + " %d ksh on %s, "%(cost, the_item)
                        counter = counter + 2
                        i = i + 1
                        total_cost = total_cost + cost
                    if len(reply):
                        message.respond("You spent" + reply[:len(reply)-2] + ". Total %d ksh."% total_cost)
                        self.debug("%d", number_of_items)
                    else:
                        self.debug("No message to reply")
                        message.respond("Message Successfully delivered")
                    #message.respond("You bought %s valued at %s " % (tkn[0], tkn[1]))
                else:
                    message.respond("Unable to handle message")
            except Items.DoesNotExist, e:         
                self.debug(e)
                message.respond("Error: Not Found")
            except Exception, e:
                message.respond("Error: invalid message format")
                self.debug(e)
	    return True

    def get_item_by_shortcode(self,kw):
        try:
            sc = Items.objects.get(short_code=kw.upper())
            return sc
        except Items.DoesNotExist, e:
            self.debug(e)
            return Items.objects.get(short_code="NONE")
        except Exception, e:
            self.debug(e)
        return False

