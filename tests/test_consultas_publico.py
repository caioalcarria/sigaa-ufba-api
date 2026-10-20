"""Testes dos parsers do SIGAA PÚBLICO (sem login). Fixtures anonimizadas em tests/fixtures/consultas/publico/
(pessoas trocadas por nomes fictícios; SIAPE, e-mail, Lattes e foto fictícios; estrutura HTML intacta)."""

from datetime import date, datetime
from pathlib import Path

from sigaa.parsers.consultas_publico import (
    docente_existe,
    parse_busca_componentes,
    parse_busca_docentes,
    parse_calendario_curso,
    parse_centro,
    parse_centro_cursos,
    parse_centro_departamentos,
    parse_centro_programas,
    parse_componente,
    parse_componentes_departamento,
    parse_curso_detalhe_pos,
    parse_curso_portal,
    parse_departamento,
    parse_disciplinas_docente,
    parse_docente,
    parse_docentes_departamento,
    parse_estrutura_curricular,
    parse_estruturas_curso,
    parse_lista_centros,
    parse_lista_cursos,
    parse_lista_departamentos,
    parse_noticias_curso,
    parse_ppp,
    parse_producao_docente,
    parse_programa_componente,
    parse_responsaveis,
    parse_turmas_curso,
    parse_turmas_publicas,
    parse_unidades_turmas,
    sem_programa,
    unidade_existe,
)

FXP = Path(__file__).parent / "fixtures/consultas/publico"


def pub(nome: str) -> str:
    return (FXP / nome).read_text(encoding="utf-8")


# ------------------------------------------------------------------------------ cursos
def test_lista_cursos_graduacao():
    cursos = parse_lista_cursos(pub("curso_lista_G.html"), "G")
    assert len(cursos) == 116
    si = next(x for x in cursos if x.id == 1876885)
    assert si.nome == "SISTEMAS DE INFORMAÇÃO"
    assert si.sede == "SALVADOR" and si.modalidade == "Presencial"
    assert si.unidade and "INSTITUTO DE COMPUTA" in si.unidade
    assert si.coordenador and si.coordenador.split()[0] in {"FULANO", "CICLANO", "BELTRANO", "MARIA", "JOAO", "ANA", "PEDRO", "LUCIA", "CARLOS", "JULIA"}
    assert si.url_portal and "portal.jsf?id=1876885" in si.url_portal
    assert all(c.id > 0 for c in cursos)


def test_lista_cursos_pos():
    cursos = parse_lista_cursos(pub("curso_lista_S.html"), "S")
    assert len(cursos) == 169
    dout = next(x for x in cursos if x.id == 43753)
    assert dout.nivel_texto == "DOUTORADO"
    assert dout.programa_id == 1820
    assert dout.url_portal is None  # pós só abre por POST (jsfcljs)


def test_curso_portal():
    cur = parse_curso_portal(pub("curso_portal.html"), 1876885)
    assert cur.nome and cur.nome.startswith("SISTEMAS DE INFORMA")
    assert cur.unidade == "INSTITUTO DE COMPUTAÇÃO - IC/UFBA"
    assert cur.titulo_profissional == "Bacharel em Sistemas de Informação"
    assert cur.area_conhecimento == "Ciências Exatas e da Terra"
    assert cur.modalidade == "Presencial"
    assert len(cur.coordenacao) == 1 and cur.coordenacao[0].cargo == "Coordenação"
    assert cur.apresentacao is None and cur.convenio_academico is None  # "Nenhum conteúdo disponível"
    assert cur.calendario and cur.calendario[0].data_inicio == date(2026, 8, 3)
    assert cur.calendario[0].data_fim == date(2026, 8, 5)


def test_curso_portal_inexistente():
    assert parse_curso_portal(pub("curso_portal_inexistente.html"), 1).nome is None


def test_curso_detalhe_pos():
    cur = parse_curso_detalhe_pos(pub("curso_detalhe_pos.html"), 43753)
    assert cur.nivel_texto == "DOUTORADO"
    assert cur.unidade and "PGCOMP" in cur.unidade
    assert [p.cargo for p in cur.coordenacao] == ["Vice-Coordenação", "Coordenação"]
    assert cur.telefones == ["(71) 3283-5750"]
    assert len(cur.emails) == 2
    assert cur.pagina_oficial == "https://posgraduacao.ufba.br/pgcomp"
    assert cur.conceito is None
    assert [e.codigo for e in cur.estruturas][:2] == ["D120271", "D120231"]
    assert cur.estruturas[0].id == 6428502 and cur.estruturas[0].ano_criacao == "2027.1"


def test_estruturas_curso():
    est = parse_estruturas_curso(pub("curso_curriculos.html"))
    assert [e.codigo for e in est] == ["T20261", "T20252", "G20251X", "195140", "195140A", "195140B"]
    ativa = [e for e in est if e.ativa]
    assert len(ativa) == 1 and ativa[0].id == 2421505
    assert all(e.turno == "Noturno" for e in est)


def _checa_estrutura(e):
    assert e.codigo == "G20251X"
    assert e.matriz_curricular == "SISTEMAS DE INFORMAÇÃO - SALVADOR - BACHARELADO - Presencial - N"
    assert e.periodo_vigor == "2025.2"
    assert (e.ch_total_minima, e.ch_obrigatoria_total, e.ch_optativa_minima, e.ch_complementar_minima) == (3101, 2206, 480, 415)
    assert (e.ch_obrigatoria_aula, e.ch_obrigatoria_orientacao, e.ch_maxima_periodo) == (2040, 166, 540)
    assert (e.prazo_minimo, e.prazo_medio, e.prazo_maximo) == (10, 10, 15)
    assert [n.nivel for n in e.niveis] == list(range(1, 11))
    n1 = e.niveis[0]
    assert n1.carga_horaria_total == 300 and len(n1.componentes) == 5
    mata02 = n1.componentes[0]
    assert (mata02.codigo, mata02.nome, mata02.carga_horaria, mata02.id, mata02.obrigatoria) == ("MATA02", "CÁLCULO A", 90, 44676, True)
    assert e.niveis[7].componentes == [] and e.niveis[7].carga_horaria_total == 0
    assert len(e.optativas) == 116 and all(o.natureza == "Optativa" and o.obrigatoria is False for o in e.optativas)
    assert e.ch_total_optativas_listadas == 7215
    assert e.complementares == []


def test_estrutura_curricular_abas():
    _checa_estrutura(parse_estrutura_curricular(pub("estrutura_detalhes.html"), 2421505, 1876885))


def test_estrutura_curricular_relatorio():
    _checa_estrutura(parse_estrutura_curricular(pub("estrutura_relatorio.html")))


def test_calendario_curso():
    ev = parse_calendario_curso(pub("curso_calendario.html"))
    assert len(ev) == 12
    assert {e.periodo for e in ev} == {"2026.1", "2026.2"}
    assert ev[0].descricao == "Matrícula para o período 2026.1."
    assert (ev[0].data_inicio, ev[0].data_fim) == (date(2026, 2, 19), date(2026, 2, 24))
    assert ev[2].data_fim is None


def test_ppp_e_noticias_vazios():
    p = parse_ppp(pub("curso_ppp.html"), 1876885)
    assert p.curso_id == 1876885 and p.perfil_profissional is None and p.projeto_pedagogico is None
    assert parse_noticias_curso(pub("curso_noticias.html")) == []


def test_turmas_curso():
    ts = parse_turmas_curso(pub("curso_turmas.html"))
    assert len(ts) == 61
    t = ts[0]
    assert (t.codigo_componente, t.componente_id, t.periodo, t.turma, t.vagas_reservadas) == ("MATC53", 45080, "2026.2", "01", 2)
    assert len(t.docentes) == 3 and all(d.siape for d in t.docentes)
    assert t.horario and t.horario.codigo == "7M2345 2T56"
    assert t.horario.data_inicio == date(2026, 8, 19) and t.horario.aulas_por_semana == 6


# --------------------------------------------------------------------------- componentes
def test_busca_componentes():
    r = parse_busca_componentes(pub("componentes_busca_codigo.html"))
    assert len(r) == 1
    assert (r[0].id, r[0].codigo, r[0].tipo, r[0].carga_horaria, r[0].tem_programa) == (44697, "MATA37", "DISCIPLINA", 60, True)


def test_busca_componentes_pos_sem_link_de_programa():
    r = parse_busca_componentes(pub("componentes_busca_pos.html"))
    assert len(r) == 181
    assert r[1].codigo == "PGCOMP/IC0062" and r[1].id == 16604 and r[1].tem_programa is False


def test_componente_detalhe_busca():
    c = parse_componente(pub("componente_detalhe_busca.html"), 44697)
    assert (c.codigo, c.nome, c.tipo, c.modalidade) == ("MATA37", "INTRODUÇÃO À LÓGICA DE PROGRAMAÇÃO", "DISCIPLINA", "Presencial")
    assert c.unidade_responsavel and c.unidade_responsavel.startswith("DEPARTAMENTO DE CIÊNCIA DA COMPUTAÇÃO")
    assert c.pre_requisitos is None and c.co_requisitos is None
    assert c.equivalencias_codigos == ["MAT045A", "MAT045B", "MAT045", "MAT146A", "MAT146B", "MAT146", "MATA37A"]
    assert (c.carga_horaria_total, c.carga_horaria_teorica, c.carga_horaria_pratica, c.carga_horaria_ead) == (60, 30, 30, 0)
    assert c.ementa and c.ementa.startswith("Desenvolvimento de algoritmos")
    assert c.matriculavel_online is True and c.necessita_orientador is False and c.quantidade_avaliacoes == 1
    assert any(x.codigo == "MATA40" for x in c.requisito_de)
    assert any(x.codigo == "MAT045" for x in c.equivalente_de)
    assert c.historico_equivalencias[0].ativa is True and c.historico_equivalencias[0].inicio_vigencia == date(2023, 1, 1)
    si = [x for x in c.curriculos if x.codigo == "G20251X" and "SISTEMAS" in (x.matriz_curricular or "")]
    assert si and si[0].obrigatoria is True and si[0].semestre == 1 and si[0].ativo is True
    assert len(c.cargas_horarias) >= 8 and c.cargas_horarias[0].grupo == "Aula"


def test_componente_resumo_link():
    c = parse_componente(pub("componente_resumo_link.html"), 44697)
    assert c.codigo == "MATA37" and c.modalidade is None
    assert (c.carga_horaria_total, c.carga_horaria_teorica, c.carga_horaria_pratica) == (60, 30, 30)
    assert c.pre_requisitos is None
    assert len(c.curriculos) == 43
    assert c.atributos.get("Módulo") == "45"


def test_componente_sem_programa():
    html = pub("componente_sem_programa.html")
    assert sem_programa(html)
    assert parse_programa_componente(html) is None


def test_programa_componente_generico():
    html = """<html><body><table class="visualizacao"><caption>Programa</caption>
      <tr><th>Componente Curricular:</th><td>MATX99 - DISCIPLINA DE TESTE</td></tr>
      <tr><th>Ano-Período:</th><td>2026.1</td></tr>
      <tr><th>Objetivos:</th><td>Entender coisas.</td></tr>
      <tr><th>Conteúdo:</th><td>Unidade 1<br/>Unidade 2</td></tr>
      <tr><th>Metodologia:</th><td>Aulas.</td></tr>
      <tr><th>Procedimentos de Avaliação da Aprendizagem:</th><td>Provas.</td></tr>
      <tr><th>Referências:</th><td>Livro A.</td></tr></table></body></html>"""
    p = parse_programa_componente(html, 1)
    assert p is not None
    assert (p.codigo, p.nome, p.periodo) == ("MATX99", "DISCIPLINA DE TESTE", "2026.1")
    assert p.objetivos == "Entender coisas." and p.avaliacao == "Provas." and p.referencias == "Livro A."
    assert p.conteudo and "Unidade 2" in p.conteudo


# ------------------------------------------------------------------------------ turmas
def test_unidades_turmas():
    u = parse_unidades_turmas(pub("turmas_form.html"))
    assert len(u) == 205
    assert any(x.id == 1114 and "CIÊNCIA DA COMPUTAÇÃO" in x.nome for x in u)


def test_turmas_publicas():
    ts = parse_turmas_publicas(pub("turmas_resultado.html"))
    assert len(ts) == 57
    jogos = ts[0]
    assert jogos.codigo_componente == "GICC0009" and jogos.componente_id == 54931
    assert len(jogos.docentes) == 3  # linhas repetidas da mesma turma foram fundidas
    assert [d.carga_horaria for d in jogos.docentes] == [15, 30, 15]
    assert jogos.local == "A definir" and jogos.locais == []
    mat045 = [t for t in ts if t.codigo_componente == "MAT045" and t.turma == "04"][0]
    assert mat045.local == "PAF 1 - 006"
    assert [(x.dia, x.inicio, x.fim) for x in mat045.locais] == [(5, "10:40", "11:35"), (5, "11:35", "12:30")]
    assert all(t.periodo == "2026.2" for t in ts)


# ----------------------------------------------------------------------------- docentes
def test_busca_docentes():
    ds = parse_busca_docentes(pub("docentes_busca.html"))
    assert len(ds) == 2 and ds[0].siape == ds[1].siape and ds[0].siape
    assert ds[0].unidade == "INSTITUTO DE COMPUTAÇÃO"
    assert ds[1].unidade == "DEPARTAMENTO DE CIÊNCIA DA COMPUTAÇÃO /IC"


def test_docentes_departamento():
    ds = parse_docentes_departamento(pub("departamento_professores.html"))
    assert len(ds) == 32
    assert ds[0].titulacao == "DOUTOR" and ds[0].categoria == "Ativo Permanente"
    assert ds[0].lattes == "http://lattes.cnpq.br/0000000000000000"
    assert all(d.siape for d in ds)


def test_docente_portal():
    html = pub("docente_portal.html")
    assert docente_existe(html)
    d = parse_docente(html, 9000001)
    assert d.nome and d.unidade == "INSTITUTO DE COMPUTAÇÃO"
    assert d.descricao_pessoal is None
    assert d.formacao and "\n" in d.formacao
    assert d.areas_interesse == ["Computação Gráfica", "Modelagem 3D", "Realidade Virtual", "Realidade Aumentada"]
    assert d.sala == "IC- 2012" and d.email == "fulano@exemplo.br"
    assert d.endereco_profissional and d.endereco_profissional.splitlines()[0].startswith("Departamento de Ciência da Computação")
    assert d.formacao_academica == []


def test_docente_producao():
    cats = parse_producao_docente(pub("docente_producao.html"))
    assert [(c.categoria, c.quantidade) for c in cats] == [("Trabalho de Fim de Curso", 3), ("Orientações de Pós-Graduação", 12)]
    assert cats[0].itens[0].data == "12/2025"
    assert cats[1].itens[0].situacao == "Orientação em Andamento"


def test_docente_disciplinas():
    ds = parse_disciplinas_docente(pub("docente_disciplinas.html"))
    assert len(ds) == 129
    d = ds[0]
    assert (d.periodo, d.codigo, d.nome, d.carga_horaria) == ("2026.2", "MATA65", "COMPUTAÇÃO GRÁFICA", 60)
    assert d.horario and d.horario.codigo == "24T34" and d.horario.data_fim == date(2026, 12, 19)


# ---------------------------------------------------------------- centros e departamentos
def test_lista_centros():
    cs = parse_lista_centros(pub("centros_lista.html"))
    assert len(cs) == 34
    ic = next(c for c in cs if c.id == 2435)
    assert ic.nome == "INSTITUTO DE COMPUTAÇÃO" and ic.sigla == "IC/UFBA" and ic.municipio == "SALVADOR"
    assert {d.id for d in ic.departamentos} == {1114, 2440}


def test_centro_portal_e_abas():
    html = pub("centro_portal.html")
    assert unidade_existe(html)
    c = parse_centro(html, 2435)
    assert c.nome == "INSTITUTO DE COMPUTAÇÃO" and c.sigla == "IC/UFBA (SALVADOR)"
    assert len(c.diretoria) == 1 and c.diretoria[0].siape
    assert c.telefones == [] and c.apresentacao is None
    assert [d.id for d in parse_centro_departamentos(pub("centro_departamentos.html"))] == [1114, 2440]
    cursos = parse_centro_cursos(pub("centro_cursos.html"))
    assert [x.id for x in cursos] == [1876851, 1876886, 1876885] and cursos[0].modalidade == "Presencial"
    assert [p.id for p in parse_centro_programas(pub("centro_programas.html"))] == [1820, 2146, 2693]


def test_centro_inexistente():
    assert not unidade_existe(pub("centro_portal_inexistente.html"))


def test_departamentos():
    ds = parse_lista_departamentos(pub("departamentos_lista.html"))
    assert [(d.id, d.centro) for d in ds] == [(1114, "INSTITUTO DE COMPUTAÇÃO"), (2440, "INSTITUTO DE COMPUTAÇÃO")]
    d = parse_departamento(pub("departamento_portal.html"), 1114)
    assert d.sigla == "DCC/IC/UFBA" and d.nome == "DEPARTAMENTO DE CIÊNCIA DA COMPUTAÇÃO /IC"
    assert len(d.chefia) == 2 and all(p.siape for p in d.chefia)
    assert d.noticias == [] and d.telefones == []


def test_componentes_departamento():
    cs = parse_componentes_departamento(pub("departamento_componentes.html"))
    assert len(cs) == 133
    assert (cs[0].id, cs[0].codigo, cs[0].tipo, cs[0].carga_horaria) == (54931, "GICC0009", "DISCIPLINA", 60)


# --------------------------------------------------------------------------- responsáveis
def test_responsaveis():
    ch = parse_responsaveis(pub("responsaveis_chefes.html"), "chefes")
    assert len(ch) == 77 and ch[0].centro == "ESCOLA DE ADMINISTRAÇÃO" and ch[0].cargo is None
    cg = parse_responsaveis(pub("responsaveis_coord_graduacao.html"), "coordenadores_graduacao")
    assert len(cg) == 192 and {x.cargo for x in cg} >= {"Coordenação", "Vice-Coordenação"}
    cp = parse_responsaveis(pub("responsaveis_coord_pos.html"), "coordenadores_pos")
    assert len(cp) == 162
    di = parse_responsaveis(pub("responsaveis_diretores.html"), "diretores")
    assert len(di) == 34 and di[0].unidade == "ESCOLA DE ADMINISTRAÇÃO" and di[0].centro is None
    assert all(x.email in (None, "fulano@exemplo.br") for x in ch + cg + cp + di)


# ====================================================================================================
# frente 'extras1'
# ====================================================================================================
from sigaa.parsers.consultas_publico import (  # noqa: E402
    mensagem_erro_publico,
    parse_acervo_detalhe,
    parse_acervo_resultado,
    parse_acervo_total,
    parse_acordos_mobilidade,
    parse_aquisicoes,
    parse_artigos_resultado,
    parse_novas_aquisicoes,
    parse_processo_seletivo,
    parse_processos_seletivos,
    parse_programa_apresentacao,
    parse_programa_areas,
    parse_programa_cursos,
    parse_programa_docentes,
    parse_programa_noticia,
    parse_programa_noticias,
    parse_programa_portal,
    parse_programa_processos_seletivos,
    parse_programas_pos,
)

FX_extras1 = Path(__file__).parent / "fixtures/consultas/publico/extras1"


def fx_extras1(nome: str) -> str:
    return (FX_extras1 / nome).read_text(encoding="utf-8")


# ------------------------------------------------------------------ biblioteca
def test_extras1_acervo_resultado():
    itens = parse_acervo_resultado(fx_extras1("bib_acervo_resultado.html"))
    assert len(itens) == 3
    a = itens[0]
    assert a.id == 1505245
    assert a.autor == "FULANO DE TAL"
    assert a.titulo == "Cálculo 1 : diferencial e integral"
    assert a.edicao == "2. ed."
    assert a.ano == "1981"
    assert a.quantidade == 1
    assert parse_acervo_total(fx_extras1("bib_acervo_resultado.html")) == 47


def test_extras1_acervo_vazio_e_mensagem():
    h = fx_extras1("bib_acervo_vazio.html")
    assert parse_acervo_resultado(h) == []
    assert parse_acervo_total(h) == 0
    assert "Não foram encontrados" in mensagem_erro_publico(h)


def test_extras1_acervo_detalhe():
    d = parse_acervo_detalhe(fx_extras1("bib_acervo_detalhe.html"))
    assert d.id == 612004
    assert d.registro_sistema == 90540
    assert d.numero_chamada == "517.2/.3 P677cP 12. ed."
    assert d.autor == "Fulano de Tal"
    assert d.titulo == "Calculo diferencial e integral"
    assert d.local_publicacao == "Porto"
    assert d.editora == "Lopes da Silva"
    assert d.ano_publicacao == "1988"
    assert d.edicao == "12. ed."
    assert d.assuntos == ["Cálculo diferencial", "Cálculo integral"]
    assert d.notas == ["Titulo original em russo"]
    assert d.total_exemplares == 1
    ex = d.exemplares[0]
    assert ex.biblioteca == "Biblioteca Central Zila Mamede"
    assert ex.localizacao == "517.2/.3 P675c 12.ed. v.1"
    assert (ex.tipo_material, ex.colecao, ex.status, ex.situacao) == ("Livro", "Acervo Circulante", "REGULAR", "Disponível")
    assert ex.id_material == 222148


def test_extras1_artigos_vazio():
    assert parse_artigos_resultado(fx_extras1("bib_artigos_vazio.html")) == []


def test_extras1_aquisicoes():
    itens = parse_aquisicoes(fx_extras1("bib_aquisicoes.html"))
    assert len(itens) >= 3
    a = itens[0]
    assert a.ano_aquisicao == 2024
    assert a.centro == "CENTRO DE TECNOLOGIA"
    assert a.departamento == "COORDENAÇÃO DO CURSO ENGENHARIA ELÉTRICA"
    assert a.titulo == "CÁLCULO NUMÉRICO COM APLICAÇÕES"
    assert a.volume == "2" and a.ano_publicacao == 1987 and a.quantidade == 4
    assert a.autor == "BELTRANO SOUZA"
    assert itens[1].volume is None  # "Vol. 0" = sem volume
    assert parse_aquisicoes(fx_extras1("bib_aquisicoes_vazio.html")) == []


def test_extras1_novas_aquisicoes_vazio():
    n = parse_novas_aquisicoes(fx_extras1("bib_novas_aquisicoes.html"))
    assert n.total == 0 and n.itens == []
    assert n.bibliotecas == "Todas" and n.area == "Todas"
    assert n.data_inicio == date(2026, 9, 19) and n.data_fim == date(2026, 10, 19)


# ---------------------------------------------------------- processos seletivos
def test_extras1_lista_processos():
    itens = parse_processos_seletivos(fx_extras1("ps_lista_stricto.html"))
    assert len(itens) == 4
    p = itens[0]
    assert p.id == 40043
    assert p.edital == "PROCESSO SELETIVO PARA INGRESSO NO CURSO DE DOUTORADO 2027.1"
    assert p.curso == "DOUTORADO EM BIODIVERSIDADE E EVOLUÇÃO"
    assert p.vagas == 6
    assert p.inscricao_inicio == date(2026, 10, 19) and p.inscricao_fim == date(2026, 12, 13)
    assert p.aberto is True
    assert p.id_programa == 1825
    assert itens[-1].aberto is False  # período "fechado" (ainda não abriu / encerrado)


def test_extras1_lista_processos_vazia():
    assert parse_processos_seletivos(fx_extras1("ps_lista_vazia.html")) == []


def test_extras1_detalhe_processo():
    d = parse_processo_seletivo(fx_extras1("ps_detalhe.html"))
    assert d.id == 40043
    assert d.curso == "DOUTORADO EM BIODIVERSIDADE E EVOLUÇÃO/PPGBIOEVO - SALVADOR"
    assert d.programa == "PROGRAMA DE PÓS-GRADUAÇÃO EM BIODIVERSIDADE E EVOLUÇÃO (PPGBIOEVO)"
    assert d.nivel == "DOUTORADO"
    assert d.inscricao_inicio == datetime(2026, 10, 19, 0, 0)
    assert d.inscricao_fim == datetime(2026, 12, 13, 23, 59)
    assert d.vagas == 6
    assert d.inscricoes_abertas is True
    assert len(d.etapas) == 3
    e = d.etapas[0]
    assert e.nome == "Anteprojetos enquadrados e inscrições homologadas"
    assert e.divulgacao_resultado == datetime(2026, 12, 15, 23, 59)
    assert e.analise_recurso == datetime(2026, 12, 18, 23, 59)
    assert [m.funcao for m in d.comissao].count("PRESIDENTE") == 1
    assert d.comissao[0].nome == "ZEFA FICTICIA"
    doc = d.documentos[0]
    assert doc.tipo == "Edital do Processo Seletivo"
    assert doc.url.startswith("/sigaa/verProducao?idProducao=")
    assert doc.disponibilizado_em == datetime(2026, 10, 15, 12, 0)
    assert d.descricao.startswith("O Programa de Pós-Graduação")
    assert "ppgbioevo@ufba.br" in d.orientacoes_inscritos
    assert d.noticias == []


def test_extras1_detalhe_processo_sem_link_inscricao():
    d = parse_processo_seletivo(fx_extras1("ps_detalhe_fechado.html"))
    assert d.inscricoes_abertas is False
    assert d.id is None  # sem link de inscrição a tela não expõe o id (o serviço preenche)
    assert d.vagas == 27 and len(d.etapas) == 2


# ------------------------------------------------------- acordos de mobilidade
def test_extras1_acordos_vazio():
    assert parse_acordos_mobilidade(fx_extras1("mobilidade_vazio.html")) == []


def test_extras1_acordos_sintetico():
    itens = parse_acordos_mobilidade(fx_extras1("mobilidade_sintetico.html"))
    assert len(itens) == 2
    a = itens[0]
    assert (a.id, a.pais, a.instituicao, a.sigla, a.status) == (123, "Portugal", "UNIVERSIDADE FICTICIA DE LISBOA", "UFL", "Ativo")
    assert a.fim_vigencia == date(2028, 12, 31)
    assert itens[1].id is None


# --------------------------------------------------------- programas de pós
def test_extras1_lista_programas():
    itens = parse_programas_pos(fx_extras1("prog_lista.html"))
    assert len(itens) >= 3
    p = itens[0]
    assert (p.id, p.sigla, p.centro) == (1289, "NPGA", "ESCOLA DE ADMINISTRAÇÃO")
    assert p.nome == "PROGRAMA DE PÓS-GRADUAÇÃO EM ADMINISTRAÇÃO (NPGA)"


def test_extras1_portal_programa():
    p = parse_programa_portal(fx_extras1("prog_portal.html"))
    assert p.id == 1825
    assert p.sigla == "PPGBIOEVO"
    assert p.centro == "INSTITUTO DE BIOLOGIA" and p.id_centro == 78
    assert p.email == "ppgbioevo@ufba.br"
    assert p.telefone == "(71) 0000-0000"
    assert p.site == "https://posgraduacao.ufba.br/ppgbioevo"
    assert p.secoes_extras["Sinopse Histórica"] == 66900643
    assert len(p.noticias) == 5 and p.noticias[0].id == 6507056
    assert p.noticias[0].titulo == "Banca de DEFESA: BELTRANO SOUZA"
    assert p.noticias[0].data == datetime(2026, 9, 18)
    assert [(x.id, x.nivel) for x in p.processos_seletivos] == [(40039, "MESTRADO"), (40043, "DOUTORADO")]
    assert p.processos_seletivos[0].inscricao_fim == date(2026, 12, 13)


def test_extras1_apresentacao():
    a = parse_programa_apresentacao(fx_extras1("prog_apresentacao.html"))
    assert a.texto.startswith("O Programa de Pós-Graduação em Biodiversidade e Evolução (PPGBioEvo) é composto")
    assert "\n" in a.texto
    assert a.endereco_alternativo == "https://ppgbioevo.bio.ufba.br/"
    assert [c.nome for c in a.coordenacao] == ["MARIA DE TAL", "JOANA FICTICIA"]
    assert a.coordenacao[0].siape == 1000101
    assert a.coordenacao[0].telefones == ["(71) 0000-0000", "(71) 0000-0000"]
    assert a.coordenacao[0].email == "coordenacao@exemplo.org"


def test_extras1_areas_linhas():
    areas = parse_programa_areas(fx_extras1("prog_areas.html"))
    assert [(a.nivel, a.nome) for a in areas][:2] == [("Doutorado", "Biodiversidade e Evolução"), ("Doutorado", "Zoologia")]
    l0 = areas[0].linhas_pesquisa[0]
    assert (l0.id, l0.nome) == (1676592, "SISTEMÁTICA E BIOGEOGRAFIA")
    assert l0.descricao == "Biodiversidade e Evolução- SISTEMÁTICA E BIOGEOGRAFIA"
    assert sum(len(a.linhas_pesquisa) for a in areas) == 9


def test_extras1_cursos():
    cursos = parse_programa_cursos(fx_extras1("prog_cursos.html"))
    assert len(cursos) == 4
    c = cursos[0]
    assert (c.id, c.nome, c.nivel, c.nivel_codigo) == (43933, "DOUTORADO EM BIODIVERSIDADE E EVOLUÇÃO", "Doutorado", "D")
    assert "capes.gov.br" in c.url_capes
    assert cursos[2].nivel_codigo == "E"


def test_extras1_docentes():
    ds = parse_programa_docentes(fx_extras1("prog_equipe.html"))
    grupos = {d.grupo for d in ds}
    assert grupos == {"Pós-Doutorandos", "Biodiversidade e Evolução"}
    prof = next(d for d in ds if d.grupo == "Biodiversidade e Evolução")
    assert prof.vinculo == "PROFESSOR" and prof.nivel == "PERMANENTE"
    assert prof.siape is not None and prof.email.endswith("@exemplo.org")
    pos = [d for d in ds if d.grupo == "Pós-Doutorandos"]
    assert pos[0].vinculo is None and pos[0].siape is None


def test_extras1_processos_do_programa():
    ps = parse_programa_processos_seletivos(fx_extras1("prog_processo_seletivo.html"))
    assert [(p.id, p.nivel) for p in ps] == [(40043, "Doutorado"), (40039, "Mestrado")]
    assert ps[0].edital == "PROCESSO SELETIVO PARA INGRESSO NO CURSO DE DOUTORADO 2027.1"
    assert ps[0].inscricao_inicio == date(2026, 10, 19)


def test_extras1_noticias_programa():
    ns = parse_programa_noticias(fx_extras1("prog_noticias.html"))
    assert len(ns) == 3
    assert ns[0].id == 6507056
    assert ns[0].data == datetime(2026, 9, 18, 16, 4)
    assert ns[0].titulo == "Banca de DEFESA: BELTRANO SOUZA"


def test_extras1_noticia_programa():
    n = parse_programa_noticia(fx_extras1("prog_noticia.html"))
    assert n.titulo == "Banca de DEFESA: FULANO DE TAL"
    assert n.id == 6507056 and n.id_programa == 1825
    assert "DATA : 31/08/2026" in n.texto
    assert "Presidente - 1000001 - CICLANO DA SILVA" in n.texto


# ====================================================================================================
# frente 'extras2'
# ====================================================================================================
from sigaa.parsers.consultas_publico import (  # noqa: E402
    mensagens_publico,
    parse_acao_extensao,
    parse_acoes_extensao,
    parse_bases_pesquisa,
    parse_bolsistas_pesquisa,
    parse_centros_cursos_abertos,
    parse_curso_aberto,
    parse_cursos_abertos,
    parse_departamentos_cursos_abertos,
    parse_inscricoes_extensao,
    parse_laboratorio,
    parse_laboratorios,
    parse_projeto_pesquisa,
    parse_projetos_pesquisa,
)

FIX_extras2 = Path(__file__).parent / "fixtures/consultas/publico/extras2"


def ler_extras2(nome: str) -> bytes:
    return (FIX_extras2 / nome).read_bytes()


# ------------------------------------------------------------------ pesquisa
def test_extras2_projetos_ufba_vazio():
    html = ler_extras2("ufba_pq_projetos_vazio.html")
    assert parse_projetos_pesquisa(html) == []
    assert any("Não foram encontrados" in m for m in mensagens_publico(html))


def test_extras2_projetos_lista():
    ps = parse_projetos_pesquisa(ler_extras2("ref_pq_projetos_lista.html"))
    assert len(ps) == 3
    p = ps[0]
    assert p.id == 35879223
    assert p.codigo == "PVP18187-2024"
    assert p.titulo.startswith("Documentos de professores")
    assert p.coordenador == "FULANO DE TAL" or p.coordenador.isupper()
    assert p.tipo == "INTERNO"
    assert p.situacao == "EM EXECUÇÃO"
    assert p.centro.startswith("CCAE")
    assert p.ano == 2024
    assert all(x.id for x in ps)
    assert len({x.centro for x in ps}) == 2  # agrupamento por centro respeitado


def test_extras2_projeto_detalhe():
    p = parse_projeto_pesquisa(ler_extras2("ref_pq_projeto_detalhe.html"))
    assert p.codigo == "PVP17825-2024"
    assert p.ano == 2024
    assert p.titulo.startswith("A Semiótica aplicada")
    assert p.tipo.startswith("INTERNO")
    assert p.situacao == "EM EXECUÇÃO"
    assert p.centro.startswith("CCAE")
    assert p.coordenador
    assert "EDITAL" in p.edital
    assert p.data_inicio == date(2024, 9, 1) and p.data_fim == date(2025, 8, 31)
    assert p.palavras_chave[0] == "Língua portuguesa"
    assert p.area_conhecimento == "Lingüística Aplicada"
    assert p.grupo_pesquisa and p.linha_pesquisa
    assert p.resumo and "Iniciação Científica" in p.resumo
    assert "Descrição" in p.secoes
    assert len(p.membros) == 2
    coord = [m for m in p.membros if m.coordenador]
    assert len(coord) == 1 and coord[0].nome == p.coordenador
    assert coord[0].categoria == "DOCENTE" and coord[0].funcao == "COORDENADOR(A)"
    assert all(m.siape for m in p.membros)
    assert "@" not in p.model_dump_json().replace("fulano@example.org", "")


def test_extras2_bases():
    assert parse_bases_pesquisa(ler_extras2("ufba_pq_bases_vazio.html")) == []
    bs = parse_bases_pesquisa(ler_extras2("ref_pq_bases_lista.html"))
    assert len(bs) == 3
    assert bs[0].nome.startswith("EDUCAÇÃO NAS ESCOLAS")
    assert bs[0].codigo is None
    assert bs[0].coordenador


def test_extras2_bolsistas():
    assert parse_bolsistas_pesquisa(ler_extras2("ufba_pq_bolsistas_erro.html")) == []
    bs = parse_bolsistas_pesquisa(ler_extras2("ref_pq_bolsistas_lista.html"))
    assert len(bs) == 3
    b = bs[0]
    assert b.discente in ("FULANO DE TAL", "CICLANO DA SILVA", "BELTRANO SOUZA", "FULANA DE OLIVEIRA")
    assert b.tipo_bolsa == "PIBIC-FAPESQ (IC)"
    assert b.cota.startswith("Cota 2026-2027")
    assert b.projeto_codigo == "PVG21372-2026"
    assert b.projeto_titulo.startswith("Análise in vitro")
    assert b.plano_titulo.startswith("Avaliação dos parâmetros")
    assert b.orientador
    assert b.data_inicio == date(2026, 9, 16) and b.data_fim is None
    assert bs[1].data_inicio == date(2026, 9, 9) and bs[1].data_fim == date(2026, 9, 16)


def test_extras2_laboratorios():
    assert parse_laboratorios(ler_extras2("ufba_pq_labs_vazio.html")) == []
    ls = parse_laboratorios(ler_extras2("ref_pq_labs_lista.html"))
    assert len(ls) == 3
    assert ls[1].id == 186483611
    assert ls[1].codigo == "LAB2291-2026"
    assert ls[1].nome.startswith("ANTIQVA")
    assert ls[1].unidade.startswith("CCHLA")
    assert ls[1].coordenador


def test_extras2_laboratorio_detalhe():
    lab = parse_laboratorio(ler_extras2("ref_pq_lab_detalhe.html"))
    assert lab.codigo == "LAB2291-2026"
    assert lab.tipo == "Laboratório de Pesquisa Multiusuários"
    assert lab.sigla == "ANTIQVA"
    assert lab.descricao and "Antiguidade" in lab.descricao
    assert lab.inicio_atividades == date(2026, 1, 19)
    assert lab.em_atividade is True
    assert lab.area_m2 == 13.67
    assert lab.unidade.startswith("CCHLA") and lab.subunidade.startswith("HIST")
    assert lab.localizacao == "Sala 220"
    assert len(lab.grupos_pesquisa) == 1 and len(lab.programas_pos) == 1
    assert len(lab.producoes) == 3
    assert lab.palavras_chave == ["História Antiga", "Egiptologia", "Assiriologia", "Arqueologia Clássica"]
    assert lab.presta_servicos is True and len(lab.servicos) == 2
    assert lab.pretende_prestar_servicos is True and len(lab.servicos_futuros) == 2
    assert lab.coordenador and lab.vice_coordenador and lab.coordenador != lab.vice_coordenador
    assert lab.inicio_coordenacao == date(2026, 1, 19)


# ------------------------------------------------------------------ extensão
def test_extras2_acoes_extensao():
    assert parse_acoes_extensao(ler_extras2("ufba_ext_lista_vazia.html")) == []
    acs = parse_acoes_extensao(ler_extras2("ref_ext_lista.html"))
    assert len(acs) == 3
    a = acs[0]
    assert a.id == 13035 and a.ano == 2024 and a.tipo == "PROJETO" and a.tipo_id == 2
    assert a.titulo.startswith("QUEBRA GELO")
    assert a.unidade == "CCTA - DTH"


def test_extras2_acao_extensao_detalhe():
    a = parse_acao_extensao(ler_extras2("ref_ext_detalhe.html"))
    assert a.id == 13035
    assert a.titulo.startswith("QUEBRA GELO")
    assert a.ano == 2024 and a.tipo == "PROJETO"
    assert (a.bolsas_concedidas, a.discentes_envolvidos, a.publico_estimado) == (0, 7, 1000)
    assert a.area_principal == "SAÚDE" and a.area_cnpq == "Multidisciplinar"
    assert a.unidade_proponente.startswith("CCTA")
    assert a.municipios == ["João Pessoa - PB"]
    assert len(a.espacos) == 1
    assert a.fonte_financiamento.startswith("FINANCIAMENTO INTERNO")
    assert a.url.endswith("/visualizacaoAcaoExtensao/13035")
    assert a.resumo and a.publico_alvo
    assert len(a.membros) == 3
    coord = [m for m in a.membros if m.coordenador]
    assert len(coord) == 1 and a.coordenador == coord[0].nome and coord[0].siape
    assert all(m.categoria for m in a.membros)
    assert "Público Estimado" in a.campos


def test_extras2_inscricoes_extensao():
    assert parse_inscricoes_extensao(ler_extras2("ufba_ext_inscricoes_vazia.html")) == []
    ins = parse_inscricoes_extensao(ler_extras2("ref_ext_inscricoes.html"))
    assert len(ins) == 2
    i = ins[0]
    assert i.id == 15852 and i.tipo == "CURSO"
    assert i.titulo.startswith("Saberes Indígenas")
    assert i.coordenador
    assert i.inscricoes_ate == date(2026, 10, 19)
    assert (i.vagas_total, i.vagas_aprovadas, i.vagas_pendentes, i.vagas_restantes) == (140, 24, 0, 116)
    assert ins[1].tipo == "EVENTO"


# ------------------------------------------------------------ cursos abertos
def test_extras2_centros_cursos_abertos():
    cs = parse_centros_cursos_abertos(ler_extras2("ufba_cursosabertos.html"))
    assert len(cs) > 20
    adm = next(c for c in cs if c.id == 1283)
    assert adm.nome == "ESCOLA DE ADMINISTRAÇÃO"
    assert [d.nome for d in adm.departamentos] == ["COORDENAÇÃO ACADÊMICA/EADM"]


def test_extras2_departamentos_a4j():
    ds = parse_departamentos_cursos_abertos(ler_extras2("ufba_cursosabertos_a4j_departamentos.xml"))
    assert ds and all(d.id for d in ds)
    assert ds[0].id == 1322 and "EDUCAÇÃO FÍSICA" in ds[0].nome


def test_extras2_cursos_abertos_lista():
    for nome in ("ufba_cursosabertos.html", "ufba_cursosabertos_busca.html"):
        ts = parse_cursos_abertos(ler_extras2(nome))
        assert len(ts) == 1
        assert ts[0].id == 376591 and ts[0].codigo == "PGEDU0151" and ts[0].nome == "PROJETO DE TESE I"
    assert parse_cursos_abertos(ler_extras2("ufba_cursosabertos_vazio.html")) == []
    assert any("Não foram encontrados" in m for m in mensagens_publico(ler_extras2("ufba_cursosabertos_vazio.html")))


def test_extras2_curso_aberto_detalhe():
    c = parse_curso_aberto(ler_extras2("ufba_cursoaberto_detalhe.html"))
    assert c.codigo == "PGEDU0151" and c.nome == "PROJETO DE TESE I"
    assert c.periodo == "2026.1"
    assert c.ementa.startswith("Atividade durante a qual o doutorando")
    assert len(c.docentes) == 2 and all(d.siape for d in c.docentes)
    assert {d.nome for d in c.docentes} <= {"FULANO DE TAL", "CICLANO DA SILVA"}
    assert len(c.topicos) == 1
    t = c.topicos[0]
    assert t.titulo == "Aulas presenciais"
    assert t.data_inicio == t.data_fim == date(2026, 4, 18)
    assert t.conteudo.startswith("Aulas presenciais em Vitória")
    assert len(t.materiais) == 6
    m = t.materiais[0]
    assert m.id_producao == 2596316 and m.titulo == "Material das aulas" and m.url.startswith("/sigaa/verProducao")


def test_extras2_html_vazio_nao_quebra():
    vazio = "<html><body></body></html>"
    assert parse_projetos_pesquisa(vazio) == []
    assert parse_bases_pesquisa(vazio) == []
    assert parse_bolsistas_pesquisa(vazio) == []
    assert parse_laboratorios(vazio) == []
    assert parse_acoes_extensao(vazio) == []
    assert parse_inscricoes_extensao(vazio) == []
    assert parse_cursos_abertos(vazio) == []
    assert parse_centros_cursos_abertos(vazio) == []
    assert parse_projeto_pesquisa(vazio).titulo is None
    assert parse_laboratorio(vazio).nome is None
    assert parse_acao_extensao(vazio).titulo is None
    assert parse_curso_aberto(vazio).nome is None
