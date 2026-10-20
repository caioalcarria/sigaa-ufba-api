"""Exceções da biblioteca. A API converte cada uma num código HTTP estável."""


class SigaaError(Exception):
    """Erro genérico vindo do SIGAA (página de 'Comportamento Inesperado', resposta estranha...)."""

    codigo = "sigaa_erro"


class CredenciaisInvalidas(SigaaError):
    codigo = "credenciais_invalidas"


class SessaoExpirada(SigaaError):
    """A sessão do SIGAA caiu (inatividade ~30 min, logoff, ou login em outro lugar)."""

    codigo = "sessao_expirada"


class NavegacaoInvalida(SigaaError):
    """O SIGAA recusou a navegação ('O endereço digitado não é válido', ViewState velho...)."""

    codigo = "navegacao_invalida"


class AcessoNegado(SigaaError):
    codigo = "acesso_negado"


class NaoEncontrado(SigaaError):
    codigo = "nao_encontrado"


class SistemaIndisponivel(SigaaError):
    """SIGAA fora do ar / em manutenção / timeout."""

    codigo = "sigaa_indisponivel"
