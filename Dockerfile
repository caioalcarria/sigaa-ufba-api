FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY sigaa ./sigaa
COPY api ./api
RUN pip install --no-cache-dir ".[api]"
EXPOSE 8000
# 1 processo de API (as sessões ficam em memória — ver docs/servidor.md) + o pool de parse,
# que usa os outros núcleos (SIGAA_PARSE_PROCESSOS; padrão núcleos-1, de 1 a 8).
# uvloop + httptools explícitos (o uvicorn[standard] já escolheria os dois).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "--loop", "uvloop", "--http", "httptools", "--backlog", "4096", "--timeout-keep-alive", "30"]
