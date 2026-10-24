"""Explicit live smoke check: real OpenRouter usage; temporary data and logs."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_application import ApplicationTests
import agent


def main():
    case = ApplicationTests("test_signin_and_order_placement_are_owned_and_idempotent")
    case.setUp()
    started = time.perf_counter()
    try:
        result = agent.chat("Show the menu, read my current order, and save a draft with exactly one cold coffee. Do not pay.",
                            case.token, "normal")
        assert result["order"]["status"] == "draft", result["order"]
        assert result["order"]["items"][0]["product_id"] == "cold_coffee", result["order"]
        assert result["order"]["items"][0]["quantity"] == 1, result["order"]
        print(f"Real model + tools + SQLite draft succeeded in {time.perf_counter()-started:.2f}s.")
        print("No classroom log, existing order, payment or email was changed.")
    except Exception as exc:
        print("Live check failed:", type(exc).__name__, "HTTP", getattr(exc, "status_code", None))
        raise SystemExit(1)
    finally:
        case.tearDown()


if __name__ == "__main__":
    main()
