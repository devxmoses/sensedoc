import pandas as pd
import streamlit as st

from client import get

m = get("/metrics")

st.subheader("Live usage", anchor=False)
with st.container(horizontal=True):
    rate = m["auto_approved_rate"]
    st.metric("Values auto-approved", f"{rate:.0%}" if rate is not None else "–", border=True)
    agree = m["reviewer_agreement"]
    st.metric(
        "Reviewer agreement",
        f"{agree:.0%}" if agree is not None else "–",
        help="Of the values a person checked, the share that were already correct.",
        border=True,
    )
    latency = m["median_latency_ms"]
    st.metric("Median time per document", f"{latency / 1000:.1f} s" if latency else "–", border=True)
    per_1000 = m["cost_per_1000_pages_usd"]
    st.metric("Cost per 1,000 pages", f"${per_1000:,.2f}" if per_1000 is not None else "–", border=True)

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Documents by status**")
        if m["documents"]:
            st.bar_chart(pd.Series(m["documents"], name="documents"), horizontal=True)
with right:
    with st.container(border=True):
        st.markdown("**Values by status**")
        if m["values"]:
            st.bar_chart(pd.Series(m["values"], name="values"), horizontal=True)

st.caption(
    f"Tokens: {m['tokens_in']:,} in / {m['tokens_out']:,} out · total cost ${m['cost_usd']:.4f} · "
    f"models used: {', '.join(f'{k} ({v})' for k, v in m['models'].items()) or '–'}"
)

st.subheader("Evaluation results", anchor=False)
evaluation = m.get("evaluation")
if not evaluation:
    st.info("Run `uv run python evaluation/run_eval.py` to measure accuracy on the labelled test set.", icon=":material/science:")
    st.stop()

st.caption(f"{evaluation['documents']} labelled documents · model {evaluation['model']} · run {evaluation['run_at'][:16]}")
summary = evaluation["summary"]
with st.container(horizontal=True):
    st.metric("Field accuracy", f"{summary['field_accuracy']:.0%}", border=True)
    st.metric("Accuracy of auto-approved values", f"{summary['auto_approved_accuracy']:.0%}", border=True)
    st.metric("Review rate", f"{summary['review_rate']:.0%}", border=True)
    st.metric("Variant accuracy (auto-approved)", f"{summary['variant_accuracy']:.0%}", border=True)

st.markdown("**Experiment 1: the same invoices as digital PDF (text) vs phone photo (vision)**")
st.dataframe(pd.DataFrame(evaluation["routes"]), hide_index=True, alt="Text route vs vision route")
st.markdown("**By document type**")
st.dataframe(pd.DataFrame(evaluation["by_type"]), hide_index=True, alt="Results by document type")
