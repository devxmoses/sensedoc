import json
from pathlib import Path

from sensedoc.extractor import extract
from sensedoc.readers import read_document
from sensedoc.schema_builder import Template, build_model

# 1. Load the template. Pydantic checks the template itself, too.
template = Template.model_validate_json(Path("templates/invoice.json").read_text())

# 2. Peek at the schema that gets generated and sent to the LLM
schema = build_model("Extraction", template.fields)
print("----- GENERATED SCHEMA -----")
print(json.dumps(schema.model_json_schema(), indent=2))

# 3. Extract
text = read_document("samples/invoice_001.pdf")
result = extract(text, template)

print("----- EXTRACTED -----")
print(result.model_dump_json(indent=2))
