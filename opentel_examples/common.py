"""Shared credentials/CLI only. Each numbered file contains its own lesson code."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time
from dotenv import load_dotenv
import httpx
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
MODEL = os.getenv("OPEN_ROUTER_MODEL", "google/gemini-2.5-flash")
QUESTION = "A customer paid INR 1200. The cancellation fee is INR 100. Explain their refund in one sentence."


def options(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--question", default=QUESTION)
    parser.add_argument("--offline", action="store_true", help="Use an explicitly synthetic HTTP response; no network or paid calls")
    parser.add_argument("--fail", action="store_true", help="With --offline, return HTTP 503 to demonstrate error recording")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output")
    args = parser.parse_args()
    if args.fail and not args.offline:
        parser.error("--fail requires --offline; it injects a local HTTP failure")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.offline:
        print("OFFLINE: synthetic HTTP response through the real SDK; no provider call.")
    return args


def make_client(args):
    if args.offline:
        def respond(request):
            time.sleep(0.08)
            if args.fail:
                return httpx.Response(503, json={"error": {"message": "Local teaching failure", "type": "server_error"}})
            payload = json.loads(request.content)
            return httpx.Response(200, json={
                "id": "chatcmpl-offline-teaching", "object": "chat.completion", "created": int(time.time()),
                "model": payload["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Your refund is INR 1100 after the INR 100 cancellation fee."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 18, "total_tokens": 60}})
        return OpenAI(api_key="offline-placeholder", base_url="https://offline.example.invalid/v1",
                      http_client=httpx.Client(transport=httpx.MockTransport(respond)), max_retries=0)
    key = os.getenv("OPEN_ROUTER_API_KEY")
    if not key:
        raise ValueError("Set OPEN_ROUTER_API_KEY in session_1_monitoring/.env")
    return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1", timeout=45, max_retries=0)


def configure_logs(args, filename, correlated=False, custom_format=None):
    fmt = custom_format or ("%(asctime)s %(levelname)s " + (
        "user=%(user_id)s request=%(request_id)s " if correlated else "") + "%(message)s")
    logging.basicConfig(level=logging.INFO, format=fmt, force=True, handlers=[
        logging.FileHandler(args.output_dir / filename, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)])
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return logging.getLogger("order_assistant")


def run(main):
    try:
        main()
    except Exception as exc:
        print(f"Example stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
