from dotenv import load_dotenv
from google import genai

load_dotenv()  

client = genai.Client()  # finds the key in the environment automatically

for model in client.models.list():
    # only show models that can generate text, not mbeddings, etc.)
    if "generateContent" in (model.supported_actions or []):
        print(model.name)
