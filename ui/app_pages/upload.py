import streamlit as st

from client import get, send, status_label

templates = get("/templates")
by_label = {f"{t['name']} (v{t['version']})": t for t in templates}

with st.form("upload", border=True):
    label = st.selectbox("Template", list(by_label))
    files = st.file_uploader(
        "Documents",
        type=["pdf", "png", "jpg", "jpeg", "webp", "xlsx", "csv", "docx"],
        accept_multiple_files=True,
        help="Up to 20 MB each. Scans and photos are read by the vision model.",
    )
    submitted = st.form_submit_button("Upload and extract", type="primary", icon=":material/rocket_launch:")

if submitted:
    if not files:
        st.warning("Add at least one file.")
    else:
        try:
            created = send(
                "POST",
                "/documents",
                data={"template_id": by_label[label]["id"]},
                files=[("files", (f.name, f.getvalue(), f.type)) for f in files],
            )
            st.session_state["just_uploaded"] = [d["id"] for d in created]
        except RuntimeError as e:
            st.error(str(e))

with st.expander("Ready-made demo files"):
    st.caption("Use the files in `samples/demo/`: an invoice PDF, an invoice photo, a receipt photo and two supermarket leaflets.")


@st.fragment(run_every=3)
def progress() -> None:
    ids = st.session_state.get("just_uploaded")
    if not ids:
        return
    docs = [get(f"/documents/{i}") for i in ids]
    st.subheader("Progress", anchor=False)
    for d in docs:
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{d['filename']}**")
            st.markdown(status_label(d["status"]))
            if d["run"]:
                st.caption(f"{d['run']['latency_ms'] / 1000:.1f} s · {d['run']['model']}")
            if d["error"]:
                st.caption(f":red[{d['error'][:200]}]")
    if all(d["status"] in ("done", "needs_review", "failed") for d in docs):
        st.success("All files processed.", icon=":material/check_circle:")
        with st.container(horizontal=True):
            st.page_link("app_pages/review.py", label="Review uncertain values", icon=":material/rate_review:")
            st.page_link("app_pages/documents.py", label="See all results", icon=":material/description:")


progress()
