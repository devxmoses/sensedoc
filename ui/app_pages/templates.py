import json

import pandas as pd
import streamlit as st

from client import get, send

TYPES = ["text", "number", "date", "currency", "list", "table"]
FIELD_COLUMNS = {
    "type": st.column_config.SelectboxColumn(options=TYPES, required=True, default="text"),
    "required": st.column_config.CheckboxColumn(default=False),
    "description": st.column_config.TextColumn(width="large", help="The model reads this. Be specific."),
    "examples": st.column_config.TextColumn(help="Comma-separated"),
}

templates = get("/templates")
by_label = {f"{t['name']} (v{t['version']})": t for t in templates}

mode = st.segmented_control("Mode", ["View", "Edit", "Create new"], default="View", label_visibility="collapsed")
mode = mode or "View"

base = None
if mode != "Create new":
    label = st.selectbox("Template", list(by_label))
    base = by_label[label]


def fields_frame(fields: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": f["name"],
                "type": f["type"],
                "required": f["required"],
                "description": f["description"],
                "examples": ", ".join(f["examples"]),
            }
            for f in fields
        ],
        columns=["name", "type", "required", "description", "examples"],
    )


def frame_to_fields(df: pd.DataFrame) -> list[dict]:
    out = []
    for row in df.to_dict("records"):
        if not row.get("name"):
            continue
        out.append(
            {
                "name": row["name"],
                "type": row.get("type") or "text",
                "required": bool(row.get("required")),
                "description": row.get("description") or "",
                "examples": [e.strip() for e in str(row.get("examples") or "").split(",") if e.strip()],
            }
        )
    return out


if mode == "View":
    t = base["template"]
    st.caption(f"Document type: {t['document_type']} · version {base['version']}")
    st.dataframe(fields_frame(t["fields"]), hide_index=True, alt="Template fields")
    for f in t["fields"]:
        if f["type"] == "table":
            st.markdown(f"**Columns of {f['name']}**")
            st.dataframe(fields_frame(f["columns"]), hide_index=True, alt=f"Columns of {f['name']}")
    if t["rules"]:
        st.markdown("**Validation rules**")
        for r in t["rules"]:
            if r["type"] == "table_sum":
                st.markdown(f"- {r['table']} › {r['column']} must add up to **{r['target']}**")
            else:
                st.markdown(f"- {' + '.join(r['fields'])} must equal **{r['target']}**")
    if t.get("product_table"):
        st.markdown(f"**Product matching:** rows of *{t['product_table']}* are matched to the SKU catalogue.")
    st.stop()

# ---------- Edit or create ----------
start = base["template"] if base else {"name": "", "document_type": "", "fields": [], "rules": [], "product_table": None}
key = f"builder-{base['id'] if base else 'new'}"

with st.container(horizontal=True):
    name = st.text_input("Template name", value=start["name"], disabled=mode == "Edit", key=f"{key}-name")
    document_type = st.text_input("Document type", value=start["document_type"], key=f"{key}-type")

st.markdown("**Fields**")
fields_df = st.data_editor(
    fields_frame(start["fields"]),
    num_rows="dynamic",
    hide_index=True,
    column_config=FIELD_COLUMNS,
    key=f"{key}-fields",
)
fields = frame_to_fields(fields_df)

old_columns = {f["name"]: f["columns"] for f in start["fields"] if f["type"] == "table"}
for f in fields:
    if f["type"] == "table":
        st.markdown(f"**Columns of {f['name']}**")
        columns_df = st.data_editor(
            fields_frame(old_columns.get(f["name"], [])),
            num_rows="dynamic",
            hide_index=True,
            column_config={**FIELD_COLUMNS, "type": st.column_config.SelectboxColumn(options=TYPES[:-1], default="text")},
            key=f"{key}-columns-{f['name']}",
        )
        f["columns"] = frame_to_fields(columns_df)

table_names = [f["name"] for f in fields if f["type"] == "table"]
with st.expander("Advanced: validation rules and product matching"):
    rules_text = st.text_area("Rules (JSON)", value=json.dumps(start["rules"], indent=2), height=180, key=f"{key}-rules")
    product_table = st.selectbox(
        "Match rows of this table to the product catalogue",
        [None, *table_names],
        index=([None, *table_names].index(start["product_table"]) if start.get("product_table") in table_names else 0),
        format_func=lambda x: "No product matching" if x is None else x,
        key=f"{key}-product",
    )

if st.button("Save as new version" if mode == "Edit" else "Create template", type="primary", icon=":material/save:"):
    try:
        body = {
            "name": name,
            "document_type": document_type,
            "fields": fields,
            "rules": json.loads(rules_text or "[]"),
            "product_table": product_table,
        }
        if mode == "Edit":
            saved = send("PUT", f"/templates/{base['id']}", json=body)
        else:
            saved = send("POST", "/templates", json=body)
        st.success(f"Saved {saved['name']} version {saved['version']}.", icon=":material/check_circle:")
    except (RuntimeError, json.JSONDecodeError) as e:
        st.error(f"Could not save: {e}")
