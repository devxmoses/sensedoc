import streamlit as st

from client import get, preview_png, send

st.caption("Only values SenseDoc was unsure about land here. Approve them, or correct them while looking at the page.")

queue = get("/review-queue")
if not queue:
    st.success("Nothing to review. Every value is approved.", icon=":material/task_alt:")
    st.stop()

documents = {}
for item in queue:
    documents.setdefault(item["document_id"], {"filename": item["filename"], "items": []})["items"].append(item)

choice = st.selectbox(
    "Document",
    list(documents),
    format_func=lambda i: f"{documents[i]['filename']} · {len(documents[i]['items'])} to review",
)
reviewer = st.text_input("Your name", value=st.session_state.get("reviewer", "reviewer"), key="reviewer")

left, right = st.columns([2, 3])
with left:
    items = documents[choice]["items"]
    shown = st.selectbox(
        "Show on the page",
        range(len(items)),
        format_func=lambda i: items[i]["field_path"] + ("" if items[i]["bbox"] else "  (position unknown)"),
    )
    item = items[shown]
    png = preview_png(choice, item["page"] or 1, item["id"] if item["bbox"] else None)
    if png:
        st.image(png, alt=f"Page of {documents[choice]['filename']} with {item['field_path']} highlighted")
    else:
        st.caption("No preview for this file type.")

products = None
with right:
    for item in documents[choice]["items"]:
        is_sku = item["field_path"].endswith(".sku")
        with st.form(f"value-{item['id']}", border=True):
            st.markdown(f"**{item['field_path']}** · confidence {item['confidence']:.2f}")
            for issue in item["issues"]:
                st.caption(f":orange[:material/warning:] {issue}")

            if is_sku:
                if products is None:
                    products = {p["sku"]: p for p in get("/products")}
                candidates = [c["sku"] for c in item["candidate_skus"] or []]
                options = candidates + [s for s in products if s not in candidates]
                new_value = st.selectbox(
                    "Which product is it?",
                    options,
                    format_func=lambda s: f"{s} · {products[s]['brand']} {products[s]['type']} "
                    f"{products[s]['size_ml']:g}ml {products[s]['pack_type']} x{products[s]['pack_count']}"
                    + ("  (suggested)" if s in candidates else ""),
                )
                st.caption("Your choice is remembered: the same wording matches automatically next time.")
            else:
                current = "" if item["value"] is None else str(item["value"])
                new_value = st.text_input("Value", value=current)

            with st.container(horizontal=True):
                approve = st.form_submit_button("Approve", icon=":material/check:", disabled=is_sku and not item["value"])
                correct = st.form_submit_button("Save correction", type="primary", icon=":material/edit:")

        if approve or correct:
            try:
                send(
                    "PATCH",
                    f"/values/{item['id']}",
                    json={"action": "approve" if approve else "correct", "new_value": new_value, "reviewer": reviewer},
                )
                st.toast("Saved", icon=":material/check:")
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
