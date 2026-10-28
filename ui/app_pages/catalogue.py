import pandas as pd
import streamlit as st

from client import get, send

st.caption(
    "Every priced product line is matched to exactly one SKU here. If more than one SKU could fit, "
    "the line goes to review. SenseDoc never guesses."
)

products = get("/products")
df = pd.DataFrame(products)
if not df.empty:
    df["brand_aliases"] = df["brand_aliases"].map(", ".join)
    df["aliases"] = df["aliases"].map(", ".join)
    df = df.rename(columns={"aliases": "learned aliases"})
st.dataframe(
    df,
    hide_index=True,
    column_config={"size_ml": st.column_config.NumberColumn("size (ml)", format="%d")},
    alt="Product catalogue",
)
st.caption("Learned aliases come from reviewer corrections, so the same leaflet wording matches automatically next time.")

with st.form("import", border=True):
    st.markdown("**Import or update products**")
    st.caption("CSV columns: sku, brand, type, size_ml, pack_type, pack_count, brand_aliases (separated by ;)")
    file = st.file_uploader("Catalogue CSV", type=["csv"])
    if st.form_submit_button("Import", icon=":material/upload:") and file:
        result = send("POST", "/products/import", files={"file": (file.name, file.getvalue(), "text/csv")})
        st.success(f"Imported {result['imported']} products.")
