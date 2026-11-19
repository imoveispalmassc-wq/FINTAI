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
        reg = {"lpa_ttm": 10.41, "lpa_moeda": "BRL", "preco": 14.06, "preco_moeda": "USD"}
        pl, _ = t.calcular_pl(reg, 5.8667)
        self.assertAlmostEqual(pl, round(14.06 * 5.8667 / 10.41, 2))

    def test_pl_negativo(self):
        pl, obs = t.calcular_pl({"lpa_ttm": -0.5, "preco": 10, "lpa_moeda": "USD",
                                 "preco_moeda": "USD"}, None)
        self.assertIsNone(pl)
        self.assertIn("negativo", obs)


if __name__ == "__main__":
    unittest.main()
