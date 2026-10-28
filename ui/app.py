"""SenseDoc web app. Run from the project root:  uv run streamlit run ui/app.py"""

import streamlit as st

from client import require_api


def login_configured() -> bool:
    """Sign-in is on when .streamlit/secrets.toml has an [auth] section (see secrets.toml.example)."""
    try:
        return "auth" in st.secrets
    except Exception:  # no secrets file at all
        return False


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
            st.Page("app_pages/ask.py", title="Ask your documents", icon=":material/forum:"),
        ],
        "Set up": [
            st.Page("app_pages/templates.py", title="Templates", icon=":material/schema:"),
            st.Page("app_pages/catalogue.py", title="Product catalogue", icon=":material/inventory_2:"),
        ],
        "Insights": [
            st.Page("app_pages/metrics.py", title="Metrics", icon=":material/monitoring:"),
            st.Page("app_pages/label.py", title="Label for testing", icon=":material/verified:"),
        ],
    }
)

if login_configured() and not st.user.is_logged_in:
    st.title("SenseDoc", anchor=False)
    st.markdown("Sign in to upload, review and export documents.")
    st.button("Sign in", type="primary", icon=":material/login:", on_click=st.login)
    st.stop()

with st.sidebar:
    st.caption("SenseDoc · documents in, validated data out")
    if login_configured():
        st.caption(f"Signed in as {st.user.get('name') or st.user.get('email')}")
        st.button("Sign out", icon=":material/logout:", on_click=st.logout)
        st.session_state.setdefault("reviewer", st.user.get("email") or "reviewer")

require_api()
st.title(page.title, anchor=False)
page.run()
