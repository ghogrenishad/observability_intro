"""2. Add messages describing execution. These log statements are instrumentation."""
from common import MODEL, configure_logs, make_client, options, run


def answer_question(client, question, log):
    log.info("Request received")
    log.info("Calling model")
    response = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": question}])
    log.info("Model response received")
    log.info("Returning answer")
    return response.choices[0].message.content


def main():
    args = options(__doc__)
    log = configure_logs(args, "02_plain.log")
    with make_client(args) as client:
        print(answer_question(client, args.question, log))


if __name__ == "__main__":
    run(main)
