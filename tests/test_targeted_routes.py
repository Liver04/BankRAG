import unittest
from evaluation.targeted_routes import select_cases
class TargetedRoutesTests(unittest.TestCase):
    def test_order_and_multiturn_preserved(self):
        c=[{'case_id':'A','turns':[1,2]},{'case_id':'B','turns':[3]}]
        self.assertEqual(select_cases(c,['B','A']),c)
    def test_unknown_rejected(self):
        with self.assertRaises(ValueError):select_cases([{'case_id':'A'}],['B'])
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):select_cases([{'case_id':'A'}],['A','A'])
