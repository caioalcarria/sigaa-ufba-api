"""Configuração por variáveis de ambiente (todas opcionais)."""

from __future__ import annotations

import os


def _bool(nome: str, padrao: bool) -> bool:
    v = os.getenv(nome)
    return padrao if v is None else v.strip().lower() in ("1", "true", "sim", "yes", "on")


def _num(nome: str, padrao: float) -> float:
    v = os.getenv(nome)
    try:
        return float(v) if v else padrao
    except ValueError:
        return padrao


class Config:
    #: endereço do SIGAA (troque pra usar com outra instituição que roda SIGAA)
    SIGAA_URL: str = os.getenv("SIGAA_URL", "https://sigaa.ufba.br")
    #: vida máxima de um token da API (horas)
    TOKEN_TTL_HORAS: float = _num("SIGAA_API_TOKEN_TTL_HORAS", 12)
    #: token sem uso por mais que isso é descartado (minutos)
    TOKEN_OCIOSO_MIN: float = _num("SIGAA_API_TOKEN_OCIOSO_MIN", 120)
    #: manter a sessão do SIGAA viva enquanto o token estiver em uso recente
    KEEPALIVE: bool = _bool("SIGAA_API_KEEPALIVE", True)
    #: intervalo do keep-alive (minutos) — o SIGAA derruba a sessão com ~30 min sem uso
    KEEPALIVE_MIN: float = _num("SIGAA_API_KEEPALIVE_MIN", 10)
    #: só mantém viva a sessão usada nos últimos N minutos
    KEEPALIVE_JANELA_MIN: float = _num("SIGAA_API_KEEPALIVE_JANELA_MIN", 60)
    #: permitir "lembrar" (guardar a senha cifrada em memória pra relogar sozinho)
    PERMITIR_LEMBRAR: bool = _bool("SIGAA_API_PERMITIR_LEMBRAR", True)
    #: aceitar Authorization: Basic usuario:senha (cria/reaproveita sessão por credencial)
    PERMITIR_BASIC: bool = _bool("SIGAA_API_PERMITIR_BASIC", True)
    #: limites de sessões
    MAX_SESSOES: int = int(_num("SIGAA_API_MAX_SESSOES", 500))
    MAX_SESSOES_POR_USUARIO: int = int(_num("SIGAA_API_MAX_SESSOES_POR_USUARIO", 5))
    #: tentativas de login por IP numa janela de 10 min (anti força-bruta)
    MAX_LOGINS_POR_IP: int = int(_num("SIGAA_API_MAX_LOGINS_POR_IP", 20))
    # ---- pool de sessões SIGAA por aluno (navegação em paralelo) ----
    #: máximo de sessões SIGAA (JSESSIONIDs) simultâneas por token. 1 = sem paralelismo (como antes).
    POOL_MAX: int = int(_num("SIGAA_API_POOL_MAX", 4))
    #: quantas sessões deixar prontas logo após o login (abertas em segundo plano; inclui a do login)
    POOL_AQUECER: int = int(_num("SIGAA_API_POOL_AQUECER", 2))
    #: no paralelo, só abre sessão nova se houver ao menos N fluxos na fila por sessão nova
    POOL_TAREFAS_POR_SESSAO: int = int(_num("SIGAA_API_POOL_TAREFAS_POR_SESSAO", 2))
    #: quantas navegações a página do portal/turmas.jsf pode ser reaproveitada antes de ser baixada de
    #: novo (o MyFaces do SIGAA UFBA guarda as 10 últimas views da sessão: uma página sobrevive a 9
    #: navegações e morre na 10ª; 8 deixa margem). 0 = sempre baixa (comportamento antigo).
    REUSAR_VIEWS: int = int(_num("SIGAA_API_REUSAR_VIEWS", 8))
    #: intervalo mínimo entre requisições de UMA sessão (segundos)
    MIN_INTERVALO: float = _num("SIGAA_API_MIN_INTERVALO", 0.25)
    #: teto GLOBAL de requisições simultâneas ao SIGAA (todas as sessões de todos os alunos)
    MAX_CONCORRENCIA_SIGAA: int = int(_num("SIGAA_API_MAX_CONCORRENCIA_SIGAA", 64))
    #: conexões HTTP keep-alive compartilhadas entre as sessões
    MAX_CONEXOES: int = int(_num("SIGAA_API_MAX_CONEXOES", 128))
    #: negociar HTTP/2 com o SIGAA (o da UFBA só fala HTTP/1.1; deixe false)
    HTTP2: bool = _bool("SIGAA_API_HTTP2", False)
    #: origens liberadas no CORS (vírgula). "*" libera tudo.
    CORS: list[str] = [o.strip() for o in os.getenv("SIGAA_API_CORS", "*").split(",") if o.strip()]


config = Config()
