from openai import OpenAI
import os

c = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

for m in sorted(x.id for x in c.models.list().data):
    print(m)
