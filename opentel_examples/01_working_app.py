"""1. The SDK makes the request. We record nothing about execution yet."""
from common import MODEL, make_client, options, run


def call_model(client, question):
    return client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": question}])


def answer_question(client, question):
    response = call_model(client, question)
    return response.choices[0].message.content


def main():
    args = options(__doc__)
    with make_client(args) as client:
        print(answer_question(client, args.question))


if __name__ == "__main__":
    run(main)
