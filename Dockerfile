FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Tesseract makes OCR work for scanned PDFs and photographed pages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Philippine time for the container's own clock and logs (the app itself
# uses TIME_ZONE in foodhub/settings.py).
ENV TZ=Asia/Manila

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# The AI model used by Similarity Check (Sentence-BERT, all-MiniLM-L6-v2) is
# downloaded here, once, so the running server never needs internet for it.
ENV ML_MODELS_DIR=/app/ml_models
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2', cache_dir='/app/ml_models')"
ENV HF_HUB_OFFLINE=1

COPY . .

RUN useradd --create-home appuser \
    && mkdir -p /app/media /app/staticfiles \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
CMD ["gunicorn", "foodhub.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
