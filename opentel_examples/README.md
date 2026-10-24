# From an application to logs, traces, OpenTelemetry and LangSmith

Open the numbered files **one at a time**. Each is runnable on its own. They use
one example throughout: a customer paid **₹1,200**, the cancellation fee is
**₹100**, and the application explains a **₹1,100 refund**. No money moves.

These are small CLI examples, separate from the Streamlit kiosk and Locust.
They do not start servers or traffic. The code to teach is in the numbered files;
`common.py` only supplies credentials, CLI options, logging destinations and the
explicit offline test transport.

## Prepare once

From this `opentel_examples` folder:

```sh
conda activate ai-dev
python -m pip install -r requirements.txt
```

The supported environment is **`ai-dev`, Python 3.12**. OpenAI and LangSmith
versions match that environment. The OpenTelemetry integration and its wrapper
library are pinned together to keep the instrumentation examples compatible.

The examples read **`../.env`**, the `.env` inside `session_1_monitoring`. Your
existing `OPEN_ROUTER_API_KEY` is used. The Python library is the **OpenAI SDK**,
configured to call OpenRouter's compatible API, using
`google/gemini-2.5-flash`. `OPEN_ROUTER_MODEL` can override that model. Calling the
SDK does not mean we are calling OpenAI's own servers in this configuration.

The ordinary commands below make real paid model calls. Step 3 makes three
calls to show concurrency; each other step normally makes one. Answers and
durations can vary. Run each file in a fresh Python process as shown.

For a practice run with no network or credentials, append **`--offline`** to
any command. It sends an explicitly synthetic response through the real SDK
using an HTTPX test transport. The terminal labels it OFFLINE. The answer, usage
and HTTP result are fixtures; the local span creation and timing are real.
Do not present that as a live model run. LangSmith uploading is disabled offline.

## The eight steps

| Step | File | New idea |
| --- | --- | --- |
| 1 | `01_working_app.py` | The SDK makes a request and returns an answer |
| 2 | `02_plain_logs.py` | We write messages about execution |
| 3 | `03_request_ids.py` | Identify requests when logs interleave |
| 4 | `04_business_measurements.py` | Record the business function's inputs, result and duration |
| 5 | `05_sdk_measurements.py` | Observe the external call from our side |
| 6 | `06_manual_spans.py` | Give operations IDs, parent links, start times and durations |
| 7 | `07_opentelemetry.py` | Standard SDK plumbing and automatic SDK-call observation |
| 8 | `08_langsmith.py` | Use native LangSmith wrappers and annotations |

## 1. The application works

```sh
python 01_working_app.py
```

**Show:** `call_model()` and `answer_question()`, then the returned sentence.
There is no application log file for this step.

The OpenAI SDK is a client library. We give it outgoing arguments; it handles
the API interaction and returns a response object. Our application reads its
answer field. It has not recorded how execution unfolded.

**Ask:** “It answered. How would we investigate a complaint that it was slow?”

## 2. Add plain logs

```sh
python 02_plain_logs.py
```

**Show:** the terminal and `output/02_plain.log`. Follow:

```text
Request received
Calling model
Model response received
Returning answer
```

A **log** records something that happened. `logger.info()` statements are
already **instrumentation**: we added code that records runtime information.
Instrumentation does not start only when OpenTelemetry is installed.

We chose the messages. Timestamps help us inspect their order. These records do
not yet define explicit operations or parent relationships.

**Ask:** “What if two customers ask questions at the same time?”

## 3. Correlate concurrent requests

```sh
python 03_request_ids.py
```

**Show:** `ThreadPoolExecutor`, `LoggerAdapter`, then `output/03_requests.log`.
Two workers run three requests: **A/R101**, **B/R102**, **A/R103**. The same user
can make multiple requests; user ID is therefore not enough for correlation.
The exact interleaving varies, but the request identifiers stay consistent.

Filter the editor by `request=R101`, or run:

```sh
rg 'request=R101' output/03_requests.log
```

`LoggerAdapter` attaches the same fields to statements written through that
adapter. It does not automatically propagate fields through all code or SDK
logs. We supply these readable labels ourselves. They are correlation IDs,
not yet a collection of real tracing spans.

**Ask:** “We can group the messages. What information would help explain the work?”

## 4. Measure a business operation

```sh
python 04_business_measurements.py
```

**Show:** `calculate_refund()` and `output/04_business.log`:

```text
Refund calculated: paid=1200 fee=100 refund=1100 duration_ms=...
```

We own this function. We can choose to record its inputs, computed result and
elapsed time. `perf_counter()` measures elapsed time; the log timestamp answers
when the event occurred. The result is computed in Python, not guessed by the
model. The function's arithmetic is fast, so a displayed duration can round to
zero; that is not proof that no computation occurred.

This is **manual instrumentation**. Recording an amount does not enforce an
approval policy or prove the business rule itself is correct.

**Ask:** “Can we also observe the external model call, even though we don't own its servers?”

## 5. Measure the SDK call

```sh
python 05_sdk_measurements.py
```

**Show:** `call_model()` and `output/05_sdk.log`. It records the requested model,
duration, returned input/output token usage and an exception if the call fails.
Missing usage is reported as unknown, rather than zero.

| Information | Where it comes from |
| --- | --- |
| Requested model | Our outgoing arguments |
| Elapsed time | Our own timer around the SDK method |
| Exception | The SDK raises it to our application |
| Token usage | The provider's response, exposed by the SDK |

We observe our interaction with the provider. We cannot infer its internal GPU
scheduling from this client-side duration.

To show the error path predictably without making a paid failing request:

```sh
python 05_sdk_measurements.py --offline --fail
```

The local transport returns HTTP 503. The real SDK raises an error; our code
logs it and re-raises. The command exits with status 1. Inspect the error in
`output/05_sdk.log`. Retries are disabled in these examples to keep one SDK call
easy to interpret.

**Ask:** “We have measurements, but how do we represent which operation contained which other operation?”

## 6. Create traces and spans ourselves

```sh
python 06_manual_spans.py
```

**Show:** `output/06_manual.log` alongside `output/06_spans.jsonl`.

```text
answer_question                    root span
  calculate_refund                 child span
  call_model                       child span
```

A **span** records one operation over an interval. A **trace** connects the
spans for an execution. Here, one question creates one trace. A later question
creates another trace, even if it concerns the same customer/order.

Compare the JSON records:

- Their `trace_id` is the same.
- Every operation has a different `span_id`.
- Each child's `parent_span_id` points to the root.
- The root has no parent.
- Each record has its own start, duration, status and attributes.

Start with `answer_question()`, then read the `span()` context manager:

1. Read the active parent from `ContextVar`.
2. Reuse its trace ID, or create a root trace ID.
3. Assign a span ID, parent ID and start time.
4. Run the original operation inside `yield`.
5. Record an exception and propagate it.
6. In `finally`, write the completed span and restore the previous parent.

The logging filter adds the active IDs to our ordinary log records. Logs are
events, not automatically spans themselves. A span can contain many log events.
The file writes completed child spans before the completed root, so reconstruct
the hierarchy using IDs, not file order. Parent and child timings overlap; do
not sum them to calculate total request time.

Try an error:

```sh
python 06_manual_spans.py --offline --fail
```

The refund span succeeds; the SDK-call span and root fail. Context is restored
even on error. This small tracer is for teaching: it is not a distributed
tracing implementation, collector or observability backend.

**Ask:** “Do we want to maintain ID creation, context, error handling and exporters ourselves?”

## 7. Use OpenTelemetry

```sh
python 07_opentelemetry.py
```

**Show the setup in this order**, following the numbered comments:

| Code object | Its job in this example |
| --- | --- |
| `Resource` | Identify the service as `order-assistant` |
| `TracerProvider` | Own tracing configuration |
| `ConsoleSpanExporter` | Serialize completed spans to a file via `out=` |
| `SimpleSpanProcessor` | Pass completed spans to the exporter synchronously |
| `trace.set_tracer_provider(...)` | Register the tracing setup |
| `trace.get_tracer(...)` | Obtain the object used to create application spans |
| `OpenAIInstrumentor().instrument()` | Observe supported OpenAI SDK methods |
| `LoggingInstrumentor().instrument(...)` | Add current tracing IDs to log records |

Now show `call_model()`: it contains only the SDK call. The integration supplies
the SDK-call observation. Our explicit root and business spans remain.

Open `output/07_otel.log` and `output/07_otel_spans.jsonl`. Find:

- A root `answer_question` span and its refund child.
- An automatically created SDK-call child, with model/usage attributes supported
  by this integration and response.
- SDK-generated trace/span IDs and parent relationships.
- The service name in the resource.
- Matching trace IDs in ordinary logs.

The `Calling model` log is written **before** entering the instrumented SDK
method, so it carries the root's span ID. The automatic SDK span is visible in
the exported records. It does not require us to log from inside that wrapper.

```sh
python 07_opentelemetry.py --offline --fail
```

Inspect SDK/root error status and exception events. There is no hand-written
timer or usage-reading code in `call_model()` now. The SDK and integration do
not automatically understand our refund policy: we still add refund attributes.

OpenTelemetry is instrumentation and telemetry plumbing, not a visual trace
viewer. These examples export spans locally; they do not configure distributed
context propagation, a collector, log exporting or metric exporting. Another
exporter/backend can be introduced afterwards. The OpenAI integration can emit
metrics, but this example has not configured their collection/export.

Prompt/answer capture is not enabled by this example. Model/usage attributes
depend on supported responses; current integration conventions can evolve.
The pinned integration package is a beta release. Follow the
[OpenAI integration](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation-genai/openai.html)
and [logging integration](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/logging/logging.html)
documentation when changing versions. Our logging setup requests correlation
only; it disables the integration's additional logging-handler installation.
For the pinned logging integration, `set_logging_format=True` enables ID
injection. We then replace its default log handlers/format with our file and
terminal handlers. Newer documentation also describes `inject_trace_context`;
the example uses the option verified against the pinned version.

**Ask:** “What if we want a hosted AI trace viewer with less setup code?”

## 8. Native LangSmith tracing

Add `LANGSMITH_API_KEY` to **`session_1_monitoring/.env`**, then run:

```sh
python 08_langsmith.py
```

The script enables native tracing for this process. Open the printed LangSmith
project (default **`order-assistant-examples`**). Find `answer_question` with a
refund child and the wrapped model call. Compare durations, inputs, outputs and
usage. Its run ID is logged to `output/08_langsmith.log` for correlation. Each
successful hosted run is also stored in `output/langsmith_runs.sqlite3`, in the
`langsmith_runs` table, with its question, refund, answer, timestamp and
LangSmith run ID. If you pass `--output-dir`, the database is created there.

**Show:** `wrap_openai(...)` and the two `@traceable` annotations. The SDK wrapper
observes supported model calls; annotations capture the business function and
overall request. This is not an OpenTelemetry exporter path. Trace records and
captured inputs/outputs are sent to LangSmith when this step is enabled.

Setting environment variables alone would **not** instrument the bare SDK code
from step 1. This example installs the observation hooks with `wrap_openai` and
`@traceable`. With a framework that already supplies hooks, such as LangChain,
enabling native tracing can require less application code. See
[LangSmith custom instrumentation](https://docs.langchain.com/langsmith/annotate-code).

```sh
python 08_langsmith.py --offline
```

This only checks the annotated functions/wrapper locally. It explicitly disables
uploads and does **not** create a dashboard trace. A valid LangSmith key and
network access are required to verify the hosted result. `smith.flush()` finishes
sending queued records before this short script exits.

## Responsibilities to finish with

| Component | Responsibility |
| --- | --- |
| OpenAI SDK | Make a compatible API request and expose the response |
| Our log statements | Explain application/business events |
| Our manual span code | Build operation records ourselves in step 6 |
| OpenTelemetry SDK | Manage trace/span records and their export in step 7 |
| OpenAI OTel integration | Observe supported SDK calls |
| Logging integration | Attach active trace/span IDs to log records |
| Business instrumentation | Supply refund amounts and other domain facts |
| Native LangSmith hooks | Record annotated/wrapped work for LangSmith |

Observation code must exist somewhere. We can write it, enable an integration
that supplies it, or use a framework with existing hooks.

Operational telemetry does not replace evals or guardrails. A successful span
does not prove the refund policy is correct; a log warning does not prevent a
write. We have added no refund execution or approval workflow to these examples.

## Practical notes and checks

Each step replaces **its own** output files so the classroom view is clean.
Other steps' files and the kiosk's `kiosk.log` are untouched. Files are under
`output/`, independent of the terminal's working directory. No server or port is
needed. `--output-dir PATH` selects another location.

Do not share keys or real customer content in screenshots. The IDs and amounts
here are teaching values. Prompt/answer content may be captured by hosted tracing
in step 8. Tokens are reported usage, not a price estimate. These examples do not
look inside provider servers or compute cost.

Run all offline checks:

```sh
python -m unittest discover -s tests -v
```

The checks run each script in a fresh process, verify correlation, arithmetic,
usage, parent relationships, automatic SDK spans, and error recording. They use
temporary output directories, make no paid calls and do not upload traces.
