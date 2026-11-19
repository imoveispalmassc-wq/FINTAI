import utils.fila_github as fg


def test_pedir_ticker_sem_token_nao_chama_rede():
    chamadas = []
    assert fg.pedir_ticker("VALE3", None, buscar=lambda *a: chamadas.append(a)) is False
    assert not chamadas


def test_primeiro_pedido_cria_issue_nova():
    criadas = []
    ok = fg.pedir_ticker("VALE3", "tok", buscar=lambda t, tok: None,
                         criar=lambda t, tok: criadas.append((t, tok)) or {"number": 1})
    assert ok is True and criadas == [("VALE3", "tok")]


def test_segundo_pedido_do_mesmo_ticker_so_comenta_nao_cria_outra_issue():
    comentarios, criadas = [], []
    ok = fg.pedir_ticker("VALE3", "tok", buscar=lambda t, tok: {"number": 42, "title": "Fila: VALE3"},
                         criar=lambda t, tok: criadas.append(t), comentar=lambda n, tok: comentarios.append(n))
    assert ok is True and comentarios == [42] and not criadas


def test_falha_na_api_nao_derruba_a_tela_do_usuario():
    def explode(t, tok):
        raise RuntimeError("timeout")
    assert fg.pedir_ticker("VALE3", "tok", buscar=explode) is False


def test_listar_fila_ordena_por_mais_pedidos_e_ignora_issue_sem_prefixo():
    issues = [
        {"title": "Fila: WEGE3", "number": 1, "comments": 2, "created_at": "2026-11-20T10:00:00Z"},
        {"title": "Fila: VALE3", "number": 2, "comments": 49, "created_at": "2026-11-20T09:00:00Z"},
        {"title": "Outra coisa qualquer", "number": 3, "comments": 100},
    ]
    fila = fg.listar_fila("tok", buscar=lambda tok: issues)
    assert [f["ticker"] for f in fila] == ["VALE3", "WEGE3"]
    assert fila[0]["pedidos"] == 50 and fila[1]["pedidos"] == 3           # 1 (criação) + comentários


def test_fechar_issue_comenta_e_fecha():
    chamadas = {"comentou": None, "fechou": None}
    fg.fechar_issue(7, "tok", "validado!",
                    comentar=lambda n, t, c: chamadas.__setitem__("comentou", (n, t, c)),
                    fechar=lambda n, t: chamadas.__setitem__("fechou", (n, t)) or None)
    assert chamadas["comentou"] == (7, "tok", "validado!") and chamadas["fechou"] == (7, "tok")
