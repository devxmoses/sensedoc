import streamlit as st

from client import send

st.caption(
    "Ask about your uploaded documents in plain language. Answers come only from your files, "
    "with the document and page cited. If the answer isn't there, SenseDoc says so."
)

if "chat" not in st.session_state:
    st.session_state.chat = []

with st.container(horizontal=True):
    for example in ("What is the total on invoice INV-2026-9313?", "Which shop sells Coke Zero 50cl?", "What are the payment terms?"):
        if st.button(example, icon=":material/lightbulb:"):
            st.session_state.pending = example


def show_answer(reply: dict) -> None:
    if reply["found"]:
        st.markdown(reply["answer"])
    else:
        st.markdown(f":orange[:material/search_off:] {reply['answer']}")
    for c in reply.get("citations", []):
        with st.expander(f"[{c['source']}] {c['filename']} · page {c['page']}", icon=":material/description:"):
            st.caption(c["snippet"])


for turn in st.session_state.chat:
    with st.chat_message(turn["role"]):
        if turn["role"] == "user":
            st.markdown(turn["text"])
        else:
            show_answer(turn["reply"])

question = st.chat_input("Ask a question about your documents") or st.session_state.pop("pending", None)
if question:
    st.session_state.chat.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching your documents..."):
            try:
                reply = send("POST", "/ask", json={"question": question})
            except RuntimeError as e:
                reply = {"found": False, "answer": f"Couldn't answer right now: {e}", "citations": []}
        show_answer(reply)
    st.session_state.chat.append({"role": "assistant", "reply": reply})

with st.sidebar:
    if st.button("Index older documents", icon=":material/manage_search:", help="Run once for files uploaded before the assistant existed."):
        st.toast(f"Indexed {send('POST', '/assistant/reindex')['documents_indexed']} documents")
