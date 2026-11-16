import os
from openai import OpenAI

c = OpenAI(
    api_key=os.environ["AQ.Ab8RN6JMxT2Uog9zI_Sl3rJKL6H6UQguSHRT2OI018B3l8LAKg"],
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)
for m in sorted(x.id for x in c.models.list().data):
    print(m)
