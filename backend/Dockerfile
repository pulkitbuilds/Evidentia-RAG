FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app
RUN useradd -m -u 1000 appuser

COPY requirements.txt .
# CPU-only PyTorch keeps the image several GB smaller than the default CUDA build
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt

# Bake the embedding model into the image so cold starts don't re-download ~130MB
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY app ./app
RUN mkdir -p data && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860
# Hosts like Render/Railway inject $PORT; Hugging Face Spaces expects 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
