import unittest
from base.safety import eligible, finalize, validate_source, redact
from base.config import config

class PolicyTests(unittest.TestCase):
    def test_source_injection(self):
        for value in ['faq" or source != "', '', 'FAQ', 'product or true']:
            with self.assertRaises(ValueError): validate_source(value)
        self.assertEqual(validate_source('faq'), 'faq')
    def test_expiry_boundary(self):
        m = dict(review_status='demo_approved', effective_date=20261001, expiry_date=20261012)
        self.assertTrue(eligible(m, 20261012))
        self.assertFalse(eligible(m, 20261013))
        self.assertFalse(eligible(m, 20260930))
    def test_pending(self):
        self.assertFalse(eligible(dict(effective_date=0, expiry_date=0)))
    def test_disclaimer_once(self):
        self.assertEqual(finalize(finalize('业务答案')).count(config.DISCLAIMER), 1)
    def test_redaction(self):
        self.assertNotIn('13812345678', redact('手机号13812345678'))
        self.assertNotIn('110101199001011234', redact('证件110101199001011234'))

if __name__ == '__main__': unittest.main()
