"""7. Let the OpenTelemetry SDK manage spans, and an integration observe SDK calls."""
import os
from common import MODEL, configure_logs, make_client, options, run
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor


def calculate_refund(amount_paid, fee, log, tracer):
    # Automatic SDK instrumentation cannot know our business calculations.
    with tracer.start_as_current_span("calculate_refund") as active:
        refund = amount_paid - fee
        active.set_attribute("app.amount_paid", amount_paid)
        active.set_attribute("app.fee", fee)
        active.set_attribute("app.refund", refund)
        log.info("Refund calculated: refund=%s", refund)
        return refund


def call_model(client, question):
    # No manual timer, token logging or SDK-call span: the integration supplies them.
    return client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": question}])


def answer_question(client, question, log, tracer):
    with tracer.start_as_current_span("answer_question") as active:
        active.set_attribute("app.user_id", "A")
        active.set_attribute("app.request_id", "R103")
        log.info("Request received")
        refund = calculate_refund(1200, 100, log, tracer)
        log.info("Calling model")
        response = call_model(client, question + f" The application calculated the refund as INR {refund}.")
        log.info("Returning answer")
        return response.choices[0].message.content


def main():
    args = options(__doc__)
    # 1. Resource: identify the service producing telemetry.
    resource = Resource.create({"service.name": "order-assistant"})
    # 2. Provider: own the tracing configuration and span creation.
    provider = TracerProvider(resource=resource)
    with (args.output_dir / "07_otel_spans.jsonl").open("w") as output:
        # 3. Exporter: write completed spans as one JSON record per line.
        exporter = ConsoleSpanExporter(out=output, formatter=lambda record: record.to_json(indent=None) + "\n")
        # 4. Processor: hand each completed span to the exporter.
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        # 5. Register the provider; obtain an object that starts application spans.
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("order_assistant")
        # 6. Wrap supported OpenAI SDK methods automatically, before creating clients.
        sdk_instrumentor = OpenAIInstrumentor()
        sdk_instrumentor.instrument()
        # 7. Attach active trace/span IDs to ordinary logging records.
        # We only want correlation here, not an additional OTel log exporter.
        os.environ["OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION"] = "false"
        # This pinned version enables context injection with set_logging_format.
        # configure_logs() then replaces the default handlers/format with ours.
        LoggingInstrumentor().instrument(set_logging_format=True)
        log = configure_logs(args, "07_otel.log", custom_format=
                             "%(asctime)s trace=%(otelTraceID)s span=%(otelSpanID)s %(message)s")
        try:
            with make_client(args) as client:
                print(answer_question(client, args.question, log, tracer))
        finally:
            provider.force_flush()
            provider.shutdown()
            sdk_instrumentor.uninstrument()
    print("Open output/07_otel_spans.jsonl: the SDK-call child span was created automatically.")


if __name__ == "__main__":
    run(main)
