# observability_intro

Session 1 — Monitoring a kiosk application.

After cloning, copy `.env.example` to `.env` and add your own credentials.

For the eight standalone lessons from a working AI call through logging,
manual spans, OpenTelemetry and LangSmith, open
[opentel_examples/README.md](opentel_examples/README.md).

Open **this folder** for the whole class. It is self-contained application code:
its own Streamlit UI, HTTP API, tools, SQLite database, ordinary logs and load
test. Nothing imports or runs `assignment_solution/traffic_demo`. Credentials
load from **`.env` inside this folder**. You can open this folder in its own window.

From this folder:

Use **`ai-dev` with Python 3.12**. `requirements.txt` installs both the kiosk
and all eight `opentel_examples`, including their tested tracing integrations.

```sh
conda activate ai-dev
python -m pip install -r requirements.txt
```

To recreate the environment on another machine, run
`conda env create -f environment.yml`, then `conda activate ai-dev`.

## 1. Generate ordinary logs in a tiny AI app

```sh
streamlit run simple_chat.py
```

Send a message, then open `kiosk.log`. Show the actual `log.info(...)` calls in
`simple_chat.py`. A message triggers a model call, an answer, elapsed time and
reported token usage. No trace IDs, span IDs, replay answers or tracing service.
Stop this small app before starting the full kiosk on the same Streamlit port.

## 2. Run the application we built

```sh
python run.py
```

Open **http://localhost:8501**. Sign in with a name and email. Ask for the menu,
add a coffee, review the saved order and confirm **Place order**. This completes
a real SQLite order using demo payment; no money is charged and no email is sent.
Sign-in is email-only classroom identification, not real account verification.

The launcher always creates/appends `kiosk.log` before its model check. It prints
the full path, marks each startup and retains previous logs. Its database is
`kiosk.sqlite3` inside this folder, independent of all earlier databases.

## 3. Customers report problems. Test the application

Keep the app running. In a second terminal in this folder:

```sh
conda activate ai-dev
python -m locust -f load_testing/locustfile.py --host http://127.0.0.1:8090 --web-host 127.0.0.1
```

Open **http://localhost:8089**, enter **2 users**, spawn rate **1**, and start.
The first three load requests are ordinary orders. Later requests naturally mix
in the three complaints. Keep runs short: real model calls consume API credits.

In another terminal, or directly in the editor:

```sh
tail -f kiosk.log
```

| Complaint | Evidence to find | Meaning |
| --- | --- | --- |
| “My request hangs and fails.” | `Menu lookup stalled`, then `TimeoutError` after eight seconds | Monitoring: a real HTTP 504. The model's own time is logged separately. |
| “The wrong information came back.” | `Tool requested: get_menu` followed by `Calling tool: get_current_order` | Eval: wrong tool routing despite a successful tool execution. |
| “Why was such a large order accepted?” | `Order exceeds allowed limit`, then a saved ₹1,200 draft | Missing guardrail: the ₹500 demo rule was observed but not enforced. |

All intentional faults are in **`failures.py`**, for the instructor. There are
exactly three fault types. The wrong-tool fault changes application dispatch;
do not claim the model selected the wrong tool. No model answers are scripted.
The first two faults trigger when the agent requests the menu. The large-order
load request explicitly asks for ten coffees. A live model can still refuse a
request; inspect its actual behavior. Locust never confirms payment, so its
drafts do not consume stock.

These are not all HTTP errors. The timeout fails technically. A wrong tool or
forbidden draft may return HTTP 200. `KIOSK_CHECK_EVALS=1 locust ...` additionally
grades tool routing and saved-order limits if you want to show that distinction.

## 4. Raw logs are difficult to investigate

Use [SESSION.md](SESSION.md) as the teaching script. Start by searching the
`request=` ID to group one turn's messages. Identify model and tool operations
and their durations. Compare multiple customers' interleaved logs. Only then
name the request execution a **trace** and each timed operation a **span**.

One trace is one `/chat` turn; several turns can update the same `order_id`.
The initial run has tracing **off**. The `span(...)` hooks simply run their body.

## 5. Add instrumentation, then OpenTelemetry

Stop the application with Ctrl+C. Show `instrumentation.py` and the few
`with span(...)` calls in `agent.py`. Restart with manual tracing:

```sh
KIOSK_TRACING=manual python run.py
```

Continue the same UI/load test. Open `traces.jsonl`: request root, model calls,
tool/execute operations and database calls now have trace IDs, span IDs, parent
IDs, timings and outcomes. The response/request ID is a root attribute.

Now replace the hand-built recording with the OpenTelemetry SDK:

```sh
KIOSK_TRACING=otel python run.py
```

Open `otel-spans.jsonl`. The same instrumentation hooks now emit SDK spans,
including nested parent relationships and exception status. The file contains
one SDK span per line; it is exported telemetry, not the original application
log. OpenTelemetry collects/exports telemetry; a backend is needed to explore
timelines visually. No collector or hosted backend is required for this step.
See the [official Python instrumentation guide](https://opentelemetry.io/docs/languages/python/instrumentation/).

## 6. Prevent the write

Restart with the limit enforced, then repeat an oversized order:

```sh
KIOSK_ENFORCE_LIMIT=1 python run.py
```

The same request is rejected before the SQLite write, with HTTP 409 and an
empty/unchanged draft. The policy also applies before checkout. This check runs
inside the write transaction. Existing ownership, quantity and stock rules are
always enforced. The environment switch is instructor configuration; customers
cannot disable the guard in a request.

## Files to open during class

| File | Purpose |
| --- | --- |
| `simple_chat.py` | Start with log statements around one real model call |
| `app.py` | The customer-facing application |
| `api.py` | The backend both the UI and Locust call |
| `agent.py`, `tools.py`, `database.py` | Model → tool → saved state |
| `load_testing/locustfile.py` | Traffic, kept separate from the application |
| `kiosk.log` | Raw application logs |
| `instrumentation.py` | Manual tracing, then OpenTelemetry |
| `failures.py` | Instructor fault controls; no extra scenarios elsewhere |

Ports: UI **8501**, API **8090**, Locust **8089**. Stop earlier Locust processes
before starting this one. Old logs are retained, so use the latest startup marker
or `tail -f` to follow new execution. This local threaded/SQLite teaching app is
not intended for production authentication, large loads or concurrent turns by
the same customer. Keep real secrets and customer data out of shared screenshots.

Run offline checks:

```sh
python -m unittest discover -s tests -v
```

The additional localhost/Streamlit/Locust checks use a deterministic model stub
and temporary databases/logs, including a real eight-second stall. They never
append verification requests to the application's `kiosk.log`:

```sh
RUN_HTTP_CHECKS=1 python -m unittest discover -s tests -v
```
