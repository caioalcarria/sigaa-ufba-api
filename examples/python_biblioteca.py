"""Usando a BIBLIOTECA direto (sem servidor): pip install sigaa-ufba-api"""
import asyncio
import getpass

from sigaa import SigaaClient
from sigaa.services import academico


async def main():
    usuario = input("Usuário SIGAA: ")
    senha = getpass.getpass("Senha: ")
    async with SigaaClient() as sigaa:
        await sigaa.login(usuario, senha)
        hist = await sigaa.executar(academico.historico)
        print(f"CR {hist.indices.cr} · IAP {hist.indices.iap}")
        for p in hist.estatisticas.por_periodo:
            print(f"  {p.periodo}: CR do período {p.cr_periodo}  → acumulado {p.cr_acumulado}")
        mat = await sigaa.executar(academico.matricula)
        for t in mat.turmas:
            print(f"  {t.codigo} {t.componente} — {t.situacao}")


asyncio.run(main())
