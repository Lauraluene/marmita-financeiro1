"""
Marmita do Engenheiro — Painel Financeiro
"""
import os
import tempfile
from collections import defaultdict
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session

from categorizador import categorizar, calcular_dre, receitas_por_semana, MESES_NOME
import database as db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "marmita2026segredo")

@app.before_request
def setup_db():
    """Inicializa o banco na primeira requisição (compatível com Vercel serverless)."""
    if not getattr(app, '_db_initialized', False):
        try:
            db.init_db()
            app._db_initialized = True
        except Exception as e:
            pass  # será tratado nas rotas que usarem o banco

# ── LOGIN ─────────────────────────────────────────────────────────────────────

LOGIN_USER = os.environ.get("APP_USER", "marmita")
LOGIN_PASS = os.environ.get("APP_PASS", "engenheiro2026")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logado"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        if (request.form.get("usuario") == LOGIN_USER and
                request.form.get("senha") == LOGIN_PASS):
            session["logado"] = True
            return redirect(url_for("index"))
        erro = "Usuário ou senha incorretos."
    return render_template("login.html", erro=erro)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── CONFIG ────────────────────────────────────────────────────────────────────

CATEGORIAS_SAIDAS = [
    "Gás", "Motoboys / Entregas", "Salários", "Diaristas",
    "Supermercado", "Fornecedor de Proteínas", "Hortifruti", "Embalagens",
    "Pró-labore", "Contabilidade", "Impostos", "FGTS",
    "Manutenção", "Troco", "Outros / Diversos",
]

def fmt(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _aplicar_memoria(lancamentos: list) -> list:
    """Aplica a memória de classificações sobre os lançamentos pendentes."""
    memoria = db.buscar_memoria()
    import unicodedata
    def norm(t):
        t = t.lower().strip()
        t = unicodedata.normalize("NFD", t)
        return "".join(c for c in t if unicodedata.category(c) != "Mn")
    for l in lancamentos:
        if l.status == "pendente":
            dn = norm(l.descricao)
            if dn in memoria:
                l.categoria = memoria[dn]
                l.status = "auto"
    return lancamentos

# ── INÍCIO ────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    meses = db.buscar_meses_importados()
    return render_template("index.html", meses=meses)

# ── UPLOAD ────────────────────────────────────────────────────────────────────

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    if "extrato" not in request.files:
        flash("Nenhum arquivo enviado.", "erro")
        return redirect(url_for("index"))

    arquivo = request.files["extrato"]
    if not arquivo.filename.lower().endswith(".pdf"):
        flash("Envie um arquivo PDF.", "erro")
        return redirect(url_for("index"))

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        arquivo.save(tmp.name)
        tmp_path = tmp.name

    try:
        from parser_nubank import extrair_transacoes
        transacoes = extrair_transacoes(tmp_path)
        if not transacoes:
            flash("Não foi possível extrair transações do PDF.", "erro")
            return redirect(url_for("index"))

        lancamentos = categorizar(transacoes)
        lancamentos = _aplicar_memoria(lancamentos)

        mes = lancamentos[0].mes
        ano = lancamentos[0].ano
        db.salvar_lancamentos(lancamentos, mes, ano)
    finally:
        os.unlink(tmp_path)

    pendentes = db.buscar_pendentes(mes, ano)
    if pendentes:
        return redirect(url_for("confirmacao", mes=mes, ano=ano))
    return redirect(url_for("dashboard", mes=mes, ano=ano))

# ── CONFIRMAÇÃO ───────────────────────────────────────────────────────────────

@app.route("/confirmacao/<int:mes>/<int:ano>")
@login_required
def confirmacao(mes, ano):
    pendentes = db.buscar_pendentes(mes, ano)
    categorias_custom = db.buscar_categorias_custom()
    todas_categorias = CATEGORIAS_SAIDAS + [c for c in categorias_custom if c not in CATEGORIAS_SAIDAS]
    return render_template(
        "confirmacao.html",
        pendentes=pendentes,
        categorias=todas_categorias,
        mes=mes, ano=ano,
        mes_nome=MESES_NOME.get(mes, str(mes))
    )

@app.route("/confirmar", methods=["POST"])
@login_required
def confirmar():
    mes = int(request.form["mes"])
    ano = int(request.form["ano"])
    for key, value in request.form.items():
        if key.startswith("cat_"):
            lid = int(key.split("_")[1])
            desc = request.form.get(f"desc_{lid}", "")
            # Se o usuário criou uma nova categoria, usa o campo de texto
            if value == "__nova__":
                value = request.form.get(f"nova_cat_{lid}", "").strip()
                if not value:
                    continue  # ignora se deixou em branco
                db.salvar_categoria_custom(value)
            db.atualizar_categoria(lid, value, desc)
    return redirect(url_for("dashboard", mes=mes, ano=ano))

# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@app.route("/dashboard/<int:mes>/<int:ano>")
@login_required
def dashboard(mes, ano):
    from categorizador import Lancamento
    rows = db.buscar_lancamentos(mes, ano)

    lancamentos = [
        Lancamento(
            id=r.get("id"),
            dia=r["dia"], mes=r["mes"], ano=r["ano"],
            tipo=r["tipo"], descricao=r["descricao"], valor=r["valor"],
            categoria=r["categoria"], subcategoria=r.get("subcategoria", ""),
            status=r["status"], tipo_mov=r["tipo_mov"], raw=r.get("raw", "")
        ) for r in rows
    ]

    dre     = calcular_dre(lancamentos)
    semanas = receitas_por_semana(lancamentos)

    saidas   = [l for l in lancamentos if l.tipo == "saida"   and l.status != "ignorado"]
    entradas = [l for l in lancamentos if l.tipo == "entrada" and l.status != "ignorado"]

    por_cat       = defaultdict(float)
    por_cat_items = defaultdict(list)
    for l in saidas:
        por_cat[l.categoria]        += l.valor
        por_cat_items[l.categoria].append(l)

    receita_ifood  = sum(l.valor for l in entradas if l.subcategoria == "iFood")
    receita_cartao = sum(l.valor for l in entradas if l.subcategoria == "Cartão")
    receita_outras = sum(l.valor for l in entradas if l.subcategoria == "Outras")

    pendentes_count = len([l for l in lancamentos if l.status == "pendente"])

    categorias_custom = db.buscar_categorias_custom("saida")
    todas_categorias = CATEGORIAS_SAIDAS + [c for c in categorias_custom if c not in CATEGORIAS_SAIDAS]
    cats_entrada_base = ["iFood", "Cartão", "Outras"]
    cats_entrada_custom = db.buscar_categorias_custom("entrada")
    categorias_entrada = cats_entrada_base + [c for c in cats_entrada_custom if c not in cats_entrada_base]

    return render_template(
        "dashboard.html",
        mes=mes, ano=ano, mes_nome=MESES_NOME.get(mes, str(mes)),
        dre=dre, semanas=semanas,
        por_cat=dict(sorted(por_cat.items(), key=lambda x: x[1], reverse=True)),
        por_cat_items=dict(por_cat_items),
        receita_ifood=receita_ifood, receita_cartao=receita_cartao, receita_outras=receita_outras,
        lancamentos=lancamentos,
        meses=db.buscar_meses_importados(),
        pendentes_count=pendentes_count,
        todas_categorias=todas_categorias,
        categorias_entrada=categorias_entrada,
        fmt=fmt,
    )

# ── EXCLUIR LANÇAMENTO ────────────────────────────────────────────────────────

@app.route("/excluir/<int:lancamento_id>", methods=["POST"])
@login_required
def excluir(lancamento_id):
    mes = int(request.form["mes"])
    ano = int(request.form["ano"])
    db.excluir_lancamento(lancamento_id)
    return redirect(url_for("dashboard", mes=mes, ano=ano))

# ── EXCLUIR MÊS ───────────────────────────────────────────────────────────────

@app.route("/excluir_mes/<int:mes>/<int:ano>", methods=["POST"])
@login_required
def excluir_mes(mes, ano):
    db.excluir_mes(mes, ano)
    flash(f"Extrato de {MESES_NOME.get(mes, str(mes))}/{ano} excluído com sucesso.", "success")
    return redirect(url_for("index"))

# ── HISTÓRICO ─────────────────────────────────────────────────────────────────

@app.route("/historico")
@login_required
def historico():
    dados = db.buscar_historico_dre()
    meses = db.buscar_meses_importados()
    return render_template("historico.html", dados=dados, meses=meses, fmt=fmt)

# ── MEMÓRIA ───────────────────────────────────────────────────────────────────

@app.route("/memoria")
@login_required
def memoria():
    items = db.listar_memoria()
    meses = db.buscar_meses_importados()
    return render_template("memoria.html", items=items, meses=meses, fmt=fmt)

@app.route("/memoria/excluir/<descricao_norm>", methods=["POST"])
@login_required
def excluir_memoria(descricao_norm):
    db.excluir_memoria(descricao_norm)
    return redirect(url_for("memoria"))

# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/lancamentos/<int:mes>/<int:ano>")
@login_required
def api_lancamentos(mes, ano):
    return jsonify(db.buscar_lancamentos(mes, ano))

@app.route("/api/categoria", methods=["POST"])
@login_required
def api_atualizar_categoria():
    data = request.get_json()
    lid = int(data["id"])
    fields = {"status": "confirmado"}
    if "categoria" in data:
        fields["categoria"] = data["categoria"]
        db.salvar_memoria(data.get("descricao", ""), data["categoria"])
    if "subcategoria" in data:
        fields["subcategoria"] = data["subcategoria"]
    db.atualizar_lancamento(lid, fields)
    return jsonify({"ok": True})

@app.route("/api/categoria_nova", methods=["POST"])
@login_required
def api_categoria_nova():
    data = request.get_json()
    nome = data.get("nome", "").strip()
    tipo = data.get("tipo", "saida")
    if nome:
        db.salvar_categoria_custom(nome, tipo)
        return jsonify({"ok": True, "nome": nome, "tipo": tipo})
    return jsonify({"ok": False}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
