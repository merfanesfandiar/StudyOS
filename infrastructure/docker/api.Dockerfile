FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv /opt/venv

WORKDIR /app

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY apps/api ./
COPY infrastructure/docker/api-entrypoint.sh /usr/local/bin/studyos-api-entrypoint

RUN chmod +x /usr/local/bin/studyos-api-entrypoint \
    && addgroup --system studyos \
    && adduser --system --ingroup studyos studyos \
    && mkdir -p /app/data/uploads \
    && chown -R studyos:studyos /app

USER studyos

EXPOSE 8000

ENTRYPOINT ["studyos-api-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
