import pandas as pd
import streamlit as st

from client import get, preview_png, send

st.caption(
    "Turn real documents into test data. Check every value against the page, fix the wrong ones, and save. "
    "Your corrections are recorded as reviews, and the verified answer joins the real evaluation set."
)

labels = get("/labels")
labelled = {label["document_id"] for label in labels}
docs = [d for d in get("/documents") if d["run"] and d["status"] in ("done", "needs_review")]

with st.container(horizontal=True):
    st.metric("Labelled documents", len(labels), border=True)
    st.metric("Processed, not yet labelled", len([d for d in docs if d["id"] not in labelled]), border=True)

if not docs:
    st.info("Upload and process some real documents first.", icon=":material/info:")
    st.page_link("app_pages/upload.py", label="Upload documents", icon=":material/upload_file:")
    st.stop()

doc_id = st.selectbox(
    "Document",
    [d["id"] for d in docs],
    format_func=lambda i: next(
        f"{d['filename']} · {d['template_name']}" + ("  ✓ labelled" if i in labelled else "") for d in docs if d["id"] == i
    ),
)
doc = get(f"/documents/{doc_id}")
values = [v for v in doc["values"] if v["status"] != "superseded"]

left, right = st.columns([2, 3])
with left:
    png = preview_png(doc_id)
    if png:
        st.image(png, alt=f"Page 1 of {doc['filename']}")
    else:
        st.caption("No preview for this file type. Open the original file to compare.")

with right:
    original = pd.DataFrame(
        [
            {
                "id": v["id"],
                "field": v["field_path"],
                "value": "" if v["value"] is None else str(v["value"]),
                "status": v["status"].replace("_", " "),
            }
            for v in values
        ]
    )
    edited = st.data_editor(
        original,
        hide_index=True,
        height=520,
        disabled=["id", "field", "status"],
        column_config={"id": None, "value": st.column_config.TextColumn("value (edit if wrong)", width="large")},
        key=f"label-{doc_id}",
    )
    name = st.text_input("Your name", value=st.session_state.get("reviewer", "reviewer"), key="labeller")

    if st.button("Save as test label", type="primary", icon=":material/verified:"):
        try:
            changed = 0
            for before, after in zip(original.to_dict("records"), edited.to_dict("records")):
                if after["value"] != before["value"]:
                    send("PATCH", f"/values/{before['id']}", json={"action": "correct", "new_value": after["value"], "reviewer": name})
                    changed += 1
                elif before["status"] == "needs review":
                    send("PATCH", f"/values/{before['id']}", json={"action": "approve", "reviewer": name})
            send("POST", f"/documents/{doc_id}/label", json={"labelled_by": name})
            st.success(f"Saved. {changed} value(s) corrected.", icon=":material/verified:")
        except RuntimeError as e:
            st.error(str(e))

st.divider()
st.markdown("**Measure accuracy on your labelled documents**")
st.code("uv run python evaluation/export_labels.py\nEVAL_SET=real uv run python evaluation/run_eval.py", language="bash")
