"""Provided: notebook tools adapted to database abstraction and per-call identity.
Only private order actions resolve the user. Public menu actions need no login.
"""
from difflib import get_close_matches
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from models import NoInput, SearchInput, OrderInput, OrderItem
from database import read_menu, read_current_order, save_draft
from sessions import require_user
from instrumentation import span

@tool(args_schema=NoInput)
def get_menu():
    """Read active menu products, names, IDs, prices in paise and current stock."""
    with span("database.read_menu"):
        return read_menu()

@tool(args_schema=SearchInput)
def search_menu(query: str):
    """Find menu products by name, including minor typos. Ask if matches are ambiguous."""
    products = read_menu()
    names = [p["name"].lower() for p in products]
    matches = get_close_matches(query.lower(), names, n=3, cutoff=0.6)
    return [p for p in products if p["name"].lower() in matches]

@tool(args_schema=NoInput)
def get_current_order(config: RunnableConfig):
    """Read only the signed-in customer's saved current order."""
    user = require_user(config["configurable"]["token"])
    with span("database.read_current_order"):
        return read_current_order(user["customer_id"])

@tool(args_schema=OrderInput)
def set_order(items: list[OrderItem], config: RunnableConfig):
    """Replace the COMPLETE signed-in customer's draft selection.

    Read the current order first and preserve items the customer wants to keep.
    Ask for missing quantities. No payment is taken by this action.
    """
    user = require_user(config["configurable"]["token"])
    selection = [item.model_dump() for item in items]
    settings = config["configurable"]
    with span("database.save_draft"):
        return save_draft(user["customer_id"], selection,
                          validate_total=lambda total: settings["faults"].validate_total(total, settings["log"]))

tools = [get_menu, search_menu, get_current_order, set_order]
