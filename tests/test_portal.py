"""Testes dos parsers do Portal do Discente e do decodificador de horários (fixtures anonimizadas)."""

from datetime import date
from pathlib import Path

import pytest

from sigaa.parsers import portal as P
from sigaa.util import horario as H

FIX = Path(__file__).parent / "fixtures" / "portal"


def fx(nome: str) -> bytes:
    return (FIX / nome).read_bytes()


# ------------------------------------------------------------------ horário
@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("46N12 (19/08/2026 - 19/12/2026)", [("Quarta", ["N1", "N2"], "18:30", "20:20"), ("Sexta", ["N1", "N2"], "18:30", "20:20")]),
        ("2N1234 4N4", [("Segunda", ["N1", "N2", "N3", "N4"], "18:30", "22:10"), ("Quarta", ["N4"], "21:15", "22:10")]),
        ("7T2  7T3  7T4  7T5", [("Sábado", ["T2", "T3", "T4", "T5"], "13:55", "17:35")]),
        ("24M12 35T34", [("Segunda", ["M1", "M2"], "07:00", "08:50"), ("Terça", ["T3", "T4"], "14:50", "16:40"),
                         ("Quarta", ["M1", "M2"], "07:00", "08:50"), ("Quinta", ["T3", "T4"], "14:50", "16:40")]),
        ("2T56  4T56", [("Segunda", ["T5", "T6"], "16:40", "18:30"), ("Quarta", ["T5", "T6"], "16:40", "18:30")]),
        ("6M3456", [("Sexta", ["M3", "M4", "M5", "M6"], "08:50", "12:30")]),
        ("3N13", [("Terça", ["N1"], "18:30", "19:25"), ("Terça", ["N3"], "20:20", "21:15")]),
    ],
)
def test_decodificar(texto, esperado):
    h = H.decodificar(texto)
    assert h.reconhecido
    assert [(a.dia_nome, a.codigos, a.inicio, a.fim) for a in h.aulas] == esperado


def test_decodificar_periodo_e_totais():
    h = H.decodificar("2N1234 4N4 (19/08/2026 - 19/12/2026)")
    assert h.codigo == "2N1234 4N4"
    assert h.data_inicio == date(2026, 8, 19) and h.data_fim == date(2026, 12, 19)
    assert h.aulas_por_semana == 5 and h.minutos_por_semana == 275
    assert h.aulas[0].dia == 2 and h.aulas[0].dia_iso == 1 and h.aulas[0].minutos == 220


def test_decodificar_tolerante():
    assert H.decodificar(None) is None and H.decodificar("   ") is None
    h = H.decodificar("A DEFINIR 2N5")
    assert not h.reconhecido and "A" in h.nao_reconhecido
    assert h.aulas[0].codigos == ["N5"] and h.aulas[0].inicio is None  # slot fora da tabela da UFBA
    assert h.minutos_por_semana is None


def test_tabela_ufba():
    t = H.tabela_horarios()
    cods = {s.codigo: (s.inicio, s.fim) for s in t.slots}
    assert len(t.slots) == 16
    assert cods["M1"] == ("07:00", "07:55") and cods["M6"] == ("11:35", "12:30")
    assert cods["T1"] == ("13:00", "13:55") and cods["T6"] == ("17:35", "18:30")
    assert cods["N1"] == ("18:30", "19:25") and cods["N4"] == ("21:15", "22:10")


def test_separar_locais():
    local, locais = H.separar_locais("PAF 1 - 006 -  Terça Horários  18:30 às 19:25PAF 1 - 006 -  Terça Horários  19:25 às 20:20")
    assert local == "PAF 1 - 006"
    assert [(x.dia, x.inicio, x.fim) for x in locais] == [(3, "18:30", "19:25"), (3, "19:25", "20:20")]
    assert H.separar_locais("Smart Class III") == ("Smart Class III", [])
    assert H.separar_locais(None) == (None, [])


def test_dia_por_nome():
    assert H.dia_por_nome("Terça") == 3 and H.dia_por_nome("terca-feira") == 3 and H.dia_por_nome("Sabado") == 7


# ------------------------------------------------------------------- portal
def test_portal_dados_institucionais():
    pd = P.parse_portal(fx("portal.html"))
    d = pd.dados
    assert d.nome == "FULANO DE TAL DA SILVA" and d.matricula == "200000000"
    assert d.curso.nome == "SISTEMAS DE INFORMAÇÃO" and d.curso.unidade_sigla == "IC" and d.curso.turno == "N"
    assert d.curso.grau == "BACHARELADO" and d.curso.municipio == "SALVADOR"
    assert (d.nivel, d.status, d.entrada, d.semestre_atual) == ("GRADUAÇÃO", "ATIVO", "2022.1", "2026.2")
    assert d.email_truncado
    assert d.unidade == "INSTITUTO DE COMPUTAÇÃO" and d.unidade_codigo == "12.28"
    assert d.id_discente == 100000 and "verFoto" in d.foto_url
    i = d.integralizacao
    assert (i.ch_obrigatoria_pendente, i.ch_optativa_pendente, i.ch_total_curriculo, i.ch_complementar_pendente) == (855, 375, 2785, 0)
    assert i.percentual == pytest.approx(55.83) and i.percentual_arredondado == 56
    assert pd.versao_sigaa.startswith("v4.13")


def test_portal_turmas_semestre_com_id_turma():
    ts = P.parse_portal(fx("portal.html")).turmas_semestre
    assert [t.turma_id for t in ts] == [393420, 386385, 391763]
    assert all(t.front_end_id and len(t.front_end_id) == 40 for t in ts)
    assert all(t.atual and t.periodo == "2026.2" for t in ts)
    ihc = ts[1]
    assert ihc.local == "PAF 1 - 006" and len(ihc.locais) == 2 and ihc.horario.codigo == "35N12"


def test_portal_atualizacoes():
    at = P.parse_portal(fx("portal.html")).atualizacoes
    assert len(at) == 10
    a = at[0]
    assert a.data == date(2026, 10, 19) and a.turma_id == 393420 and a.periodo == "2026.2"
    assert a.tipo == "Nova Notícia" and a.titulo == "Novas datas de seminários"
    assert {x.turma_id for x in at} == {393420, 386385}


def test_portal_vazios():
    pd = P.parse_portal(fx("portal.html"))
    assert pd.atividades == [] and pd.noticias == [] and pd.comunidades_virtuais == [] and pd.forum_curso == []


def test_atividades_variacao():
    html = """<html><body><div id="avaliacao-portal"><h4>Minhas atividades</h4><table>
      <tr><th></th><th>Data</th><th>Atividade</th></tr>
      <tr><td><img src="/sigaa/img/portal_turma/tarefa.png" title="Tarefa"/></td><td>25/10/2026 23:59</td>
          <td><small>APLICAÇÕES PARA DISPOSITIVOS MÓVEIS<br/><a href="#" onclick="jsfcljs(document.getElementById('f'),{'f:x':'f:x','idTurma':'393420'},'');">Tarefa: Lista 3</a></small></td></tr>
      <tr><td></td><td>27/10/2026</td><td><small>INTERAÇÃO HUMANO-COMPUTADOR<br/>Avaliação: Prova 1</small></td></tr>
    </table></div></body></html>"""
    at = P.parse_portal(html).atividades
    assert len(at) == 2
    assert at[0].data == date(2026, 10, 25) and at[0].hora == "23:59" and at[0].tipo == "Tarefa"
    assert at[0].turma == "APLICAÇÕES PARA DISPOSITIVOS MÓVEIS" and at[0].turma_id == 393420 and "Lista 3" in at[0].descricao
    assert at[1].tipo == "Avaliação" and at[1].hora is None


def test_portal_html_minimo_nao_quebra():
    pd = P.parse_portal("<html><body><p>nada</p></body></html>")
    assert pd.dados.matricula is None and pd.turmas_semestre == [] and pd.atualizacoes == []


# ------------------------------------------------------------------- turmas
def test_turmas_classico():
    ts = P.parse_turmas_classico(fx("turmas.html"))
    assert len(ts) == 37
    t = ts[0]
    assert (t.periodo, t.codigo, t.turma, t.carga_horaria, t.horario.codigo) == ("2026.2", "MATC89", "01", 60, "46N12")
    assert t.front_end_id and t.turma_id is None and t.atual
    assert len({t.periodo for t in ts}) == 9
    assert sum(t.atual for t in ts) == 3


def test_turmas_mobile_tem_id_numerico():
    ts = P.parse_turmas_mobile(fx("mobile_turmas_todas.html"), "2026.2")
    assert len(ts) == 37 and all(t.turma_id for t in ts)
    assert ts[0].turma_id == 393420 and ts[0].nivel == "GRADUAÇÃO" and ts[0].codigo == "MATC89"
    mat220 = next(t for t in ts if t.turma_id == 382446)
    assert mat220.local == "PAF 1 - 021" and {x.dia for x in mat220.locais} == {3, 5}


def test_mesclar_turmas():
    c = P.parse_turmas_classico(fx("turmas.html"))
    m = P.parse_turmas_mobile(fx("mobile_turmas_todas.html"), "2026.2")
    p = P.parse_portal(fx("portal.html")).turmas_semestre
    ts = P.mesclar_turmas(c, m, p)
    assert len(ts) == 37
    assert all(t.turma_id and t.front_end_id and t.codigo and t.carga_horaria for t in ts)
    # MATD04 aparece em 3 períodos diferentes → 3 turmas distintas
    assert len([t for t in ts if t.codigo == "MATD04"]) == 3
    periodos = [t.periodo for t in ts]
    assert periodos == sorted(periodos, reverse=True)
    portal_por_front = {t.front_end_id: t.turma_id for t in p}
    for t in ts:
        if t.front_end_id in portal_por_front:
            assert t.turma_id == portal_por_front[t.front_end_id]


def test_mesclar_sem_mobile_mantem_front_end():
    c = P.parse_turmas_classico(fx("turmas.html"))
    p = P.parse_portal(fx("portal.html")).turmas_semestre
    ts = P.mesclar_turmas(c, p)
    assert len(ts) == 37
    assert sum(1 for t in ts if t.turma_id) == 3  # só as atuais (vindas do portal)


def test_grade_e_ics():
    p = P.parse_portal(fx("portal.html")).turmas_semestre
    g = H.montar_grade(p, "2026.2")
    assert g.periodo == "2026.2" and not g.conflitos
    seg = next(d for d in g.dias if d.dia == 2)
    assert [(a.inicio, a.fim, a.nome) for a in seg.aulas] == [("18:30", "22:10", "SISTEMAS DE APOIO À DECISÃO")]
    ter = next(d for d in g.dias if d.dia == 3)
    assert ter.aulas[0].local == "PAF 1 - 006"
    ics = H.gerar_ics(p)
    assert ics.startswith("BEGIN:VCALENDAR") and ics.count("BEGIN:VEVENT") == len(g.aulas)
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261219T235959Z" in ics
    assert "DTSTART;TZID=America/Bahia:20260824T183000" in ics  # 1ª segunda a partir de 19/08/2026
    assert all(len(linha.encode()) <= 75 for linha in ics.split("\r\n"))


def test_grade_conflito():
    a = P._turma("AAA01 - A", periodo="2026.2", horario_txt="2N12")
    b = P._turma("BBB01 - B", periodo="2026.2", horario_txt="2N23")
    g = H.montar_grade([a, b])
    assert g.conflitos == ["Segunda N2: AAA01 × BBB01"]


# ---------------------------------------------------- dados pessoais / perfil
def test_dados_pessoais():
    d = P.parse_dados_pessoais(fx("dados_pessoais.html"))
    assert d.nome == "FULANO DE TAL DA SILVA" and d.matricula == "200000000"
    assert d.data_nascimento == date(2000, 1, 1) and d.sexo == "M" and d.ano_conclusao_ensino_medio == 2020
    assert d.nome_pai == "PAI DE TAL" and d.nome_mae == "MAE DE TAL"
    assert d.documentos.cpf == "000.000.000-00" and d.documentos.rg == "0000000000" and d.documentos.rg_orgao == "SSP/BA"
    assert d.documentos.titulo_eleitor == "000000000000" and d.documentos.titulo_zona is None
    assert d.endereco.cep == "40000000" and d.endereco.logradouro == "RUA FICTICIA" and d.endereco.uf == "Bahia"
    assert d.contato.email == "fulano@example.com" and d.contato.celular == "(71) 900000000"
    assert d.renda_familiar is None and d.zona_residencia is None
    assert "Senha" not in d.campos_extras


def test_dados_pessoais_vazio():
    assert P.parse_dados_pessoais("<html></html>").nome is None


def test_perfil():
    p = P.parse_perfil(fx("perfil.html"))
    assert p.tem_foto and "verFoto" in p.foto_url
    assert p.descricao_pessoal is None and p.curriculo_lattes is None and p.assinatura is None


def test_perfil_preenchido():
    html = """<div id="conteudo"><textarea id="descricaoPessoal">Aluno de SI</textarea>
      <textarea id="areasInteresse">IA, IHC</textarea><input id="curriculoLattes" value="http://lattes.cnpq.br/0"/>
      <textarea name="j_id_x" title="Assinatura (utilizada nas mensagens da caixa postal)">Att, Fulano</textarea></div>"""
    p = P.parse_perfil(html)
    assert (p.descricao_pessoal, p.areas_interesse, p.curriculo_lattes, p.assinatura) == ("Aluno de SI", "IA, IHC", "http://lattes.cnpq.br/0", "Att, Fulano")
    assert not p.tem_foto


# ----------------------------------------------------------------- fórum
def test_forum_vazio():
    f = P.parse_forum_curso(fx("forum_lista.html"))
    assert f.titulo == "FÓRUM DO CURSO DE SISTEMAS DE INFORMAÇÃO" and f.topicos == []
    assert f.descricao.startswith("Este fórum")


def test_forum_com_topicos_variacao():
    html = """<div id="conteudo"><h2>Portal &gt; FÓRUM DO CURSO X</h2><table class="listagem">
      <tr><th>Título</th><th>Autor</th><th>Respostas</th><th>Última Postagem</th></tr>
      <tr><td><a href="#" onclick="jsfcljs(document.getElementById('f'),{'f:v':'f:v','id':'777'},'');">Dúvida sobre TCC</a></td>
          <td>FULANO</td><td>3</td><td>18/10/2026 21:05</td></tr></table></div>"""
    f = P.parse_forum_curso(html)
    t = f.topicos[0]
    assert (t.id, t.titulo, t.autor, t.respostas) == (777, "Dúvida sobre TCC", "FULANO", 3)
    assert t.ultima_postagem.isoformat() == "2026-10-18T21:05:00"


# --------------------------------------------------------------- módulos
def test_modulos():
    m = P.parse_modulos(fx("modulos.html"))
    assert m.habilitados == ["Gerenciamento de salas", "Portal do Discente"]
    disc = next(x for x in m.modulos if x.chave == "discente")
    assert disc.url == "/sigaa/verPortalDiscente.do" and disc.grupo == "Portais"
    assert next(x for x in m.modulos if x.chave == "sipac").grupo == "Outros Sistemas"
    assert not next(x for x in m.modulos if x.chave == "graduacao").habilitado


# ---------------------------------------------------------- salas livres
def test_filtros_salas_livres():
    f = P.parse_filtros_salas_livres(fx("salas_livres_form.html"))
    assert (f.ano, f.periodo) == (2026, 2)
    assert {o.rotulo for o in f.turnos} == {"manha", "tarde", "noite"}
    assert next(o for o in f.predios if o.rotulo == "PAF 1").valor == "31"
    assert next(o for o in f.niveis if o.valor == "G").rotulo == "GRADUAÇÃO"


def test_salas_livres():
    r = P.parse_salas_livres(fx("salas_livres_resultado.html"))
    assert r.total == 40 and r.emitido_em.isoformat() == "2026-10-19T19:48:00"
    s = r.salas[0]
    assert (s.predio, s.predio_nome, s.sala, s.capacidade, s.dia_nome, s.inicio, s.fim, s.turno) == (
        "PAF I", "PAF 1", "005", 60, "Segunda", "20:20", "21:15", "noite")
    assert any(x.capacidade is None for x in r.salas)  # sala sem capacidade cadastrada


def test_salas_livres_vazio():
    html = "<html><body>Nenhuma turma foi encontrada com os critérios utilizados<table><tr><td>predio</td><td>sala</td></tr></table></body></html>"
    assert P.parse_salas_livres(html).total == 0 and P.resultado_salas_vazio(html)


# ---------------------------------------------------------- caixa postal
def test_caixa_postal_best_effort():
    html = """<table><tr><th>Remetente</th><th>Assunto</th><th>Data</th></tr>
      <tr class="naoLida"><td>COORDENAÇÃO</td><td><a href="ver.jsf?idMensagem=55">Matrícula</a></td><td>01/10/2026 10:00</td></tr></table>"""
    c = P.parse_caixa_postal(html)
    m = c.mensagens[0]
    assert (m.id, m.remetente, m.assunto, m.lida) == ("55", "COORDENAÇÃO", "Matrícula", False)
