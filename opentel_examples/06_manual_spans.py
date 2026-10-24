"""6. Turn timed operations into connected records: one trace, multiple spans."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
from time import perf_counter, time_ns
from uuid import uuid4
from common import MODEL, configure_logs, make_client, options, run

current = ContextVar("current_span", default=None)


class SpanFields(logging.Filter):
    def filter(self, record):
        active = current.get()
        record.trace_id = active["trace_id"] if active else "-"
        record.span_id = active["span_id"] if active else "-"
        return True


@contextmanager
def span(name, output, **attributes):
    parent = current.get()
    record = {"trace_id": parent["trace_id"] if parent else uuid4().hex,
              "span_id": uuid4().hex[:16], "parent_span_id": parent["span_id"] if parent else None,
              "name": name, "start_time_ns": time_ns(), "status": "ok", "attributes": attributes}
    token = current.set(record)
    started = perf_counter()
    try:
        yield attributes
    except Exception as exc:
        record.update(status="error", error=type(exc).__name__)
        raise
    finally:
        record["duration_ms"] = round((perf_counter() - started) * 1000, 2)
        try:
            output.write(json.dumps(record) + "\n")
            output.flush()
        finally:
            current.reset(token)


def calculate_refund(amount_paid, fee, log, output):
    with span("calculate_refund", output, amount_paid=amount_paid, fee=fee) as detail:
        refund = amount_paid - fee
        detail["refund"] = refund
        log.info("Refund calculated: refund=%s", refund)
        return refund


def call_model(client, question, log, output):
    with span("call_model", output, model=MODEL) as detail:
        log.info("Calling model")
        try:
            response = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": question}])
        except Exception:
            log.exception("SDK call failed")
            raise
        if response.usage:
            detail.update(input_tokens=response.usage.prompt_tokens, output_tokens=response.usage.completion_tokens)
        log.info("Model response received")
        return response


def answer_question(client, question, log, output):
    with span("answer_question", output, user_id="A", request_id="R103"):
        log.info("Request received")
        refund = calculate_refund(1200, 100, log, output)
        response = call_model(client, question + f" The application calculated the refund as INR {refund}.", log, output)
        log.info("Returning answer")
        return response.choices[0].message.content


def main():
    args = options(__doc__)
    log = configure_logs(args, "06_manual.log", custom_format="%(asctime)s trace=%(trace_id)s span=%(span_id)s %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(SpanFields())
    with make_client(args) as client, (args.output_dir / "06_spans.jsonl").open("w") as output:
        print(answer_question(client, args.question, log, output))
    print("Open output/06_spans.jsonl: one root and two child spans.")


if __name__ == "__main__":
    run(main)
