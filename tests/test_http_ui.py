"""Opt-in localhost and Streamlit integration checks, with a mocked model only."""
import itertools
import os
from pathlib import Path
import socket
import sys
import subprocess
import threading
import unittest
from unittest.mock import patch, Mock
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_application
import config
import api
import agent
import database
import failures
from langchain_core.messages import AIMessage


@unittest.skipUnless(os.getenv("RUN_HTTP_CHECKS") == "1", "Set RUN_HTTP_CHECKS=1 for localhost/UI checks")
class HttpUiTests(unittest.TestCase):
    def setUp(self):
        test_application.ApplicationTests.setUp(self)
        self.quantity = 1
        self.stack.enter_context(patch.object(agent, "get_model", side_effect=lambda: test_application.FakeModel(self.quantity)))
        self.stack.enter_context(patch.object(failures, "_traffic", itertools.cycle(("normal",))))
        self.httpd = api.ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        self.port = self.httpd.server_port
        self.stack.enter_context(patch.object(config, "API_PORT", self.port))
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()
        self.url = "http://127.0.0.1:" + str(self.port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=2)
        test_application.ApplicationTests.tearDown(self)

    def post(self, path, payload, token=None):
        return requests.post(self.url + path, json=payload,
                             headers={"Authorization": "Bearer " + (token or self.token)}, timeout=30)

    def test_embedded_api_starts_when_not_running(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = api.ensure_api_server(port)
        self.assertIsNotNone(server)
        try:
            self.assertEqual(requests.get(f"http://127.0.0.1:{port}/health", timeout=2).json()["status"], "ok")
        finally:
            with api._embedded_servers_lock:
                api._embedded_servers.pop(port, None)
            server.shutdown()
            server.server_close()

    def test_http_login_chat_checkout_and_failed_auth(self):
        login = self.post("/signin", {"name": "Customer", "email": "http@example.invalid"})
        self.assertEqual(login.status_code, 200)
        token = login.json()["access_token"]
        result = self.post("/chat", {"query": "Order one coffee", "profile": "normal"}, token)
        self.assertEqual(result.status_code, 200)
        placed = self.post("/checkout", {"order_id": result.json()["order"]["order_id"]}, token)
        self.assertEqual(placed.status_code, 200)
        self.assertEqual(placed.json()["status"], "placed")
        current = requests.get(self.url + "/order",
                               headers={"Authorization": "Bearer " + token}, timeout=5)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["status"], "placed")
        self.assertEqual(current.json()["items"][0]["product_id"], "cold_coffee")
        self.assertEqual(self.post("/chat", {"query": "Hi"}, "invalid").status_code, 401)

    def test_three_complaints_and_guard_over_http(self):
        original = failures.Failures.__init__
        def no_wait(faults, *args, **kwargs):
            original(faults, *args, **kwargs)
            faults.sleep = lambda seconds: None
        with patch.object(failures.Failures, "__init__", no_wait):
            timed_out = self.post("/chat", {"query": "Show menu", "profile": "slow"})
        self.assertEqual(timed_out.status_code, 504)
        wrong = self.post("/chat", {"query": "Order coffee", "profile": "wrong_tool"})
        self.assertEqual(wrong.status_code, 200)
        self.assertFalse(wrong.json()["checks"]["tool_selection_pass"])
        self.quantity = 10
        large = self.post("/chat", {"query": "Order ten coffees", "profile": "over_limit"})
        self.assertEqual(large.status_code, 200)
        self.assertEqual(large.json()["order"]["total_paise"], 120000)
        self.assertFalse(large.json()["checks"]["order_limit_pass"])
        with patch.dict(os.environ, {"KIOSK_ENFORCE_LIMIT": "1"}):
            blocked = self.post("/chat", {"query": "Order ten coffees", "profile": "over_limit"})
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(database.read_current_order(self.customer_id)["total_paise"], 120000)

    def test_streamlit_signin_chat_and_place_order(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(config.ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception)
        app.text_input[0].set_value("UI Student")
        app.text_input[1].set_value("ui@example.invalid")
        next(b for b in app.button if b.label == "Start my order").click().run()
        app.run()  # Settle the sign-in rerun before submitting a different widget tree.
        self.assertFalse(app.exception)
        app.chat_input[0].set_value("Show the menu and add one coffee").run()
        self.assertFalse(app.exception)
        self.assertTrue(any(m.label == "Total" and m.value == "₹120.00" for m in app.metric))
        app.checkbox[0].check().run()
        next(b for b in app.button if b.label == "Place order").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Order placed" in message.value for message in app.success))
        with database.connect_db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM orders WHERE status='placed'").fetchone()[0], 1)

    def test_simple_chat_generates_plain_logs(self):
        from streamlit.testing.v1 import AppTest
        model = Mock()
        model.invoke.return_value = AIMessage(content="Hello from the model")
        with patch.object(agent, "get_model", return_value=model):
            app = AppTest.from_file(str(config.ROOT / "simple_chat.py"), default_timeout=30).run()
            app.chat_input[0].set_value("Hello").run()
        self.assertFalse(app.exception)
        raw = (self.root / "kiosk.log").read_text()
        self.assertIn("User message: 'Hello'", raw)
        self.assertIn("Assistant answer: 'Hello from the model'", raw)

    def test_locust_records_all_three_complaints(self):
        class TrafficModel:
            def __init__(self):
                self.model = None

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                if self.model is None:
                    quantity = 10 if "10 cold" in messages[-1].content else 1
                    self.model = test_application.FakeModel(quantity)
                return self.model.invoke(messages)

        env = dict(os.environ, KIOSK_TRAFFIC="complaints", KIOSK_CHECK_EVALS="0")
        with patch.object(agent, "get_model", side_effect=TrafficModel):
            result = subprocess.run([sys.executable, "-m", "locust", "-f",
                str(config.ROOT / "load_testing" / "locustfile.py"), "--host", self.url,
                "--headless", "-u", "1", "-r", "1", "-t", "30s", "--stop-timeout", "12",
                "--only-summary"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)  # Expected timeout failure.
        raw = (self.root / "kiosk.log").read_text()
        self.assertIn("Menu lookup stalled", raw)
        self.assertIn("Request failed: error=TimeoutError", raw)
        self.assertIn("Wrong tool executed: requested=get_menu actual=get_current_order", raw)
        self.assertIn("Order exceeds allowed limit: total_paise=120000", raw)


if __name__ == "__main__":
    unittest.main()
