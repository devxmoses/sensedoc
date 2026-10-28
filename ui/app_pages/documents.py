import pandas as pd
import streamlit as st

from client import get, preview_png, send, status_label

docs = get("/documents")
if not docs:
    st.info("No documents yet. Upload some first.", icon=":material/info:")
    st.page_link("app_pages/upload.py", label="Upload documents", icon=":material/upload_file:")
    st.stop()

table = pd.DataFrame(
    [
        {
            "id": d["id"],
            "file": d["filename"],
            "template": d["template_name"],
            "status": d["status"].replace("_", " "),
            "seconds": d["run"]["latency_ms"] / 1000 if d["run"] else None,
            "cost (USD)": d["run"]["cost_usd"] if d["run"] else None,
            "model": d["run"]["model"] if d["run"] else None,
        }
        for d in docs
    ]
)
selection = st.dataframe(
    table,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={"cost (USD)": st.column_config.NumberColumn(format="$%.4f")},
    alt="All uploaded documents with their status",
)

rows = selection.selection.rows
doc_id = int(table.iloc[rows[0]]["id"]) if rows else int(table.iloc[0]["id"])
doc = get(f"/documents/{doc_id}")

st.subheader(doc["filename"], anchor=False)
with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown(status_label(doc["status"]))
    if st.button("Process again", icon=":material/refresh:"):
        send("POST", f"/documents/{doc_id}/reprocess")
        st.rerun()
if doc["error"]:
    st.error(doc["error"], icon=":material/error:")

values = [v for v in doc.get("values") or [] if v["status"] != "superseded"]
left, right = st.columns([2, 3])

with right:
    picked = None
    if values:
        df = pd.DataFrame(
            [
                {
                    "field": v["field_path"],
                    "value": "" if v["value"] is None else str(v["value"]),
                    "confidence": v["confidence"],
                    "status": v["status"].replace("_", " "),
                    "page": v["page"],
                    "notes": "; ".join(v["issues"]),
                }
                for v in values
            ]
        )
        st.caption("Click a row to see where the value is on the page.")
        chosen = st.dataframe(
            df,
            hide_index=True,
            height=520,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                "page": st.column_config.NumberColumn(format="%d"),
                "notes": st.column_config.TextColumn(width="large"),
            },
            key=f"values-{doc_id}",
            alt="Extracted values with confidence",
        )
        if chosen.selection.rows:
            picked = values[chosen.selection.rows[0]]
        run = doc["run"]
        st.caption(
            f"{run['model']} · {run['latency_ms'] / 1000:.1f} s · {run['tokens_in']:,} tokens in, "
            f"{run['tokens_out']:,} out · ${run['cost_usd']:.4f} · attempts: {run['attempts']}"
        )

with left:
    page = 1
    if (doc["page_count"] or 1) > 1 and not (picked and picked["page"]):
        page = st.number_input("Page", min_value=1, max_value=doc["page_count"], value=1)
    png = preview_png(doc_id, page, picked["id"] if picked and picked["bbox"] else None)
    if png:
        st.image(png, alt=f"Page of {doc['filename']}")
        if picked and not picked["bbox"]:
            st.caption(f"Couldn't find where '{picked['value']}' is printed on the page.")
    else:
        st.caption("No preview for this file type.")
