"""5. Observe the SDK boundary: requested model, duration, exceptions and returned usage."""
import logging
from time import perf_counter
from common import MODEL, configure_logs, make_client, options, run


def calculate_refund(amount_paid, fee, log):
    started = perf_counter()
    refund = amount_paid - fee
    log.info("Refund calculated: paid=%s fee=%s refund=%s duration_ms=%.2f",
             amount_paid, fee, refund, (perf_counter() - started) * 1000)
    return refund


def call_model(client, question, log):
    started = perf_counter()
    log.info("SDK call started: model=%s", MODEL)
    try:
        response = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": question}])
    except Exception:
        log.exception("SDK call failed: duration_ms=%.2f", (perf_counter() - started) * 1000)
        raise
    usage = response.usage
    log.info("SDK call completed: duration_ms=%.2f input_tokens=%s output_tokens=%s",
             (perf_counter() - started) * 1000,
             usage.prompt_tokens if usage else "unknown", usage.completion_tokens if usage else "unknown")
    return response


def answer_question(client, question, log):
    log.info("Request received")
    refund = calculate_refund(1200, 100, log)
    response = call_model(client, question + f" The application calculated the refund as INR {refund}.", log)
    log.info("Returning answer")
    return response.choices[0].message.content


def main():
    args = options(__doc__)
    logger = configure_logs(args, "05_sdk.log", correlated=True)
    log = logging.LoggerAdapter(logger, {"user_id": "A", "request_id": "R103"})
    with make_client(args) as client:
        print(answer_question(client, args.question, log))


if __name__ == "__main__":
    run(main)
