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

left, right = st.columns([2, 3])
with left:
    png = preview_png(doc_id)
    if png:
        st.image(png, alt=f"Page 1 of {doc['filename']}")
    else:
        st.caption("No preview for this file type.")

with right:
    values = doc.get("values") or []
    if values:
        df = pd.DataFrame(
            [
                {
                    "field": v["field_path"],
                    "value": "" if v["value"] is None else str(v["value"]),
                    "confidence": v["confidence"],
                    "status": v["status"].replace("_", " "),
                    "notes": "; ".join(v["issues"]),
                }
                for v in values
                if v["status"] != "superseded"
            ]
        )
        st.dataframe(
            df,
            hide_index=True,
            height=520,
            column_config={
                "confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                "notes": st.column_config.TextColumn(width="large"),
            },
            alt="Extracted values with confidence",
        )
        run = doc["run"]
        st.caption(
            f"{run['model']} · {run['latency_ms'] / 1000:.1f} s · {run['tokens_in']:,} tokens in, "
            f"{run['tokens_out']:,} out · ${run['cost_usd']:.4f} · attempts: {run['attempts']}"
        )
