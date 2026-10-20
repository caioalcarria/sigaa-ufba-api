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
    #: só abre sessão extra se o SIGAA estiver com menos que esta fração do teto global em voo
    POOL_PRESSAO_MAX: float = _num("SIGAA_API_POOL_PRESSAO_MAX", 0.5)
    #: quantas navegações a página do portal/turmas.jsf pode ser reaproveitada antes de ser baixada de
    #: novo (o MyFaces do SIGAA UFBA guarda as 10 últimas views da sessão: uma página sobrevive a 9
    #: navegações e morre na 10ª; 8 deixa margem). 0 = sempre baixa (comportamento antigo).
    REUSAR_VIEWS: int = int(_num("SIGAA_API_REUSAR_VIEWS", 8))
    #: ritmo de UMA sessão: intervalo mínimo entre o INÍCIO de duas requisições (s) — teto de ~3 req/s
    MIN_INTERVALO: float = _num("SIGAA_API_MIN_INTERVALO", 0.3)
    #: ... e pausa mínima entre o FIM de uma e o início da próxima (s). Antes era 0,25 s contado do fim
    #: (somava 250 ms a cada viagem); 0,15 s é o mínimo combinado pro SIGAA real.
    MIN_FOLGA: float = _num("SIGAA_API_MIN_FOLGA", 0.15)
    #: teto GLOBAL de requisições simultâneas ao SIGAA (todas as sessões de todos os alunos)
    MAX_CONCORRENCIA_SIGAA: int = int(_num("SIGAA_API_MAX_CONCORRENCIA_SIGAA", 64))
    #: UMA piscina de conexões pra todas as sessões em vez de uma por sessão. Só pra comparação: a piscina
    #: do httpcore degrada com muita requisição simultânea (ver docs/perf/sessoes.md). Deixe false.
    TRANSPORTE_COMPARTILHADO: bool = _bool("SIGAA_API_TRANSPORTE_COMPARTILHADO", False)
    #: conexões HTTP keep-alive de CADA sessão (uma sessão navega uma tela por vez; >1 só pra GETs simultâneos)
    CONEXOES_POR_SESSAO: int = int(_num("SIGAA_API_CONEXOES_POR_SESSAO", 4))
    #: negociar HTTP/2 com o SIGAA (o da UFBA só fala HTTP/1.1; deixe false)
    HTTP2: bool = _bool("SIGAA_API_HTTP2", False)
    #: processos do pool de parse (HTML/PDF fora do event loop). Vazio = núcleos-1 (1 a 8); 0 = desliga
    PARSE_PROCESSOS: int | None = int(os.environ["SIGAA_PARSE_PROCESSOS"]) if os.getenv("SIGAA_PARSE_PROCESSOS") else None
    #: prazo total de uma requisição na API (s); estourou = 504 e a navegação é cancelada
    TIMEOUT_REQUISICAO_S: float = _num("SIGAA_API_TIMEOUT_S", 120)
    #: comprimir respostas JSON maiores que isso (bytes) com gzip quando o cliente aceita; 0 = desliga
    GZIP_MIN_BYTES: int = int(_num("SIGAA_API_GZIP_MIN_BYTES", 2048))
    #: limiares do coletor de lixo (gc.set_threshold) — o padrão do Python é 700,10,10
    GC_LIMIARES: tuple[int, ...] = tuple(int(x) for x in os.getenv("SIGAA_API_GC_LIMIARES", "50000,20,20").split(","))
    #: origens liberadas no CORS (vírgula). "*" libera tudo.
    CORS: list[str] = [o.strip() for o in os.getenv("SIGAA_API_CORS", "*").split(",") if o.strip()]


config = Config()
