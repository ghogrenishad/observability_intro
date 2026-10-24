"""Ordinary Python logs first: no trace/span fields in the initial lesson."""
import logging
from config import ROOT

LOG_PATH = ROOT / "kiosk.log"


def request_logger(request_id="-"):
    logger = logging.getLogger("session1.kiosk")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s request=%(request_id)s %(message)s"))
        logger.addHandler(handler)
    return logging.LoggerAdapter(logger, {"request_id": request_id})
