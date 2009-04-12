from rapidsms.tests.scripted import TestScript
from app import App
from models import Case, User
from datetime import datetime, date

def age_in_months (*ymd):
    return int((datetime.now().date() - date(*ymd)).days / 30.4375)    

def age_in_years (*ymd):
    return int((datetime.now().date() - date(*ymd)).days / 365.25)

class TestApp (TestScript):
    apps = (App,)

    test_00_Join = """
        # test registration
        1234567 > join smith john
        1234567 < 1234567 registered to *1 jsmith (SMITH, John).

        # test re-registration
        1234567 > join smith john
        1234567 < Username 'jsmith' is already in use. Reply with: JOIN <last> <first> <username>
    
        # test takeover/confirm
        1234567 > join smith john smithj
        1234567 < Phone 1234567 is already registered to SMITH, John. Reply with 'CONFIRM smithj'.   
        1234567 > confirm smithj
        1234567 < 1234567 registered to *2 smithj (SMITH, John).

        # test authentication
        7654321 > *2 can you read this?
        7654321 < 7654321 is not a registered number.

        # test direct messaging
        7654321 > join doe jane
        7654321 < 7654321 registered to *3 jdoe (DOE, Jane).
        7654321 > *2 can you read this? 
        1234567 < *jdoe> can you read this?
        1234567 > *jdoe yes, I can read that
        7654321 < *smithj> yes, I can read that

        # test direct messaging to a non-existent user
        7654321 > *14 are you there?
        7654321 < User *14 is not registered.
        7654321 > *kdoe are you there?
        7654321 < User *kdoe is not registered.

        # FIXME: what happens if you message an inactive provider???
    """
    
    test_00_NewCase = """
        # test basic case creation
        7654321 > new madison dolly f 080411
        7654321 < New #18: MADISON, Dolly F/%dm (None) None

        # case with guardian and age in years
        7654321 > new madison molly f 20050411 sally
        7654321 < New #26: MADISON, Molly F/%d (Sally) None

        # case with guardian and phone number
        7654321 > new madison holly f 090211 sally 230123
        7654321 < New #34: MADISON, Holly F/%dm (Sally) None

        # case with phone number but no guardian
        7654321 > new madison wally m 070615 230123
        7654321 < New #42: MADISON, Wally M/%dm (None) None

        # FIXME: unparsable cases???
    """ % (
        age_in_months(2008,4,11),
        age_in_years(2005,4,11),
        age_in_months(2009,2,11),
        age_in_months(2007,6,15),)

    def test_01_CreatedCases (self):
        user = User.objects.get(username="jdoe")
        case = Case.objects.get(ref_id=42)
        self.assertEqual(case.mobile, "230123", "case 42 mobile")
        self.assertEqual(case.provider, user.provider, "case 42 provider")

        case = Case.objects.get(ref_id=34)
        self.assertEqual(case.mobile, "230123", "case 34 mobile")
        self.assertEqual(case.guardian, "Sally", "case 34 guardian")
        self.assertEqual(case.provider, user.provider, "case 34 provider")

    test_01_ListCases = """
        0000000 > list
        0000000 < 0000000 is not a registered number.

        7654321 > list
        7654321 < #18 MADISON D. F/11m, #26 MADISON M. F/4, #34 MADISON H. F/1m, #42 MADISON W. M/21m
    """

    test_01_ListProviders = """
        0000000 > list *
        0000000 < 0000000 is not a registered number.

        7654321 > list *
        7654321 < *1 jsmith, *2 smithj, *3 jdoe
    """
    
    test_02_CancelCases = """
        0000000 > cancel #34
        0000000 < 0000000 is not a registered number.
        
        7654321 > cancel #34
        7654321 < Case #34 cancelled.
        7654321 > cancel 42
        7654321 < Case #42 cancelled. 
        7654321 > cancel 42
        7654321 < Case #42 not found. 
    """ 
