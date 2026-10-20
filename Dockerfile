FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY sigaa ./sigaa
COPY api ./api
RUN pip install --no-cache-dir ".[api]"
EXPOSE 8000
# 1 worker: as sessões ficam em memória (ver README › Sessões)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
