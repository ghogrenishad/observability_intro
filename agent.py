"""The kiosk's model/tool loop, with ordinary application logs."""
from functools import lru_cache
from contextlib import nullcontext
import json
import os
import time
from uuid import uuid4
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langsmith import trace
from langsmith.utils import tracing_is_enabled
from config import ROOT
from database import read_current_order
from sessions import require_user, load_history, save_turn
from tools import tools
from failures import Failures
from instrumentation import span
from logging_setup import request_logger


@lru_cache(maxsize=1)
def get_model():
    if not os.getenv("OPEN_ROUTER_API_KEY"):
        raise ValueError("Set OPEN_ROUTER_API_KEY in session_1_monitoring/.env")
    return ChatOpenAI(model="google/gemini-2.5-flash", api_key=os.environ["OPEN_ROUTER_API_KEY"],
                      base_url="https://openrouter.ai/api/v1", temperature=0, timeout=45, max_retries=1)


prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a friendly kiosk ordering assistant.
Use tools for real menu and saved order information. Ask for missing quantities.
Read the current order before edits; set_order replaces the complete selection.
100 paise = INR 1. Never invent data or claim success after a failed tool result.
You can access only the signed-in customer's order. Chat cannot change identity.
Payment is handled separately by the application. Saving a draft does not place or pay for it."""),
    MessagesPlaceholder("history"), ("human", "{query}")])
tool_repo = {tool.name: tool for tool in tools}


def chat(query, token, profile=None):
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ValueError("Enter a message of 1–4000 characters.")
    user = require_user(token)
    request_id = str(uuid4())
    log = request_logger(request_id)
    faults = Failures(profile)
    config = {"configurable": {"token": token, "faults": faults, "log": log}}
    started = time.perf_counter()
    log.info("Message received: %s", json.dumps(query))
    # LangChain automatically traces its calls; this parent connects the calls
    # made by our plain Python loop into one chat-request trace. Never trace token.
    parent = (trace("kiosk.chat", inputs={"query": query},
                    metadata={"request_id": request_id})
              if tracing_is_enabled() else nullcontext())
    with parent as root, span("chat", request_id=request_id):
        try:
            messages = prompt.invoke({"query": query, "history": load_history(user["customer_id"])}).to_messages()
            llm = get_model().bind_tools(tools)
            for _ in range(10):
                log.info("Calling model")
                tick = time.perf_counter()
                with span("model.invoke", model="google/gemini-2.5-flash") as detail:
                    response = llm.invoke(messages)
                    detail["usage"] = response.usage_metadata or {}
                log.info("Model returned: elapsed_ms=%.2f tool_calls=%s usage=%s",
                         (time.perf_counter() - tick) * 1000, len(response.tool_calls), json.dumps(detail["usage"]))
                if not response.tool_calls:
                    break
                messages.append(response)
                for call in response.tool_calls:
                    requested, arguments = call["name"], call["args"]
                    log.info("Tool requested: %s arguments=%s", requested, json.dumps(arguments))
                    tick = time.perf_counter()
                    with span("tool." + requested, arguments=arguments):
                        def execute(actual, actual_args):
                            log.info("Calling tool: %s arguments=%s", actual, json.dumps(actual_args))
                            with span("execute." + actual):
                                return tool_repo[actual].invoke(actual_args, config=config)
                        result = faults.dispatch(requested, arguments, execute, log)
                    log.info("Tool returned: requested=%s elapsed_ms=%.2f result=%s", requested,
                             (time.perf_counter() - tick) * 1000, json.dumps(result))
                    messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"]))
            else:
                raise RuntimeError("Agent exceeded ten model calls")
            with span("database.read_saved_order"):
                order = read_current_order(user["customer_id"])
            log.info("Saved order: %s", json.dumps(order))
            log.info("Assistant answer: %s", json.dumps(response.content))
            tool_pass = all(c["requested"] == c["actual"] for c in faults.calls)
            state_pass = order.get("total_paise", 0) <= 50000
            save_turn(user["customer_id"], HumanMessage(content=query), response)
            if root is not None:
                root.outputs = {"answer": response.content, "request_id": request_id,
                                "saved_order": {key: order.get(key) for key in
                                                ("items", "total_paise", "status", "payment_status")}}
            log.info("Request completed: elapsed_ms=%.2f", (time.perf_counter() - started) * 1000)
            return {"request_id": request_id, "answer": response.content, "order": order,
                    "checks": {"tool_selection_pass": tool_pass, "order_limit_pass": state_pass}}
        except Exception as exc:
            log.error("Request failed: error=%s elapsed_ms=%.2f", type(exc).__name__,
                      (time.perf_counter() - started) * 1000)
            raise
