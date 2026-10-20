"""Testes dos parsers da turma virtual (fixtures anonimizadas em tests/fixtures/turma_virtual/)."""

from datetime import date, datetime
from pathlib import Path

import pytest

from sigaa.parsers import turma_virtual as P

FIX = Path(__file__).parent / "fixtures" / "turma_virtual"


def h(nome: str) -> bytes:
    return (FIX / nome).read_bytes()


# ------------------------------------------------------------------ listas de turmas e ids
def test_turmas_todas_e_mobile_casam_ids():
    desk = P.parse_turmas_anteriores(h("turmas_todas.html"))
    mob = P.parse_turmas_mobile(h("turmas_mobile.html"))
    assert len(desk) == 37 and len(mob) == 37
    assert all(t.front_end_id and len(t.front_end_id) == 40 for t in desk)
    assert all(t.turma_id for t in mob)
    P.casar_turmas(desk, mob)
    assert all(t.turma_id for t in desk), "toda turma do desktop ganha o idTurma do mobile"
    matc89 = next(t for t in desk if t.codigo == "MATC89")
    assert matc89.turma_id == 393420
    assert matc89.periodo == "2026.2" and matc89.turma == "01" and matc89.carga_horaria == 60
    # mesmo código em semestres diferentes (MATD04 3x) não se confunde
    matd04 = [t for t in desk if t.codigo == "MATD04"]
    assert len({t.turma_id for t in matd04}) == len(matd04) >= 3


# ------------------------------------------------------------------ principal
def test_principal_com_topicos_e_quadros():
    t = P.parse_principal(h("principal_matc89.html"), "379D8F1134E70BFEFBDEC0EF37FE66C2436EB469")
    assert (t.codigo, t.turma, t.periodo) == ("MATC89", "01", "2026.2")
    assert t.nome == "APLICAÇÕES PARA DISPOSITIVOS MÓVEIS"
    assert t.carga_horaria == 60
    assert t.andamento.aulas_ministradas == 36 and t.andamento.aulas_total == 72
    assert t.andamento.percentual_ch_ministrada == 50.0
    assert t.ultima_noticia.titulo == "Novas datas de seminários"
    assert t.ultima_noticia.data == datetime(2026, 10, 19, 8, 30)
    assert t.ultima_noticia.autor.startswith("FULANO DE TAL")
    assert len(t.topicos) == 1 and t.topicos[0].data_inicio == date(2026, 8, 19)
    assert [m.tipo for m in t.topicos[0].materiais] == ["conteudo"] * 3
    assert t.topicos[0].materiais[0].id == 6371183
    assert len(t.noticias_recentes) == 5 and t.noticias_recentes[0].id == 6729370
    assert len(t.avaliacoes_proximas) == 3
    assert t.atividades_recentes[0].descricao.startswith("Nova Notícia")
    assert {m.grupo for m in t.menu} >= {"Turma", "Alunos", "Materiais", "Atividades"}
    assert any(m.rotulo == "Ver Notas" and m.grupo == "Alunos" for m in t.menu)
    assert len(t.outras_turmas) == 3


def test_principal_materiais_de_arquivo_com_hash_e_links():
    t = P.parse_principal(h("principal_mata07.html"))
    assert len(t.topicos) == 30
    diag = next(x for x in t.topicos if x.titulo == "Avaliação diagnóstica")
    assert diag.links and diag.links[0].startswith("https://")
    assert "Clique aqui para registrar" in diag.descricao
    m = diag.materiais[0]
    assert m.tipo == "arquivo" and m.id_hash and len(m.id_hash) == 40 and m.icone == "pdf.png"
    assert m.descricao.startswith("Baixe o arquivo")


def test_principal_sem_topicos_e_com_ementa():
    vazio = P.parse_principal(h("principal_sem_topicos.html"))
    assert vazio.sem_topicos and vazio.topicos == [] and vazio.ementa is None
    em = P.parse_principal(h("principal_ementa.html"))
    assert em.ementa or em.topicos


# ------------------------------------------------------------------ notícias
def test_noticias_lista_e_detalhe():
    ns = P.parse_noticias(h("noticias.html"))
    assert len(ns) == 12 and ns[0].id == 6729370 and ns[0].data == date(2026, 10, 19)
    d = P.parse_noticia(h("noticia_detalhe.html"))
    assert d.titulo == "Duvidas sobre as notas" and d.id == 5817622
    assert d.data == datetime(2026, 7, 7, 0, 4)
    assert "smart class" in d.conteudo


# ------------------------------------------------------------------ participantes / plano / programa
def test_participantes():
    p = P.parse_participantes(h("participantes.html"))
    assert p.total_docentes == 1 and p.total_discentes == 48
    doc = p.docentes[0]
    assert doc.papel == "docente" and doc.formacao == "DOUTORADO" and doc.departamento == "INSTITUTO DE COMPUTAÇÃO"
    assert doc.email == "fulano@example.com" and doc.pagina_publica
    assert 1 <= len(p.discentes) <= 4
    al = p.discentes[0]
    assert al.matricula == "200000000" and al.curso and al.email and al.campos_extras == {}


def test_plano_de_curso():
    pl = P.parse_plano_curso(h("plano_curso.html"))
    assert pl.metodologia.startswith("Desenvolvimento de projeto")
    assert pl.horario_atendimento == "A concordar com os alunos"
    assert pl.id_componente == 45094
    assert len(pl.cronograma) == 28 and pl.cronograma[0].inicio == date(2026, 8, 20)
    assert pl.avaliacoes[0].descricao == "1ª Avaliação"
    assert pl.referencias_basicas == [] and pl.referencias_complementares[0].tipo == "Artigo"


def test_programa_indisponivel():
    pg = P.parse_programa(h("programa_indisponivel.html"))
    assert pg.disponivel is False and pg.codigo == "MATC89" and "não possui" in pg.mensagem


# ------------------------------------------------------------------ materiais
def test_conteudos():
    cs = P.parse_conteudos(h("conteudos.html"))
    assert [c.id for c in cs] == [6371183, 6371248, 6421528] and cs[0].criado_em == date(2026, 8, 28)
    d = P.parse_conteudo(h("conteudo_detalhe.html"), 6371183)
    assert d.titulo == "Temas para seminário" and "• Push notifications" in d.conteudo


def test_referencias():
    rs = P.parse_referencias(h("referencias.html"))
    assert rs[0].tipo == "Site" and rs[0].url.startswith("http://classroom.google.com")
    d = P.parse_referencia(h("referencia_detalhe.html"), 1)
    assert d.tipo == "Artigo" and d.ano == 2020 and d.autor == "Frank Zammetti" and d.url is None


def test_arquivos():
    a = P.parse_arquivos(h("arquivos.html"))
    assert len(a) == 13 and a[0].id == 2542120 and a[0].nome == "Plano de Aula" and a[0].topico == "Conteúdo Programático"
    assert P.parse_arquivos(h("arquivos_vazio.html")) == []


@pytest.mark.parametrize(
    "fixture,fn",
    [
        ("videos_vazio.html", P.parse_videos),
        ("tarefas_vazio.html", P.parse_tarefas),
        ("questionarios_vazio.html", P.parse_questionarios),
        ("enquetes_vazio.html", P.parse_enquetes),
        ("foruns_vazio.html", P.parse_foruns),
    ],
)
def test_telas_vazias(fixture, fn):
    assert fn(h(fixture)) == []


# ------------------------------------------------------------------ avaliações
def test_avaliacoes():
    av = P.parse_avaliacoes(h("avaliacoes.html"))
    assert [(a.id, a.data, a.hora) for a in av][0] == (6371178, date(2026, 8, 20), "00:00")
    d = P.parse_avaliacao(h("avaliacao_detalhe.html"), 6371178)
    assert d.descricao.startswith("Exercícios de programação") and d.data == date(2026, 8, 20)


# ------------------------------------------------------------------ fórum
def test_foruns_e_detalhe():
    fs = P.parse_foruns(h("foruns.html"))
    assert [(f.id, f.topicos) for f in fs] == [(1, 2), (2, 1)]
    assert fs[1].aula == "Conteúdo Programático" and fs[1].tipo == "Uma única discussão simples"
    assert fs[0].inicio == date(2026, 3, 12) and fs[0].fim == date(2026, 6, 23)
    d = P.parse_forum(h("forum_detalhe.html"), 1)
    assert d.forum.monitorar_leitura is True and d.forum.ordenacao == "Mostrar respostas aninhadas"
    assert d.forum.criado_em == datetime(2026, 3, 12, 20, 26)
    assert [t.id for t in d.topicos] == [1, 2] and d.topicos[0].titulo == "Material Seminários"
    assert d.topicos[0].ultima_mensagem_em == datetime(2026, 5, 15, 0, 36, 0) or d.topicos[0].ultima_mensagem_em.date() == date(2026, 5, 15)


def test_topico_forum_com_respostas_e_anexos():
    t = P.parse_topico_forum(h("forum_topico.html"), 2, 1)
    assert t.mensagem.titulo == "Forum para armazenar arquivos dos seminarios"
    assert len(t.respostas) == 17
    r = t.respostas[0]
    assert r.autor.startswith("FULANO DE TAL") and r.data and r.anexo_id == 2672347
    assert "Ver Arquivo Anexo" not in r.texto


# ------------------------------------------------------------------ notas
def test_notas_com_subavaliacoes_e_pesos():
    n = P.parse_notas(h("notas_subavaliacoes.html"))
    assert (n.codigo, n.periodo, n.situacao, n.resultado, n.faltas) == ("MATB19", "2026.1", "APR", 6.0, 0)
    u = n.unidades[0]
    assert u.rotulo == "Unid. 1" and u.nota == 6.0
    assert [(a.abreviacao, a.peso, a.nota) for a in u.avaliacoes] == [("Sem", 20.0, 9.5), ("P1", 25.0, 3.5), ("P2", 25.0, 1.0), ("Jude", 30.0, 10.0)]
    assert u.avaliacoes[1].denominacao == "Prova 1"
    assert n.reposicao is None


def test_notas_simples_e_nao_lancadas():
    n = P.parse_notas(h("notas_simples.html"))
    assert n.unidades[0].nota == 9.0 and n.unidades[0].avaliacoes == [] and n.situacao == "APR"
    v = P.parse_notas(h("notas_nao_lancadas.html"))
    assert v.lancadas is False and "lançadas" in v.mensagem


# ------------------------------------------------------------------ frequência
def test_frequencia():
    f = P.parse_frequencia(h("frequencia.html"))
    assert f.lancada and len(f.registros) == 18
    assert f.registros[0].registrada is False and f.registros[3].faltas == 0
    assert f.total_faltas == 6
    assert (f.presencas_registradas, f.aulas_com_registro, f.percentual_registradas) == (53, 59, 89.0)
    assert (f.aulas_ch, f.percentual_ch, f.minimo_percentual, f.duracao_aula_min) == (65, 81.0, 75.0, 55)
    assert f.max_faltas == 16 and f.faltas_restantes == 10


def test_frequencia_nao_lancada_ignora_totais_lixo():
    f = P.parse_frequencia(h("frequencia_nao_lancada.html"))
    assert f.lancada is False and f.registros == [] and f.presencas_registradas is None and f.percentual_ch is None


# ------------------------------------------------------------------ outros
def test_linha_tempo_grupo_estatisticas():
    ev = P.parse_linha_tempo(h("linha_tempo.html"))
    assert len(ev) == 2 and ev[0].tipo == "Nova Notícia cadastrada" and ev[0].data == datetime(2026, 10, 19, 8, 30)
    assert P.parse_grupo(h("grupo_vazio.html")).cadastrado is False
    e = P.parse_estatisticas(h("estatisticas.html"))
    assert e.titulo == "Estatísticas da Turma" and "cewolf" in P.url_grafico_estatisticas(h("estatisticas.html"))


def test_mensagens_de_erro():
    assert any("não possui um programa" in m for m in P.mensagens(h("programa_indisponivel.html")))
    assert P.mensagens(h("noticias.html")) == []


def test_nome_de_arquivo_nfd_estragado_do_sigaa():
    from sigaa.services.turma_virtual import _consertar_nome

    assert _consertar_nome("Regulac807a771o_de_Informac807a771o.pdf") == "Regulação_de_Informação.pdf"
    assert _consertar_nome("Plano_de_Aula_2024.pdf") == "Plano_de_Aula_2024.pdf"
