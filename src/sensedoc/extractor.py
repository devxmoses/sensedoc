"""Send a parsed documentt plus a template to the LLM and get validated data back."""

import base64
import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from sensedoc.readers import ParsedDocument
from sensedoc.schema_builder import Template, build_model

load_dotenv()

SYSTEM_PROMPT = (
    "You extract data from business documents into the fields requested. "
    "Only use information that appears in the document. "
    "If a field is not shown, return null. Never guess or fill gaps "
    "from general knowledge. Copy IDs and codes exactly as written."
)


def get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=os.environ["GEMINI_MODEL"], 
        temperature=0,
        timeout=60,
        max_retries=2,
    )

def build_messages(doc: ParsedDocument, template: Template) -> list:
    content = [{"type": "text", "text": f"Document type: {template.document_type}"}]

    if doc.text:
        content.append({"type": "text", "text": f"Document text:\n\n{doc.text}"})

    for image in doc.images:
        content.append(
            {
                "type": "image",
                "base64": base64.b64encode(image.data).decode(),
                "mime_type": image.mime_type,
            }
        )

    return [SystemMessage(SYSTEM_PROMPT), HumanMessage(content=content)]




def extract(doc:ParsedDocument, template: Template) -> BaseModel:
    schema = build_model("Extraction", template.fields)
    structured_llm = get_llm().with_structured_output(schema)
    return structured_llm.invoke(build_messages(doc, template))
