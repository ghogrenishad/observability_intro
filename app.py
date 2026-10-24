"""Customer-facing Streamlit chat. All state changes go through the same API as Locust."""
import os
import requests
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

st.set_page_config(page_title="Corner Kiosk", page_icon="☕", layout="wide")


def load_streamlit_secrets():
    try:
        secrets = st.secrets
        for key in ("OPEN_ROUTER_API_KEY", "LANGSMITH_API_KEY", "KIOSK_TRACING",
                    "KIOSK_ENFORCE_LIMIT"):
            if key in secrets and key not in os.environ:
                os.environ[key] = str(secrets[key])
    except StreamlitSecretNotFoundError:
        pass


load_streamlit_secrets()

from config import API_PORT
from api import ensure_api_server

ensure_api_server(API_PORT)

st.markdown("""<style>
.stApp {background:#faf8f3; color:#24352c}
h1,h2,h3 {font-family:Georgia,serif;color:#24352c}
[data-testid="stSidebar"] {background:#edf0e7}
.stButton>button[kind="primary"] {background:#285943;border-color:#285943}
</style>""", unsafe_allow_html=True)
API = f"http://127.0.0.1:{API_PORT}"


def call(method, path, **kwargs):
    headers = {"Authorization": "Bearer " + st.session_state.token} if st.session_state.get("token") else {}
    try:
        response = requests.request(method, API + path, headers=headers, timeout=150, **kwargs)
        data = response.json()
    except requests.RequestException:
        st.error("The kiosk is unavailable. Please try again shortly.")
        return None
    if response.status_code != 200:
        st.error(data.get("error", "Something went wrong. Please try again."))
        if response.status_code == 401:
            st.session_state.pop("token", None)
        return None
    return data


st.caption("FRESHLY MADE · YOUR NEIGHBOURHOOD KIOSK")
st.title("A little break, made to order.")
signin_panel = st.empty()
if not st.session_state.get("token"):
    with signin_panel.container():
        st.write("Coffee, quick bites, and something refreshing. Sign in to start your order.")
        left, right = st.columns([1, 1])
        with left, st.form("signin"):
            st.subheader("Welcome to Corner Kiosk")
            name = st.text_input("Your name", key="signin_name")
            email = st.text_input("Email", key="signin_email")
            st.caption("Classroom demo: email-only sign-in. No password or real payment.")
            if st.form_submit_button("Start my order", type="primary"):
                login = call("POST", "/signin", json={"name": name, "email": email})
                if login:
                    st.session_state.token = login["access_token"]
                    st.session_state.customer = login["customer"]
                    st.session_state.messages = call("GET", "/history") or []
                    signin_panel.empty()
                    st.rerun()
        with right:
            st.subheader("On the menu")
            menu = call("GET", "/menu") or []
            for item in menu:
                st.markdown(f"**{item['name']}** · ₹{item['price_paise']/100:.0f}")
    st.stop()

with st.sidebar:
    st.subheader("Your kiosk")
    st.write("Hello, " + st.session_state.customer["name"])
    menu = call("GET", "/menu") or []
    for item in menu:
        st.write(f"{item['name']} · ₹{item['price_paise']/100:.0f}")
    st.divider()
    if st.button("Sign out"):
        call("POST", "/signout", json={})
        st.session_state.clear()
        st.rerun()

chat_column, order_column = st.columns([2, 1])
with chat_column:
    st.subheader("What can we make for you?")
    st.caption('Try “Show me the menu and add one cold coffee.”')
    for message in st.session_state.get("messages", []):
        with st.chat_message(message["role"]):
            st.write(message["content"])
    query = st.chat_input("Tell us what you’d like…")
    if query:
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.write(query)
        with st.chat_message("assistant"), st.spinner("Getting that ready…"):
            result = call("POST", "/chat", json={"query": query})
            if result:
                st.write(result["answer"])
                st.session_state.messages.append({"role": "assistant", "content": result["answer"]})

with order_column:
    st.subheader("Your order")
    order = call("GET", "/order")
    if order and order.get("items"):
        for item in order["items"]:
            st.write(f"{item['quantity']} × {item['product_name']}")
            st.caption(f"₹{item['quantity']*item['unit_price_paise']/100:.2f}")
        st.divider()
        st.metric("Total", f"₹{order['total_paise']/100:.2f}")
        confirmed = st.checkbox("I've reviewed my order")
        if st.button("Place order", type="primary", disabled=not confirmed):
            placed = call("POST", "/checkout", json={"order_id": order["order_id"]})
            if placed:
                st.session_state.placed = placed
                st.rerun()
        st.caption("Demo payment. No money is charged.")
    elif order is not None:
        st.write("Your order is empty. Add something through the chat.")
    if st.session_state.get("placed"):
        st.success("Order placed! We’re getting it ready.")
        st.caption("Order " + st.session_state.placed["order_id"][:8])
