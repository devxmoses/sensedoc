import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from sensedoc.extractor import extract
from sensedoc.readers import read_document
from sensedoc.schema_builder import Template

st.set_page_config(page_title="SenseDoc", layout="wide")
st.title("SenseDoc")
st.caption("Turn documents into structured data")

# ---------- 1. Pick a template ----------
template_files = sorted(Path("templates").glob("*.json"))
choice = st.selectbox("Template", template_files, format_func=lambda p: p.stem)
template = Template.model_validate_json(choice.read_text())

with st.expander("Fields in this template"):
    for field in template.fields:
        flag = " · required" if field.required else ""
        st.write(f"**{field.name}** · {field.type}{flag}")

# ---------- 2. Upload ----------
uploaded = st.file_uploader("Upload a document", type=["pdf", "png","jpg", "jpeg", "webp", "xlsx", "csv", "docx"])

# ---------- 3. Extract (only when the button is clicked) ----------
if uploaded and st.button("Extract", type="primary"):
    # our reader expects a file on disk, so save the upload to a temp file
    with tempfile.NamedTemporaryFile(suffix=Path(uploaded.name).suffix, delete=False) as tmp:
        tmp.write(uploaded.getvalue())

    with st.spinner("Reading the document..."):
        text = read_document(tmp.name)
        result = extract(text, template)

    Path(tmp.name).unlink()  # delete the temp file
    # remember the result so it survives the next rerun
    st.session_state["result"] = result.model_dump(mode="json")
    st.session_state["filename"] = Path(uploaded.name).stem

# ---------- 4. Show the result ----------
if "result" in st.session_state:
    data = st.session_state["result"]

    # split values: tables are lists of dicts, everything else is a single field
    tables = {k: v for k, v in data.items() if isinstance(v, list) and v and isinstance(v[0], dict)}
    fields = {k: v for k, v in data.items() if k not in tables}

    st.subheader("Fields")
    rows = [(k, "" if v is None else str(v)) for k, v in fields.items()]
    st.table(pd.DataFrame(rows, columns=["Field", "Value"]))

    for name, table_rows in tables.items():
        st.subheader(name.replace("_", " ").title())
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)

    st.download_button(
        "Download JSON",
        data=pd.Series(data).to_json(indent=2),
        file_name=f"{st.session_state['filename']}.json",
    )
