FROM python:3.12-slim AS runtime

ARG SERVICE
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY shared ./shared
COPY services/${SERVICE}/app ./service

RUN addgroup --system axsentinel \
    && adduser --system --ingroup axsentinel --uid 10001 axsentinel \
    && chown -R axsentinel:axsentinel /app

USER 10001
EXPOSE 8080

CMD ["sh", "-c", "uvicorn service.main:app --host 0.0.0.0 --port ${PORT}"]
