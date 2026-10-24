"""Traffic only. The same /chat API is used by the Streamlit customer app."""
from itertools import cycle
import os
from uuid import uuid4
from locust import HttpUser, task, between

traffic = cycle(("normal", "normal", "normal", "slow", "wrong_tool", "over_limit"))


class Customer(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        response = self.client.post("/signin", json={"name": "Customer", "email": f"load-{uuid4().hex}@example.invalid"}, name="Sign in")
        response.raise_for_status()
        self.client.headers["Authorization"] = "Bearer " + response.json()["access_token"]

    @task
    def order(self):
        profile = "normal" if os.getenv("KIOSK_TRAFFIC") == "normal" else next(traffic)
        quantity = 10 if profile == "over_limit" else 1
        query = f"Show the menu, read my current order, then replace my draft with exactly {quantity} cold coffee(s)."
        with self.client.post("/chat", json={"query": query, "profile": profile}, name="Chat / order",
                              timeout=150, catch_response=True) as response:
            if response.status_code != 200:
                response.failure("Order request failed: HTTP " + str(response.status_code))
            elif response.elapsed.total_seconds() > 8:
                response.failure("Order exceeded eight-second response target")
            elif os.getenv("KIOSK_CHECK_EVALS", "0") == "1":
                if not all(response.json()["checks"].values()):
                    response.failure("HTTP succeeded, but tool/order checks failed")

    def on_stop(self):
        self.client.post("/signout", json={}, name="Sign out")
