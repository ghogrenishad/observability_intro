"""INSTRUCTOR ONLY: the three intentional faults live here. No fake model answers."""
from itertools import cycle
import os
import threading
import time

_traffic = cycle(("normal", "slow", "normal", "wrong_tool", "normal", "over_limit"))
_lock = threading.Lock()


class PolicyBlocked(ValueError):
    pass


class Failures:
    def __init__(self, profile=None, sleep=time.sleep):
        if profile is None:
            with _lock:
                profile = next(_traffic)
        if profile not in {"normal", "slow", "wrong_tool", "over_limit"}:
            raise ValueError("Unknown traffic profile")
        self.profile, self.sleep = profile, sleep
        self.used = False
        self.enforce = os.getenv("KIOSK_ENFORCE_LIMIT", "0") == "1"
        self.calls = []

    def dispatch(self, requested, arguments, execute, log):
        actual, actual_args = requested, arguments
        if not self.used and requested in {"get_menu", "search_menu"}:
            self.used = True
            if self.profile == "slow":
                log.warning("Menu lookup stalled; waiting for its 8-second timeout")
                self.sleep(8)
                raise TimeoutError("Menu lookup timed out after 8 seconds")
            if self.profile == "wrong_tool":
                actual, actual_args = "get_current_order", {}
                log.warning("Wrong tool executed: requested=%s actual=%s", requested, actual)
        self.calls.append({"requested": requested, "actual": actual, "arguments": actual_args})
        return execute(actual, actual_args)

    def validate_total(self, total, log):
        # Fault 3: this new business limit is observed but initially not enforced.
        # Existing stock, ownership and quantity checks remain enforced in SQLite.
        if total > 50000:
            if self.enforce:
                log.warning("Order blocked before write: total_paise=%s limit_paise=50000", total)
                raise PolicyBlocked("Orders above ₹500 require approval.")
            log.warning("Order exceeds allowed limit: total_paise=%s limit_paise=50000; enforcement disabled", total)
        else:
            log.info("Order limit check passed: total_paise=%s", total)
