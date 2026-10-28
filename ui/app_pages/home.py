import streamlit as st

from client import get

st.markdown(
    "Turn invoices, receipts, price lists and photos into **validated, structured data**. "
    "Define the fields you want, upload files in bulk, and only check the values SenseDoc is unsure about."
)

m = get("/metrics")
docs = m["documents"]
with st.container(horizontal=True):
    st.metric("Documents processed", sum(docs.values()), border=True)
    st.metric("Waiting for review", docs.get("needs_review", 0), border=True)
    rate = m["auto_approved_rate"]
    st.metric("Values auto-approved", f"{rate:.0%}" if rate is not None else "–", border=True)
    latency = m["median_latency_ms"]
    st.metric("Median time per document", f"{latency / 1000:.1f} s" if latency else "–", border=True)

st.subheader("How it works", anchor=False)
steps = [
    (":material/schema:", "Define", "Pick a template or build your own: field names, types, required flags."),
    (":material/upload_file:", "Upload", "PDFs, scans, phone photos, Excel, CSV and Word, many at once."),
    (":material/auto_awesome:", "Extract", "Gemini returns exactly your fields; text is used when present, images otherwise."),
    (":material/fact_check:", "Validate", "Values are checked against the page, sums and required fields, then scored."),
    (":material/rate_review:", "Review", "Only uncertain values reach a person, shown beside the page."),
    (":material/download:", "Export", "CSV, Excel or JSON, ready for your spreadsheet or system."),
]
with st.container(horizontal=True):
    for icon, title, text in steps:
        with st.container(border=True, height="stretch"):
            st.markdown(f"#### {icon} {title}")
            st.caption(text)

st.subheader("Get started", anchor=False)
with st.container(horizontal=True):
    st.page_link("app_pages/upload.py", label="Upload documents", icon=":material/upload_file:")
    st.page_link("app_pages/review.py", label="Open the review queue", icon=":material/rate_review:")
    st.page_link("app_pages/templates.py", label="Build a template", icon=":material/schema:")
