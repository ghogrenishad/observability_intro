"""One API shared by the Streamlit customer app and Locust traffic."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4
from config import API_PORT, initialize_database
from logging_setup import request_logger
from sessions import sign_in, sign_out, require_user, load_history
from database import read_menu, read_customer_order, get_owned_order, mark_paid
from agent import chat
from failures import Failures, PolicyBlocked
from instrumentation import span

_embedded_servers = {}
_embedded_servers_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def token(self):
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            raise PermissionError("Please sign in.")
        return value[7:]

    def do_GET(self):
        try:
            if self.path == "/health":
                return self.reply(200, {"status": "ok", "service": "session_1_monitoring"})
            if self.path == "/menu":
                return self.reply(200, read_menu())
            user = require_user(self.token())
            if self.path == "/order":
                return self.reply(200, read_customer_order(user["customer_id"]))
            if self.path == "/history":
                return self.reply(200, [{"role": "user" if m.type == "human" else "assistant", "content": m.content}
                                        for m in load_history(user["customer_id"])])
            self.reply(404, {"error": "Not found"})
        except PermissionError as exc:
            self.reply(401, {"error": str(exc)})
        except Exception:
            request_logger().exception("GET request failed")
            self.reply(500, {"error": "Could not load kiosk data"})

    def do_POST(self):
        request_id = str(uuid4())
        log = request_logger(request_id)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError("Expected a JSON body of at most 16 KB")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            if self.path == "/signin":
                result = sign_in(body.get("name"), body.get("email"))
                log.info("Customer signed in: customer_id=%s", result["customer"]["customer_id"])
                return self.reply(200, result)
            token = self.token()
            user = require_user(token)
            if self.path == "/chat":
                return self.reply(200, chat(body.get("query"), token, body.get("profile")))
            if self.path == "/signout":
                sign_out(token)
                return self.reply(200, {"signed_out": True})
            if self.path == "/checkout":
                order = get_owned_order(user["customer_id"], body["order_id"])
                policy = Failures("normal")
                with span("checkout", request_id=request_id, order_id=order["order_id"]):
                    paid = mark_paid(user["customer_id"], order["order_id"], "demo-" + order["order_id"],
                                     validate_total=lambda total: policy.validate_total(total, log))
                log.info("Order placed with demo payment: order_id=%s total_paise=%s", paid["order_id"], paid["total_paise"])
                return self.reply(200, paid)
            self.reply(404, {"error": "Not found"})
        except PolicyBlocked as exc:
            log.warning("Write prevented by policy")
            self.reply(409, {"error": str(exc)})
        except PermissionError as exc:
            self.reply(401, {"error": str(exc)})
        except TimeoutError as exc:
            self.reply(504, {"error": str(exc)})
        except (ValueError, KeyError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            log.error("Request failed: error=%s", type(exc).__name__)
            self.reply(500, {"error": "Request failed: " + type(exc).__name__})

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass  # Application logs go to kiosk.log, not the terminal's HTTP access log.


def ensure_api_server(port=API_PORT):
    """Start an in-process API when the UI is not already using one."""
    health_url = f"http://127.0.0.1:{port}/health"

    def is_healthy():
        try:
            with urlopen(health_url, timeout=0.2) as response:
                return response.status == 200
        except (OSError, URLError):
            return False

    if is_healthy():
        return None

    with _embedded_servers_lock:
        if is_healthy():
            return None
        initialize_database()
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        worker = threading.Thread(target=server.serve_forever, name="kiosk-api", daemon=True)
        worker.start()
        _embedded_servers[port] = server
        for _ in range(50):
            if is_healthy():
                request_logger().info("Embedded API ready: http://127.0.0.1:%s", port)
                return server
            time.sleep(0.02)
        server.shutdown()
        server.server_close()
        del _embedded_servers[port]
        raise RuntimeError(f"Embedded API did not become ready on port {port}")


if __name__ == "__main__":
    initialize_database()
    request_logger().info("API ready: http://127.0.0.1:%s", API_PORT)
    print(f"Kiosk API: http://127.0.0.1:{API_PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", API_PORT), Handler).serve_forever()
