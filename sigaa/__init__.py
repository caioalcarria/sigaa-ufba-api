"""sigaa — cliente Python (não oficial, somente leitura) do SIGAA da UFBA."""

__version__ = "0.1.0"

from .client import Page, SigaaClient  # noqa: E402,F401
from .errors import (  # noqa: E402,F401
    AcessoNegado,
    CredenciaisInvalidas,
    NaoEncontrado,
    NavegacaoInvalida,
    SessaoExpirada,
    SigaaError,
    SistemaIndisponivel,
)
