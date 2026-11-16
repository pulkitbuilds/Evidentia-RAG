for gemini
from openai import OpenAI

c = OpenAI(api_key="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", base_url="https://integrate.api.nvidia.com/v1")
for m in sorted(x.id for x in c.models.list().data):
    print(m)
