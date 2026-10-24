"""Email-only classroom sign-in, with server-side expiring sessions and history."""
import json
from secrets import token_urlsafe
import time
from langchain_core.messages import message_to_dict, messages_from_dict
from database import connect_db, find_or_create_customer


def sign_in(name, email):
    if not isinstance(name, str) or not name.strip() or not isinstance(email, str) or "@" not in email:
        raise ValueError("Enter your name and email.")
    customer = find_or_create_customer(name.strip(), email)
    token = token_urlsafe(32)
    with connect_db() as db:
        db.execute("DELETE FROM demo_sessions WHERE expires < ?", (time.time(),))
        db.execute("INSERT INTO demo_sessions VALUES (?,?,?)", (token, customer["customer_id"], time.time() + 3600))
    return {"access_token": token, "customer": customer}


def require_user(token):
    with connect_db() as db:
        row = db.execute("""SELECT c.* FROM customers c JOIN demo_sessions s
                            ON c.customer_id=s.customer_id WHERE s.token=? AND s.expires>?""",
                         (token, time.time())).fetchone()
    if not row:
        raise PermissionError("Please sign in again.")
    return dict(row)


def sign_out(token):
    with connect_db() as db:
        db.execute("DELETE FROM demo_sessions WHERE token=?", (token,))


def load_history(customer_id):
    with connect_db() as db:
        rows = db.execute("SELECT message FROM chat_history WHERE customer_id=? ORDER BY id", (customer_id,))
        return messages_from_dict([json.loads(row[0]) for row in rows])


def save_turn(customer_id, *messages):
    with connect_db() as db:
        for message in messages:
            db.execute("INSERT INTO chat_history(customer_id,message) VALUES (?,?)",
                       (customer_id, json.dumps(message_to_dict(message))))
