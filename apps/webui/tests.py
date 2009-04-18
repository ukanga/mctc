from django.test import TestCase                
from django.test.client import Client

class dashboard(TestCase):
    fixtures = ["users.json",]

    def testPasses(self):
        clt = Client()
        res = clt.get("/")
        assert res.status_code == 302
        # admin is a superuser
        clt.login(username='admin', password='admin')
        res = clt.get("/")
        assert res.status_code == 200
        clt.logout()
        clt.login(username='staff', password='staff')
        res = clt.get("/")
        assert res.status_code == 200
        clt.logout()

    def testFails(self):
        clt = Client()
        clt.login(username='nonstaff', password='nonstaff')
        res = clt.get("/")
        assert res.status_code == 302
        clt.logout()        
        clt.login(username='nonactive', password='nonactive')
        res = clt.get("/")
        assert res.status_code == 302