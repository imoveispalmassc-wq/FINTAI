"""
Testes offline do catch-up do TTM diário (não acessam a internet).

Rodar:  python -m unittest discover -s tests -v
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # .../utils (continha "/utils" a mais e não existia)
import ttm_auto as t  # noqa: E402

SEC = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/"
CVM = "https://www.rad.cvm.gov.br/ENET/frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega=1"


class FontesFalsas:
    """Simula SEC/CVM/Yahoo/BCB. `docs` = {(ticker, 'AAAA-MM-DD'): [doc,...]}."""

    def __init__(self, docs=None, ttm=None, precos=None, falhar_preco=None, link_ruim=False):
        self.docs = docs or {}
        self.ttm = ttm or {}
        self.precos = precos or {}
        self.falhar_preco = falhar_preco
        self.link_ruim = link_ruim
        self.chamadas_ttm = []
        self.dias_verificados = []

    def documentos_novos(self, ticker, dia):
        self.dias_verificados.append((ticker, dia.isoformat()))
        return self.docs.get((ticker, dia.isoformat()), [])

    def calcular_ttm(self, ticker):
        self.chamadas_ttm.append(ticker)
        r = t.vazio("ATUALIZADO")
        lucro, lpa = self.ttm.get(ticker, (1000.0, 2.0))
        r.update(lucro_ttm=lucro, lpa_ttm=lpa, lucro_moeda="USD", lpa_moeda="USD",
                 trimestres=["2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"],
                 fonte="SEC XBRL (teste)",
                 link_oficial="https://example.com/noticia" if self.link_ruim else SEC)
        return r

    def preco_fechamento(self, ticker, dia):
        if self.falhar_preco == ticker:
            raise t.ErroRede("Yahoo fora do ar (simulado)")
        p = self.precos.get((ticker, dia.isoformat()), 100.0)
        return {"preco": p, "preco_data": dia.isoformat(), "preco_moeda": "USD",
                "preco_fonte": "Yahoo (teste)"}

    def dolar(self, dia):
        return {"usd_brl": 5.8667, "usd_brl_data": dia.isoformat(), "usd_brl_fonte": "BCB (teste)"}


def preparar(pasta: Path, tickers, last_run=None, historico=None):
    (pasta / "guidance_tickers.json").write_text(json.dumps(tickers))
    if last_run:
        (pasta / "last_run.json").write_text(json.dumps({"last_run": last_run}))
    if historico is not None:
        (pasta / "ttm_diario.json").write_text(json.dumps(historico))


def ler(pasta: Path, nome: str):
    return json.loads((pasta / nome).read_text())


class TestCatchUp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dias_faltantes(self):
        self.assertEqual(t.dias_faltantes(date(2026, 11, 17), date(2026, 11, 19)),
                         [date(2026, 11, 18), date(2026, 11, 19)])
        self.assertEqual(t.dias_faltantes(date(2026, 11, 19), date(2026, 11, 19)), [])

    def test_processa_18_e_19_nao_so_19(self):
        """last_run = 17/11, hoje = 19/11 -> processa 18 e 19; balanço do dia 18 não é perdido."""
        preparar(self.dir, ["NVDA", "TGT", "PANW"], last_run="2026-11-17")
        f = FontesFalsas(docs={("TGT", "2026-11-18"): [{"form": "8-K", "data": "2026-11-18",
                                                        "link": SEC + "tgt-8k.htm"}]})
        self.assertEqual(t.executar(self.dir, date(2026, 11, 19), f), 0)

        dias = sorted({d for _, d in f.dias_verificados})
        self.assertEqual(dias, ["2026-11-18", "2026-11-19"])
        saida = ler(self.dir, "ttm_diario.json")
        self.assertEqual(len(saida), 6)  # 3 tickers x 2 dias
        tgt18 = next(r for r in saida if r["ticker"] == "TGT" and r["data"] == "2026-11-18")
        self.assertEqual(tgt18["origem_ttm"], "RECALCULADO")
        self.assertEqual(tgt18["documentos_novos"][0]["data"], "2026-11-18")
        self.assertTrue(all(r["dias_catchup"] == 2 for r in saida))
        self.assertEqual(ler(self.dir, "last_run.json")["last_run"], "2026-11-19")

    def test_sem_balanco_novo_mantem_ttm_e_atualiza_preco(self):
        anterior = {"data": "2026-11-17", "ticker": "ADM", "lucro_ttm": 2486e6, "lucro_moeda": "USD",
                    "lpa_ttm": 5.13, "lpa_moeda": "USD", "trimestres": ["2026-09-30"],
                    "fonte": "SEC XBRL", "link_oficial": SEC, "status": "ATUALIZADO",
                    "pendencias": [], "preco": 69.0, "preco_moeda": "USD", "pl": 13.45}
        preparar(self.dir, ["ADM"], last_run="2026-11-17", historico=[anterior])
        # Se recalculasse, viriam valores diferentes (999 / 9.99): prova que NÃO recalculou.
        f = FontesFalsas(ttm={"ADM": (999.0, 9.99)},
                         precos={("ADM", "2026-11-18"): 68.95, ("ADM", "2026-11-19"): 67.78})
        self.assertEqual(t.executar(self.dir, date(2026, 11, 19), f), 0)

        self.assertEqual(f.chamadas_ttm, [])
        r19 = next(r for r in ler(self.dir, "ttm_diario.json") if r["data"] == "2026-11-19")
        self.assertEqual(r19["lucro_ttm"], 2486e6)
        self.assertEqual(r19["lpa_ttm"], 5.13)
        self.assertEqual(r19["preco"], 67.78)
        self.assertEqual(r19["pl"], round(67.78 / 5.13, 2))
        self.assertEqual(r19["status"], "SEM_NOVO_DOCUMENTO")
        self.assertEqual(r19["origem_ttm"], "MANTIDO_TTM_ANTERIOR")

    def test_falha_nao_atualiza_last_run(self):
        preparar(self.dir, ["AAPL", "HSIC"], last_run="2026-11-17", historico=[])
        f = FontesFalsas(falhar_preco="HSIC")
        self.assertEqual(t.executar(self.dir, date(2026, 11, 19), f), 1)
        self.assertEqual(ler(self.dir, "last_run.json")["last_run"], "2026-11-17")
        self.assertEqual(ler(self.dir, "ttm_diario.json"), [])

        # No dia seguinte o Yahoo volta: processa 18, 19 e 20.
        f2 = FontesFalsas()
        self.assertEqual(t.executar(self.dir, date(2026, 11, 20), f2), 0)
        self.assertEqual(sorted({r["data"] for r in ler(self.dir, "ttm_diario.json")}),
                         ["2026-11-18", "2026-11-19", "2026-11-20"])
        self.assertEqual(ler(self.dir, "last_run.json")["last_run"], "2026-11-20")

    def test_numero_sem_link_oficial_e_descartado(self):
        preparar(self.dir, ["AAPL"], last_run="2026-11-18")
        f = FontesFalsas(link_ruim=True)
        self.assertEqual(t.executar(self.dir, date(2026, 11, 19), f), 0)
        r = ler(self.dir, "ttm_diario.json")[0]
        self.assertIsNone(r["lucro_ttm"])
        self.assertIsNone(r["lpa_ttm"])
        self.assertIsNone(r["pl"])
        self.assertEqual(r["status"], "PENDENTE_SEM_LINK_OFICIAL")

    def test_sem_last_run_cria_com_7_dias(self):
        preparar(self.dir, ["AAPL"])
        f = FontesFalsas()
        self.assertEqual(t.executar(self.dir, date(2026, 11, 19), f), 0)
        datas = sorted({r["data"] for r in ler(self.dir, "ttm_diario.json")})
        self.assertEqual(datas[0], "2026-11-13")
        self.assertEqual(len(datas), 7)

    def test_links_oficiais(self):
        self.assertTrue(t.link_oficial_valido(SEC))
        self.assertTrue(t.link_oficial_valido(CVM))
        self.assertFalse(t.link_oficial_valido("https://finance.yahoo.com/quote/AAPL"))
        self.assertFalse(t.link_oficial_valido("https://fakesec.gov.example.com/x"))


class TestTrimestres(unittest.TestCase):
    def test_aapl_q4_derivado_por_anual_menos_9m(self):
        """Dados reais do XBRL da Apple (EPS diluído FY26): 2,84 + 2,01 + 2,02 + (8,98 - 6,88) = 8,97."""
        fatos = [
            {"start": "2025-09-28", "end": "2025-12-27", "val": 2.84, "filed": "2026-01-30"},
            {"start": "2025-12-28", "end": "2026-03-28", "val": 2.01, "filed": "2026-05-01"},
            {"start": "2025-09-28", "end": "2026-03-28", "val": 4.85, "filed": "2026-05-01"},
            {"start": "2026-03-29", "end": "2026-06-27", "val": 2.02, "filed": "2026-07-31"},
            {"start": "2025-09-28", "end": "2026-06-27", "val": 6.88, "filed": "2026-07-31"},
            {"start": "2025-09-28", "end": "2026-09-26", "val": 8.98, "filed": "2026-11-03"},
        ]
        q = t.ultimos_4_consecutivos(t.trimestres_de_fatos(fatos))
        self.assertIsNotNone(q)
        self.assertTrue(q[-1]["derivado"])
        self.assertAlmostEqual(q[-1]["val"], 2.10, places=4)
        self.assertAlmostEqual(sum(x["val"] for x in q), 8.97, places=4)

    def test_buraco_nos_trimestres_fica_pendente(self):
        fatos = [
            {"start": "2025-10-01", "end": "2025-12-31", "val": 1, "filed": "a"},
            {"start": "2026-04-01", "end": "2026-06-30", "val": 1, "filed": "a"},
            {"start": "2026-07-01", "end": "2026-09-30", "val": 1, "filed": "a"},
            {"start": "2025-07-01", "end": "2025-09-30", "val": 1, "filed": "a"},
        ]
        self.assertIsNone(t.ultimos_4_consecutivos(t.trimestres_de_fatos(fatos)))

    def test_pl_xp_converte_moeda(self):
        reg = {"lpa_ttm": 10.41, "lpa_moeda": "BRL", "preco": 14.06, "preco_moeda": "USD",
               "preco_fonte": "Yahoo Finance (XP)"}
        pl, _ = t.calcular_pl(reg, 5.8667)
        self.assertAlmostEqual(pl, round(14.06 * 5.8667 / 10.41, 2))

    def test_pl_negativo(self):
        pl, obs = t.calcular_pl({"lpa_ttm": -0.5, "preco": 10, "lpa_moeda": "USD",
                                 "preco_moeda": "USD", "preco_fonte": "Yahoo"}, None)
        self.assertIsNone(pl)
        self.assertIn("negativo", obs)


def _f(ini, fim, val, filed="2026-11-20", accn="0000000000-26-000001"):
    return {"start": ini, "end": fim, "val": val, "filed": filed, "accn": accn}


class RedeFalsa:
    """companyconcept da SEC por tag: {tag: [fatos]}."""

    def __init__(self, por_tag):
        self.por_tag = por_tag

    def json(self, url):
        if url.endswith("company_tickers.json"):
            return {"0": {"ticker": "TGT", "cik_str": 27419}, "1": {"ticker": "ACM", "cik_str": 868857},
                    "2": {"ticker": "PANW", "cik_str": 1327567}}
        tag = url.rsplit("/", 1)[-1].replace(".json", "")
        fatos = self.por_tag.get(tag)
        if fatos is None:
            return None
        unidade = "USD/shares" if "Share" in tag else "USD"
        return {"units": {unidade: [dict(x) for x in fatos]}}


class TestRegrasTravadas(unittest.TestCase):
    """TESTE OBRIGATÓRIO (prompt travado de 22/11/2026)."""

    def test_tgt_sai_10_77_gaap_e_nao_10_91(self):
        rede = RedeFalsa({"EarningsPerShareDiluted": [
            _f("2025-11-02", "2026-01-31", 2.30), _f("2026-02-01", "2026-05-02", 1.71),
            _f("2026-05-03", "2026-08-01", 4.11), _f("2026-08-02", "2026-10-31", 2.65)]})
        r = t.Fontes(rede).calcular_ttm("TGT")
        self.assertAlmostEqual(r["lpa_ttm"], 10.77, places=4)
        self.assertEqual(r["lpa_tipo"], "diluido_gaap")
        self.assertNotIn("lpa_guidance", t.config_ativo("TGT"))   # REGRA 5: guidance fora do TTM

    def test_acm_sai_2_84_continuas_e_2_25_total_so_na_nota(self):
        def serie(q1, q2, q3, nove, ano):
            return [_f("2025-10-01", "2025-12-31", q1), _f("2026-01-01", "2026-03-31", q2),
                    _f("2026-04-01", "2026-06-30", q3), _f("2025-10-01", "2026-06-30", nove),
                    _f("2025-10-01", "2026-09-30", ano)]
        rede = RedeFalsa({"EarningsPerShareDiluted": serie(0.56, 1.39, -0.67, 1.28, 2.25),
                          "IncomeLossFromContinuingOperationsPerDilutedShare": serie(1.06, 1.42, -0.65, 1.85, 2.84)})
        r = t.Fontes(rede).calcular_ttm("ACM")
        self.assertAlmostEqual(r["lpa_ttm"], 2.84, places=4)
        self.assertTrue(r["tem_descontinuadas"])
        self.assertAlmostEqual(r["lpa_total"], 2.25, places=4)
        self.assertEqual(r["lpa_tipo"], "diluido_operacoes_continuas")

    def test_panw_sai_0_61_com_q4_do_release_e_registra_divergencia(self):
        rede = RedeFalsa({"EarningsPerShareDiluted": [
            _f("2025-08-01", "2025-10-31", 0.47), _f("2025-11-01", "2026-01-31", 0.61),
            _f("2026-02-01", "2026-04-30", -0.22), _f("2025-08-01", "2026-04-30", 0.79),
            _f("2025-08-01", "2026-07-31", 0.40), _f("2026-08-01", "2026-10-31", 0.57)]})
        r = t.Fontes(rede).calcular_ttm("PANW")
        self.assertAlmostEqual(r["lpa_ttm"], 0.61, places=4)
        self.assertAlmostEqual(r["q4_calculado"], -0.39, places=4)
        self.assertEqual((r["q4_release"], r["q4_usado"]), (-0.35, -0.35))

    def test_nenhum_pl_com_cotacao_copiada(self):
        for fonte in ("COPIADO - NÃO VERIFICADO (robô)", "", None):
            reg = {"lpa_ttm": 4.5, "lpa_moeda": "BRL", "preco": 40.07, "preco_moeda": "BRL", "preco_fonte": fonte}
            pl, _ = t.calcular_pl(reg, None)
            self.assertIsNone(pl)
            self.assertEqual(t.status_pl({**reg, "pl": pl}), "cotação pendente")

    def test_marcacao_nunca_some_e_ativo_com_ttm_nao_volta_para_pendente(self):
        tmp = tempfile.TemporaryDirectory()
        pasta = Path(tmp.name)
        marca = {"last_updated": "22/11/2026 às 10:31", "updated_by": "robo-claude-10h", "source_date": "17/11/2026"}
        ant = {"data": "2026-11-22", "ticker": "NVDA", "lucro_ttm": 226256e6, "lucro_moeda": "USD", "lpa_ttm": 9.31,
               "lpa_moeda": "USD", "trimestres": ["2026-10-25"], "fonte": "release", "link_oficial": SEC,
               "status": "ATUALIZADO", "pendencias": [], **marca}
        preparar(pasta, ["NVDA"], last_run="2026-11-22", historico=[ant])

        class Pendente(FontesFalsas):
            def calcular_ttm(self, ticker):
                return t.vazio("PENDENTE_XBRL", "10-Q ainda não no XBRL")
        # dia 23: sem documento (mantém); dia 24: documento novo, mas o cálculo volta pendente
        f = Pendente(docs={("NVDA", "2026-11-24"): [{"form": "10-Q", "data": "2026-11-24", "link": SEC}]})
        self.assertEqual(t.executar(pasta, date(2026, 11, 24), f), 0)
        for r in ler(pasta, "ttm_diario.json"):
            for c, v in marca.items():
                self.assertEqual(r[c], v)
            self.assertFalse(r["status"].startswith("PENDENTE"))
            self.assertEqual(r["lpa_ttm"], 9.31)
        tmp.cleanup()

    def test_recalculo_grava_marcacao(self):
        tmp = tempfile.TemporaryDirectory()
        pasta = Path(tmp.name)
        preparar(pasta, ["ADM"], last_run="2026-11-17", historico=[])
        self.assertEqual(t.executar(pasta, date(2026, 11, 18), FontesFalsas()), 0)
        r = ler(pasta, "ttm_diario.json")[0]
        self.assertEqual(r["updated_by"], "ttm_auto.py")
        self.assertRegex(r["last_updated"], r"^\d{2}/\d{2}/\d{4} às \d{2}:\d{2}$")
        self.assertEqual(r["pl_status"], "ok")
        tmp.cleanup()


class TestDivergenciaAutomatica(unittest.TestCase):
    """Issue #48, item 9: TTM recalculado por documento novo e diferente do que já estava salvo
    -> o robô mesmo abre a Issue de divergência (best-effort, nunca trava o catch-up)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ttm_diferente_do_anterior_aciona_a_issue_de_divergencia(self):
        anterior = {"data": "2026-11-17", "ticker": "ADM", "lucro_ttm": 2486e6, "lucro_moeda": "USD",
                    "lpa_ttm": 5.13, "lpa_moeda": "USD", "trimestres": ["2026-09-30"],
                    "fonte": "SEC XBRL", "link_oficial": SEC, "status": "ATUALIZADO",
                    "pendencias": [], "preco": 69.0, "preco_moeda": "USD", "pl": 13.45}
        preparar(self.dir, ["ADM"], last_run="2026-11-17", historico=[anterior])
        f = FontesFalsas(docs={("ADM", "2026-11-18"): [{"form": "8-K", "data": "2026-11-18",
                                                        "link": SEC + "adm-8k.htm"}]},
                         ttm={"ADM": (999.0, 9.99)})  # bem diferente do anterior (5,13)

        import utils.divergencia as divergencia
        chamadas = []
        original = divergencia.abrir_issue_divergencia
        divergencia.abrir_issue_divergencia = lambda **kw: chamadas.append(kw) or {"number": 1}
        try:
            self.assertEqual(t.executar(self.dir, date(2026, 11, 18), f), 0)
        finally:
            divergencia.abrir_issue_divergencia = original

        self.assertEqual(len(chamadas), 1)
        self.assertEqual(chamadas[0]["ticker"], "ADM")
        self.assertEqual(chamadas[0]["salvo"], 5.13)
        self.assertEqual(chamadas[0]["novo"], 9.99)
        self.assertEqual(chamadas[0]["link"], SEC + "adm-8k.htm")

    def test_ttm_igual_ao_anterior_nao_aciona_issue(self):
        anterior = {"data": "2026-11-17", "ticker": "ADM", "lucro_ttm": 1000.0, "lucro_moeda": "USD",
                    "lpa_ttm": 2.0, "lpa_moeda": "USD", "trimestres": ["2026-09-30"],
                    "fonte": "SEC XBRL", "link_oficial": SEC, "status": "ATUALIZADO",
                    "pendencias": [], "preco": 69.0, "preco_moeda": "USD", "pl": 13.45}
        preparar(self.dir, ["ADM"], last_run="2026-11-17", historico=[anterior])
        f = FontesFalsas(docs={("ADM", "2026-11-18"): [{"form": "8-K", "data": "2026-11-18", "link": SEC}]},
                         ttm={"ADM": (1000.0, 2.0)})  # igual ao anterior

        import utils.divergencia as divergencia
        chamadas = []
        original = divergencia.abrir_issue_divergencia
        divergencia.abrir_issue_divergencia = lambda **kw: chamadas.append(kw) or {"number": 1}
        try:
            self.assertEqual(t.executar(self.dir, date(2026, 11, 18), f), 0)
        finally:
            divergencia.abrir_issue_divergencia = original
        self.assertEqual(chamadas, [])

    def test_falha_ao_abrir_issue_nao_derruba_o_catchup(self):
        anterior = {"data": "2026-11-17", "ticker": "ADM", "lucro_ttm": 2486e6, "lucro_moeda": "USD",
                    "lpa_ttm": 5.13, "lpa_moeda": "USD", "trimestres": ["2026-09-30"],
                    "fonte": "SEC XBRL", "link_oficial": SEC, "status": "ATUALIZADO",
                    "pendencias": [], "preco": 69.0, "preco_moeda": "USD", "pl": 13.45}
        preparar(self.dir, ["ADM"], last_run="2026-11-17", historico=[anterior])
        f = FontesFalsas(docs={("ADM", "2026-11-18"): [{"form": "8-K", "data": "2026-11-18", "link": SEC}]},
                         ttm={"ADM": (999.0, 9.99)})

        import utils.divergencia as divergencia

        def explode(**kw):
            raise RuntimeError("sem GITHUB_TOKEN (simulado)")

        original = divergencia.abrir_issue_divergencia
        divergencia.abrir_issue_divergencia = explode
        try:
            self.assertEqual(t.executar(self.dir, date(2026, 11, 18), f), 0)
        finally:
            divergencia.abrir_issue_divergencia = original
        r18 = next(r for r in ler(self.dir, "ttm_diario.json") if r["data"] == "2026-11-18")
        self.assertEqual(r18["lpa_ttm"], 9.99)   # gravou o TTM novo mesmo com a issue falhando


class TestFonteOficialB3(unittest.TestCase):
    """Issue #26: release de resultados > CVM. BBAS3 = R$ 12,45 bi (Análise do Desempenho), não 11,02 bi (DRE CVM)."""

    def test_bbas3_usa_o_release_e_guarda_a_cvm_so_como_conferencia(self):
        class F(t.Fontes):
            def _ttm_cvm_dre(self, ticker, cfg):
                r = t.vazio("ATUALIZADO")
                r.update(lucro_ttm=11016424000.0, lpa_ttm=1.9226, trimestres=["2026-09-30"], link_oficial=CVM)
                return r
        r = F(RedeFalsa({})).calcular_ttm("BBAS3")
        self.assertAlmostEqual(r["lucro_ttm"] / 1e9, 12.453, places=3)
        self.assertAlmostEqual(r["lpa_ttm"], 2.1813, places=4)
        self.assertAlmostEqual(r["lucro_cvm"] / 1e9, 11.016, places=3)
        self.assertGreater(r["divergencia_cvm"], 0.1)
        self.assertIn("contabil_br.json", r["fonte"])

    def test_link_do_release_no_ri_e_aceito_como_oficial(self):
        self.assertTrue(t.link_oficial_valido("https://filemanager-cdn.mziq.com/published/x", t.config_ativo("PETR4")["ri"]))
        self.assertFalse(t.link_oficial_valido("https://investidor10.com.br/x", t.config_ativo("BBAS3")["ri"]))


if __name__ == "__main__":
    unittest.main()
