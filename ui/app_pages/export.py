import pandas as pd
import streamlit as st

from client import get, http

templates = get("/templates")
by_label = {f"{t['name']} (v{t['version']})": t for t in templates}

with st.container(horizontal=True, vertical_alignment="bottom"):
    label = st.selectbox("Template", list(by_label))
    include_unreviewed = st.toggle(
        "Include documents still in review", help="Their uncertain values are left out either way."
    )

template_id = by_label[label]["id"]
params = {"include_unreviewed": include_unreviewed}
rows = http().get(f"/templates/{template_id}/export", params={**params, "format": "json"}).json()

if not rows:
    st.info("Nothing to export yet for this template.", icon=":material/info:")
    st.stop()

st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Data ready to export")
st.caption(f"{len(rows)} rows. One row per table line, with the document's header fields repeated.")

with st.container(horizontal=True):
    for fmt, icon in (("csv", ":material/csv:"), ("xlsx", ":material/table_view:"), ("json", ":material/data_object:")):
        response = http().get(f"/templates/{template_id}/export", params={**params, "format": fmt})
        st.download_button(
            f"Download {fmt.upper()}",
            data=response.content,
            file_name=f"sensedoc_{by_label[label]['name'].lower().replace(' ', '_')}.{fmt}",
            icon=icon,
        )
