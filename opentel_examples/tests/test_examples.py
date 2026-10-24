"""Fresh-process checks: no provider network calls and no LangSmith uploads."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, script, fail=False, offline=True):
        command = [sys.executable, str(ROOT / script), "--output-dir", str(self.output)]
        if offline:
            command.append("--offline")
        if fail:
            command.append("--fail")
        result = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                env=dict(os.environ, LANGSMITH_API_KEY="", LANGSMITH_TRACING="false"))
        expected = 1 if fail or (script == "08_langsmith.py" and not offline) else 0
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("--- Logging error ---", result.stderr)
        return result

    def read_spans(self, name):
        return [json.loads(line) for line in (self.output / name).read_text().splitlines()]

    def test_first_five_steps_and_request_correlation(self):
        for script in ("01_working_app.py", "02_plain_logs.py", "03_request_ids.py",
                       "04_business_measurements.py", "05_sdk_measurements.py"):
            with self.subTest(script=script):
                result = self.execute(script)
                self.assertIn("INR 1100", result.stdout)
        requests = (self.output / "03_requests.log").read_text()
        for request in ("R101", "R102", "R103"):
            records = [line for line in requests.splitlines() if "request=" + request in line]
            self.assertEqual(len(records), 4)
            self.assertTrue(any("Request received" in line for line in records))
            self.assertTrue(any("Returning answer" in line for line in records))
        self.assertIn("paid=1200 fee=100 refund=1100", (self.output / "04_business.log").read_text())
        self.assertIn("input_tokens=42 output_tokens=18", (self.output / "05_sdk.log").read_text())

    def test_sdk_failure_is_logged_and_propagated(self):
        self.execute("05_sdk_measurements.py", fail=True)
        self.assertIn("SDK call failed", (self.output / "05_sdk.log").read_text())

    def test_manual_span_parentage_and_log_correlation(self):
        self.execute("06_manual_spans.py")
        rows = self.read_spans("06_spans.jsonl")
        self.assertEqual(len(rows), 3)
        root = next(row for row in rows if row["parent_span_id"] is None)
        self.assertEqual(root["name"], "answer_question")
        self.assertEqual(len({row["trace_id"] for row in rows}), 1)
        children = [row for row in rows if row is not root]
        self.assertTrue(all(row["parent_span_id"] == root["span_id"] for row in children))
        refund = next(row for row in rows if row["name"] == "calculate_refund")
        self.assertEqual(refund["attributes"]["refund"], 1100)
        self.assertIn(root["trace_id"], (self.output / "06_manual.log").read_text())

    def test_manual_error_marks_sdk_and_root(self):
        self.execute("06_manual_spans.py", fail=True)
        rows = self.read_spans("06_spans.jsonl")
        failed = {row["name"] for row in rows if row["status"] == "error"}
        self.assertEqual(failed, {"answer_question", "call_model"})

    def test_otel_creates_sdk_span_automatically(self):
        self.execute("07_opentelemetry.py")
        rows = self.read_spans("07_otel_spans.jsonl")
        root = next(row for row in rows if row["parent_id"] is None)
        self.assertEqual(root["name"], "answer_question")
        sdk = next(row for row in rows if row["attributes"].get("gen_ai.request.model"))
        self.assertEqual(sdk["parent_id"], root["context"]["span_id"])
        self.assertEqual(sdk["attributes"].get("gen_ai.usage.input_tokens"), 42)
        self.assertEqual(sdk["attributes"].get("gen_ai.usage.output_tokens"), 18)
        self.assertEqual(len({row["context"]["trace_id"] for row in rows}), 1)
        self.assertEqual(root["resource"]["attributes"]["service.name"], "order-assistant")
        self.assertIn(root["context"]["trace_id"][2:], (self.output / "07_otel.log").read_text())

    def test_otel_records_errors_on_sdk_and_root(self):
        self.execute("07_opentelemetry.py", fail=True)
        rows = self.read_spans("07_otel_spans.jsonl")
        errors = [row for row in rows if row["status"]["status_code"] == "ERROR"]
        self.assertGreaterEqual(len(errors), 2)
        self.assertTrue(any(row["events"] for row in errors))

    def test_langsmith_offline_wrapper_and_missing_key(self):
        result = self.execute("08_langsmith.py")
        self.assertIn("no LangSmith dashboard trace was created", result.stdout)
        result = self.execute("08_langsmith.py", offline=False)
        self.assertIn("Add LANGSMITH_API_KEY", result.stderr)

    def test_langsmith_run_record_is_saved_to_sqlite(self):
        sys.path.insert(0, str(ROOT))
        try:
            from importlib.util import module_from_spec, spec_from_file_location
            spec = spec_from_file_location("langsmith_example", ROOT / "08_langsmith.py")
            module = module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(ROOT))

        database = module.record_run(self.output, "Refund question", 1100, "Refund is INR 1100.", "run-123")
        with sqlite3.connect(database) as db:
            row = db.execute("""SELECT langsmith_run_id, question, refund_inr, answer, created_at
                FROM langsmith_runs""").fetchone()
        self.assertEqual(row[:4], ("run-123", "Refund question", 1100, "Refund is INR 1100."))
        self.assertTrue(row[4])


if __name__ == "__main__":
    unittest.main()
