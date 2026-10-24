"""First exercise: a tiny real AI application that writes ordinary logs."""
import time
from uuid import uuid4
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from agent import get_model
from logging_setup import request_logger

st.set_page_config(page_title="Simple AI chat", page_icon="💬")
st.title("Simple AI chat")
st.caption("Start here: one message, one model call, ordinary Python logs.")
if "messages" not in st.session_state:
    st.session_state.messages = []
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])
query = st.chat_input("Ask something")
if query:
    log = request_logger(str(uuid4()))
    log.info("User message: %r", query)
    messages = [HumanMessage(content=m["content"]) if m["role"] == "user" else AIMessage(content=m["content"])
                for m in st.session_state.messages]
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.write(query)
    tick = time.perf_counter()
    try:
        log.info("Calling model")
        response = get_model().invoke(messages + [HumanMessage(content=query)])
        log.info("Model returned: elapsed_ms=%.2f usage=%s", (time.perf_counter()-tick)*1000, response.usage_metadata)
        log.info("Assistant answer: %r", response.content)
        st.session_state.messages.append({"role": "assistant", "content": response.content})
        with st.chat_message("assistant"):
            st.write(response.content)
    except Exception as exc:
        log.error("Model failed: error=%s elapsed_ms=%.2f", type(exc).__name__, (time.perf_counter()-tick)*1000)
        st.error("The model request failed. Check kiosk.log.")
