# syntax=docker/dockerfile:1
# Imagem da API. Segurança (ver docs/seguranca/privacidade.md e docs/servidor.md):
# * dependências SÓ do requirements.lock, com hash conferido (--require-hashes) — nada resolvido no build;
# * duas etapas: a final não tem pip/compilador do build, só o venv pronto + o código;
# * roda como usuário sem privilégio (uid 10001), código de root e só leitura, core dump desligado;
# * nenhum segredo no build (eles entram por variável de ambiente na hora de rodar).
# Base fixada por digest (python:3.12-slim). Atualize o digest junto com o lock.
ARG BASE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

FROM ${BASE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.lock /tmp/requirements.lock
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes --no-deps -r /tmp/requirements.lock \
 && /opt/venv/bin/pip uninstall -y pip \
 && find /opt/venv -name '__pycache__' -prune -exec rm -rf {} +
COPY sigaa /app/sigaa
COPY api /app/api
# bytecode pronto: com o sistema de arquivos só-leitura o Python não consegue gravar .pyc depois
RUN python -m compileall -q /opt/venv /app

FROM ${BASE}
# FORWARDED_ALLOW_IPS: quem pode mandar X-Forwarded-For/-Proto (o proxy reverso). Padrão: só o próprio
# contêiner. Atrás de proxy, ponha o IP/rede DELE (nunca "*" com a porta exposta direto). Ver docs/servidor.md.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app PATH=/opt/venv/bin:$PATH \
    FORWARDED_ALLOW_IPS=127.0.0.1
RUN useradd --system --uid 10001 --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin api
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
WORKDIR /app
USER 10001:10001
EXPOSE 8000
# vivo = o processo responde (não consulta o SIGAA: isso é o /v1/status)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/', timeout=4)"]
# 1 processo de API (as sessões ficam em memória — ver docs/servidor.md) + o pool de parse,
# que usa os outros núcleos (SIGAA_PARSE_PROCESSOS; padrão núcleos-1, de 1 a 8).
# uvloop + httptools explícitos. --no-server-header: não anuncia "uvicorn" na resposta.
# ulimit -c 0: core dump teria senha/token/dado de aluno da memória.
CMD ["sh", "-c", "ulimit -c 0 && exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --no-server-header --loop uvloop --http httptools --backlog 4096 --timeout-keep-alive 30"]
