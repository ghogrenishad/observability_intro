"""3. Concurrent requests interleave. Add user and request IDs to group their logs."""
from concurrent.futures import ThreadPoolExecutor
import logging
from common import MODEL, configure_logs, make_client, options, run


def answer_question(client, user_id, request_id, question, logger):
    log = logging.LoggerAdapter(logger, {"user_id": user_id, "request_id": request_id})
    log.info("Request received")
    log.info("Calling model")
    response = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": question}])
    log.info("Model response received")
    log.info("Returning answer")
    return response.choices[0].message.content


def main():
    args = options(__doc__)
    logger = configure_logs(args, "03_requests.log", correlated=True)
    with make_client(args) as client:
        # Readable labels are supplied by us here; they are not SDK-generated trace IDs.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(answer_question, client, user, request, args.question, logger)
                       for user, request in (("A", "R101"), ("B", "R102"), ("A", "R103"))]
            for future in futures:
                print(future.result())


if __name__ == "__main__":
    run(main)
