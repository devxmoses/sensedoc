"""SenseDoc web app. Run from the project root:  uv run streamlit run ui/app.py"""

import streamlit as st

from client import require_api

st.set_page_config(page_title="SenseDoc", page_icon=":material/document_scanner:", layout="wide")

page = st.navigation(
    {
        "": [
            st.Page("app_pages/home.py", title="Overview", icon=":material/home:", default=True),
        ],
        "Work": [
            st.Page("app_pages/upload.py", title="Upload", icon=":material/upload_file:"),
            st.Page("app_pages/documents.py", title="Documents", icon=":material/description:"),
            st.Page("app_pages/review.py", title="Review queue", icon=":material/rate_review:"),
            st.Page("app_pages/export.py", title="Export", icon=":material/download:"),
        ],
        "Set up": [
            st.Page("app_pages/templates.py", title="Templates", icon=":material/schema:"),
            st.Page("app_pages/catalogue.py", title="Product catalogue", icon=":material/inventory_2:"),
        ],
        "Insights": [
            st.Page("app_pages/metrics.py", title="Metrics", icon=":material/monitoring:"),
        ],
    }
)

with st.sidebar:
    st.caption("SenseDoc · documents in, validated data out")

require_api()
st.title(page.title, anchor=False)
page.run()
