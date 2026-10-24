"""Real tools and SQLite, deterministic model replies; no paid calls or live log writes."""
import contextlib
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import database
import logging_setup
import instrumentation
from failures import Failures, PolicyBlocked
from sessions import sign_in, require_user
import agent
from langchain_core.messages import AIMessage


class FakeModel:
    def __init__(self, quantity=1):
        self.responses = iter([
            AIMessage(content="", tool_calls=[{"name": "get_menu", "args": {}, "id": "menu"},
                                              {"name": "get_current_order", "args": {}, "id": "read"}]),
            AIMessage(content="", tool_calls=[{"name": "set_order", "args": {"items": [
                {"product_id": "cold_coffee", "quantity": quantity}]}, "id": "write"}]),
            AIMessage(content="Your draft is saved. Review it before placing the order.",
                      usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
        ])

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return next(self.responses)


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        for module, name, value in [(config, "DB_PATH", self.root / "test.sqlite3"),
                                     (database, "DB_PATH", self.root / "test.sqlite3"),
                                     (instrumentation, "ROOT", self.root),
                                     (instrumentation, "TRACING", "off"),
                                     (logging_setup, "LOG_PATH", self.root / "kiosk.log")]:
            self.stack.enter_context(patch.object(module, name, value))
        self.stack.enter_context(patch.dict(os.environ, {"KIOSK_ENFORCE_LIMIT": "0"}))
        config.initialize_database()
        self.logger = logging.getLogger("session1.kiosk")
        self.original_handlers = self.logger.handlers
        self.logger.handlers = []
        self.login = sign_in("Student", "student@example.invalid")
        self.token = self.login["access_token"]
        self.customer_id = self.login["customer"]["customer_id"]

    def tearDown(self):
        for handler in self.logger.handlers:
            handler.close()
        self.logger.handlers = self.original_handlers
        self.stack.close()
        self.temp.cleanup()

    def chat(self, profile="normal", quantity=1):
        with patch.object(agent, "get_model", return_value=FakeModel(quantity)):
            return agent.chat("Show the menu and order coffee.", self.token, profile)

    def test_signin_and_order_placement_are_owned_and_idempotent(self):
        result = self.chat()
        self.assertTrue(all(result["checks"].values()))
        order_id = result["order"]["order_id"]
        other = sign_in("Other", "other@example.invalid")
        with self.assertRaises(PermissionError):
            database.get_owned_order(other["customer"]["customer_id"], order_id)
        first = database.mark_paid(self.customer_id, order_id, "demo-" + order_id)
        database.mark_paid(self.customer_id, order_id, "demo-" + order_id)
        self.assertEqual(first["status"], "placed")
        visible_order = database.read_customer_order(self.customer_id)
        self.assertEqual(visible_order["order_id"], order_id)
        self.assertEqual(visible_order["status"], "placed")
        self.assertEqual(visible_order["items"][0]["product_id"], "cold_coffee")
        coffee = next(p for p in database.read_menu() if p["product_id"] == "cold_coffee")
        self.assertEqual(coffee["stock_quantity"], 19)

    def test_expired_session_rejected(self):
        with database.connect_db() as db:
            db.execute("UPDATE demo_sessions SET expires=0")
        with self.assertRaises(PermissionError):
            require_user(self.token)

    def test_slow_fault_really_fails_before_lookup(self):
        sleeps, calls = [], []
        faults = Failures("slow", sleep=sleeps.append)
        log = logging_setup.request_logger("slow-test")
        with self.assertRaises(TimeoutError):
            faults.dispatch("get_menu", {}, lambda *args: calls.append(args), log)
        self.assertEqual(sleeps, [8])
        self.assertEqual(calls, [])

    def test_wrong_dispatch_is_logged_and_fails_check(self):
        result = self.chat("wrong_tool")
        self.assertFalse(result["checks"]["tool_selection_pass"])
        raw = (self.root / "kiosk.log").read_text()
        self.assertIn("Wrong tool executed: requested=get_menu actual=get_current_order", raw)

    def test_limit_observed_without_guard(self):
        result = self.chat("over_limit", quantity=10)
        self.assertFalse(result["checks"]["order_limit_pass"])
        self.assertEqual(result["order"]["total_paise"], 120000)

    def test_guard_blocks_before_write_and_does_not_replace_existing_draft(self):
        self.chat()
        with patch.dict(os.environ, {"KIOSK_ENFORCE_LIMIT": "1"}):
            with self.assertRaises(PolicyBlocked):
                self.chat("over_limit", quantity=10)
        order = database.read_current_order(self.customer_id)
        self.assertEqual(order["total_paise"], 12000)
        self.assertEqual(order["items"][0]["quantity"], 1)

    def test_guard_also_protects_checkout_of_existing_oversized_draft(self):
        result = self.chat("over_limit", quantity=10)
        policy = Failures("normal")
        policy.enforce = True
        with self.assertRaises(PolicyBlocked):
            database.mark_paid(self.customer_id, result["order"]["order_id"], "demo-pay",
                               validate_total=lambda total: policy.validate_total(total, logging_setup.request_logger()))
        order = database.read_current_order(self.customer_id)
        self.assertEqual(order["payment_status"], "unpaid")

    def test_manual_traces_share_root_and_do_not_appear_when_off(self):
        self.chat()
        self.assertFalse((self.root / "traces.jsonl").exists())
        with patch.object(instrumentation, "TRACING", "manual"):
            self.chat()
        records = [json.loads(line) for line in (self.root / "traces.jsonl").read_text().splitlines()]
        root = next(r for r in records if r["parent_span_id"] is None)
        self.assertEqual(root["name"], "chat")
        self.assertEqual(len({r["trace_id"] for r in records}), 1)
        self.assertTrue(any(r["name"] == "database.save_draft" for r in records))
        self.assertEqual(instrumentation._current.get(), None)

    def test_otel_sdk_exports_real_parented_spans(self):
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
        except ImportError:
            self.skipTest("Install requirements.txt for the OpenTelemetry SDK check")
        stream = io.StringIO()
        provider = TracerProvider(resource=Resource.create({"service.name": "test-kiosk"}))
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(
            out=stream, formatter=lambda record: record.to_json(indent=None) + "\n")))
        tracer = provider.get_tracer("test")
        with patch.object(instrumentation, "TRACING", "otel"), \
             patch.object(instrumentation, "otel_tracer", return_value=(tracer, provider)):
            self.chat()
        provider.force_flush()
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertTrue(any(r["name"] == "chat" and r["parent_id"] is None for r in rows))
        self.assertEqual(len({r["context"]["trace_id"] for r in rows}), 1)
        provider.shutdown()


if __name__ == "__main__":
    unittest.main()
