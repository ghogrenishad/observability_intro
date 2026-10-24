# Teaching order

1. **Logs exist because we write them.** Run `simple_chat.py`. Send one message.
   Open its `kiosk.log` lines, then the `log.info` statements that produced them.
   Ask what each timestamp, severity, request ID, message, duration and usage
   value tells us. These are real model calls; there is no replay mode here.
2. **Use the kiosk.** Sign in, chat, review the database-backed draft and place
   an order. Explain that saving a draft and placing/paying an order are distinct.
3. **“We are getting complaints. Let's test it.”** Start Locust with two users.
   Show normal requests first, then a timeout. Ask which operation consumed the
   time. Find the menu stall in raw logs. This introduces monitoring.
4. **“A successful operation can still be wrong.”** Compare requested and actual
   tool names. The deliberately broken dispatcher ran the order lookup instead
   of the menu lookup. Its database read succeeded, but fetched the wrong thing.
   Define the expected tool and check it: this introduces evals. Do not attribute
   this routing defect to model reasoning. The API includes a small `checks`
   object, not a comprehensive semantic or final-answer evaluator.
5. **“Detection doesn't prevent a write.”** Read ten-coffee tool arguments and
   the saved draft's `total_paise=120000`. Our demo limit is `50000`. Ask where to
   enforce it. Later enable the guard and verify the draft stays unchanged; this
   introduces guardrails. The ordinary stock and ownership guards stay enabled.
6. **Group one request by hand.** Search its `request=` ID. Mark its beginning,
   model calls, tool calls, database operations, answer and end. The whole
   execution is a trace; timed operations are spans; point-in-time messages are
   logs/events. Repeated calls need distinct span IDs. Parent IDs express nesting.
   A single order can link several request traces through `order_id`.
7. **Explain instrumentation.** Open `agent.py`, `tools.py` and
   `instrumentation.py`. `with span(...)` runs the original operation, times it,
   captures errors and restores the parent. It observes execution; it does not
   itself decide policy or make the model correct. Enable `KIOSK_TRACING=manual`.
   Inspect the same execution structure in `traces.jsonl`. Overlapping parent and
   child durations must not be summed.
8. **Standardize the plumbing.** Enable `KIOSK_TRACING=otel`. The SDK creates
   trace/span IDs, maintains context, handles exception status and exports spans
   to `otel-spans.jsonl`. This is OpenTelemetry instrumentation, not a tracing UI.
   Our example covers local tracing, not distributed context propagation or
   OpenTelemetry metric/log exporters. A collector/backend can come afterwards.

What else can instrumentation record?

| Kind | Useful fields |
| --- | --- |
| Request | ID, operation, latency, success/error, conversation/order ID |
| Model | Model name, call count, input/output tokens, latency, finish reason |
| Tools | Requested/executed name, arguments, result, latency, error, retry |
| Database | Read/write operation, latency, saved state, transaction outcome |
| Quality | Expected decision, tool-argument correctness, saved-state and answer checks |
| Policy | Rule, limit, approval requirement, allow/block outcome, enforcement point |
| Cost | Reported usage and actual applicable model pricing |
| Reproducibility | Prompt/model/deployment versions and evaluation case ID |

The current application records request IDs, model latency/usage, tool names and
arguments/results, saved orders and limit warnings. Instrumentation adds timing
and nesting for selected operations. Several fields above are possible additions,
not claims about features already implemented. Missing usage is unknown; do not
infer a zero-cost call. Tokens and latency are not measures of correctness.

Log deliberately: avoid API keys/auth headers and redact customer information
before sharing. Later discuss sampling, retention, metric aggregation and alerts.
Do not open a tracing platform before the students have a question that raw logs
make difficult to answer.
