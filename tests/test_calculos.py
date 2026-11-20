from calculos import normalizar_ticker


def test_normalizar_ticker_br_padrao_ganha_sa():
    for t in ("PETR4", "VALE3", "ITUB4", "WEGE3", "BBAS3", "BOVA11"):
        assert normalizar_ticker(t) == f"{t}.SA"


def test_normalizar_ticker_b3sa3_ganha_sa_mesmo_com_digito_no_meio_do_codigo():
    # B3 S.A. (a própria bolsa): o código tem um dígito dentro do nome (B3SA), não só no final
    assert normalizar_ticker("B3SA3") == "B3SA3.SA"
    assert normalizar_ticker("b3sa3") == "B3SA3.SA"


def test_normalizar_ticker_eua_nao_ganha_sa():
    for t in ("AAPL", "MSFT", "TGT", "XP", "PANW"):
        assert normalizar_ticker(t) == t


def test_normalizar_ticker_ja_com_sufixo_nao_duplica():
    assert normalizar_ticker("PETR4.SA") == "PETR4.SA"
