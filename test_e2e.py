"""Deterministic HTTP/WS regression entry point; no network judge, no training."""
import unittest
if __name__=='__main__':
    suite=unittest.defaultTestLoader.discover('tests')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
