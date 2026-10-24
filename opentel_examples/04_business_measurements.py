"""4. Record inputs, result and duration of a business function we own."""
import logging
from time import perf_counter
from common import MODEL, configure_logs, make_client, options, run


def calculate_refund(amount_paid, fee, log):
    started = perf_counter()
    refund = amount_paid - fee
    log.info("Refund calculated: paid=%s fee=%s refund=%s duration_ms=%.2f",
             amount_paid, fee, refund, (perf_counter() - started) * 1000)
    return refund


def answer_question(client, question, log):
    log.info("Request received")
    refund = calculate_refund(1200, 100, log)
    log.info("Calling model")
    response = client.chat.completions.create(model=MODEL, messages=[
        {"role": "user", "content": question + f" The application calculated the refund as INR {refund}."}])
    log.info("Model response received")
    log.info("Returning answer")
    return response.choices[0].message.content


def main():
    args = options(__doc__)
    logger = configure_logs(args, "04_business.log", correlated=True)
    log = logging.LoggerAdapter(logger, {"user_id": "A", "request_id": "R103"})
    with make_client(args) as client:
        print(answer_question(client, args.question, log))


if __name__ == "__main__":
    run(main)
