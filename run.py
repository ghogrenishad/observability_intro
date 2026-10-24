"""Start the working kiosk. Load testing is a separate command."""
import argparse
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4
from config import ROOT, API_PORT, TRACING
from logging_setup import request_logger, LOG_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-model-check", action="store_true", help="For offline UI/tests only")
    args = parser.parse_args()
    log = request_logger()
    log.info("Application starting: run_id=%s tracing=%s", uuid4().hex, TRACING)
    log.info("Python runtime: version=%s executable=%s", sys.version.split()[0], sys.executable)
    print("Application log: " + str(LOG_PATH), flush=True)
    print("Python: " + sys.executable, flush=True)
    if not args.skip_model_check:
        from agent import get_model
        try:
            print("Checking model connection…", flush=True)
            get_model().invoke("Reply OK only.", max_tokens=8)
        except Exception as exc:
            log.error("Startup stopped: model=%s HTTP=%s", type(exc).__name__, getattr(exc, "status_code", None))
            print("Model connection failed. Check this folder's .env and kiosk.log.", flush=True)
            return 1
    if TRACING == "otel":
        from instrumentation import otel_tracer
        otel_tracer()  # Check the optional SDK before starting processes.
    children = []
    try:
        api = subprocess.Popen([sys.executable, str(ROOT / "api.py")], cwd=ROOT)
        children.append(api)
        for _ in range(100):
            if api.poll() is not None:
                raise RuntimeError("API did not start; see the error above")
            try:
                with urlopen(f"http://127.0.0.1:{API_PORT}/health", timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("API did not become ready")
        ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
                               "--server.address", "127.0.0.1", "--server.port", "8501", "--server.headless", "true"], cwd=ROOT)
        children.append(ui)
        print("Customer app: http://localhost:8501", flush=True)
        print("Load testing is separate: see load_testing/locustfile.py. Ctrl+C stops the app.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Application stopping")
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
