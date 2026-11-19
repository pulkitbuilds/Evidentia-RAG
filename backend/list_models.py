for gemini
from openai import OpenAI

c = OpenAI(api_key="", base_url="https://integrate.api.nvidia.com/v1")
for m in sorted(x.id for x in c.models.list().data):
    print(m)
