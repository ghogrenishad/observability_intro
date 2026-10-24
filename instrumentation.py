"""Opt-in teaching steps: off → manual spans → OpenTelemetry SDK spans."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import json
import threading
import time
from uuid import uuid4
from config import ROOT, TRACING

_current = ContextVar("span_context", default=None)
_lock = threading.Lock()


@lru_cache(maxsize=1)
def otel_tracer():
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": "kiosk"}))
    stream = (ROOT / "otel-spans.jsonl").open("a", buffering=1)
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(
        out=stream, formatter=lambda record: record.to_json(indent=None) + "\n")))
    return provider.get_tracer("session_1_monitoring"), provider


@contextmanager
def span(name, **attributes):
    if TRACING == "off":
        yield attributes
        return
    if TRACING == "otel":
        tracer, _ = otel_tracer()
        with tracer.start_as_current_span(name) as active:
            try:
                yield attributes
            finally:
                for key, value in attributes.items():
                    active.set_attribute(key, json.dumps(value) if isinstance(value, (dict, list)) else value)
        return
    parent = _current.get()
    record = {"trace_id": parent["trace_id"] if parent else uuid4().hex,
              "span_id": uuid4().hex[:16], "parent_span_id": parent["span_id"] if parent else None,
              "name": name, "start_time_ns": time.time_ns(), "status": "ok", "attributes": attributes}
    token = _current.set(record)
    started = time.perf_counter()
    try:
        yield attributes
    except Exception as exc:
        record.update(status="error", error=type(exc).__name__)
        raise
    finally:
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        try:
            with _lock, (ROOT / "traces.jsonl").open("a") as stream:
                stream.write(json.dumps(record) + "\n")
        finally:
            _current.reset(token)
