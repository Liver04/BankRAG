"""Application logs contain codes, not customer queries or raw exception payloads."""
import logging
import os
from logging.handlers import RotatingFileHandler
from base.config import config
class PrivacyFilter(logging.Filter):
    def filter(self,record):
        from base.safety import redact
        record.msg=redact(record.getMessage());record.args=()
        record.exc_info=None;record.exc_text=None
        return True
def setup_logging(log_file=config.LOG_FILE):
    os.makedirs(os.path.dirname(log_file),exist_ok=True)
    log=logging.getLogger('BankRAG');log.setLevel(logging.INFO)
    if not log.handlers:
        formatter=logging.Formatter('%(asctime)s %(levelname)s %(module)s %(message)s')
        for h in [RotatingFileHandler(log_file,maxBytes=5_000_000,backupCount=3,encoding='utf-8'),logging.StreamHandler()]:
            h.setFormatter(formatter);h.addFilter(PrivacyFilter());log.addHandler(h)
    return log
logger=setup_logging()
