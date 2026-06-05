"""
Banco de dados — Marmita do Engenheiro.
Usa a API REST do Supabase (sem necessidade de senha do banco).
Requer variáveis de ambiente: SUPABASE_URL e SUPABASE_KEY.
"""
import os
import unicodedata
import json
import urllib.request
import urllib.parse
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fjizzwlozsryucrdnfps.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def _headers(extra=None):
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h

def _get(table, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def _post(table, data, prefer="return=minimal"):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body,
          headers=_headers({"Prefer": prefer}), method="POST")
    with urllib.request.urlopen(req) as r:
        resp = r.read()
        return json.loads(resp) if resp else []

def _patch(table, filters, data):
    qs = "&".join(f"{k}=eq.{urllib.parse.quote(str(v))}" for k, v in filters.items())
    url = f"{SUPABASE_URL}/rest/v1/{table}?{qs}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body,
          headers=_headers({"Prefer": "return=minimal"}), method="PATCH")
    with urllib.request.urlopen(req) as r:
        r.read()

def _delete(table, filters):
    qs = "&".join(f"{k}=eq.{urllib.parse.quote(str(v))}" for k, v in filters.items())
    url = f"{SUPABASE_URL}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers=_headers(), method="DELETE")
    with urllib.request.urlopen(req) as r:
        r.read()

def _upsert(table, data, on_conflict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body,
          headers=_headers({
              "Prefer": f"resolution=merge-duplicates,return=minimal",
              "Content-Type": "application/json"
          }), method="POST")
    # Adiciona on_conflict como query param
    url += f"?on_conflict={on_conflict}"
    req = urllib.request.Request(url, data=body,
          headers=_headers({
              "Prefer": "resolution=merge-duplicates,return=minimal"
          }), method="POST")
    with urllib.request.urlopen(req) as r:
        r.read()

# ── INIT ─────────────────────────────────────────────────────────────────────

def init_db():
    """No Supabase as tabelas já existem — não precisa fazer nada."""
    pass

# ── HELPERS ──────────────────────────────────────────────────────────────────

def _norm(t: str) -> str:
    t = t.lower().strip()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

# ── MEMÓRIA DE CLASSIFICAÇÕES ─────────────────────────────────────────────────

def salvar_memoria(descricao: str, categoria: str):
    dn = _norm(descricao)
    _upsert("memoria_classificacoes", {
        "descricao_norm": dn,
        "descricao_orig": descricao,
        "categoria": categoria,
        "atualizado_em": datetime.now().isoformat()
    }, "descricao_norm")

def buscar_memoria() -> dict:
    rows = _get("memoria_classificacoes", {"select": "descricao_norm,categoria"})
    return {r["descricao_norm"]: r["categoria"] for r in rows}

def listar_memoria() -> list:
    return _get("memoria_classificacoes", {
        "select": "*",
        "order": "atualizado_em.desc"
    })

def excluir_memoria(descricao_norm: str):
    _delete("memoria_classificacoes", {"descricao_norm": descricao_norm})

# ── CATEGORIAS PERSONALIZADAS ─────────────────────────────────────────────────

def salvar_categoria_custom(nome: str):
    nome = nome.strip()
    if not nome:
        return
    _upsert("categorias_custom", {"nome": nome}, "nome")

def buscar_categorias_custom() -> list:
    rows = _get("categorias_custom", {"select": "nome", "order": "nome"})
    return [r["nome"] for r in rows]

# ── LANÇAMENTOS ───────────────────────────────────────────────────────────────

def salvar_lancamentos(lancamentos: list, mes: int, ano: int):
    # Deletar existentes
    url = f"{SUPABASE_URL}/rest/v1/lancamentos?mes=eq.{mes}&ano=eq.{ano}"
    req = urllib.request.Request(url, headers=_headers(), method="DELETE")
    with urllib.request.urlopen(req) as r:
        r.read()

    url2 = f"{SUPABASE_URL}/rest/v1/meses_importados?mes=eq.{mes}&ano=eq.{ano}"
    req2 = urllib.request.Request(url2, headers=_headers(), method="DELETE")
    with urllib.request.urlopen(req2) as r:
        r.read()

    # Inserir lançamentos
    if lancamentos:
        rows = [{
            "dia": l.dia, "mes": l.mes, "ano": l.ano,
            "tipo": l.tipo, "descricao": l.descricao, "valor": l.valor,
            "categoria": l.categoria, "subcategoria": l.subcategoria,
            "status": l.status, "tipo_mov": l.tipo_mov, "raw": l.raw
        } for l in lancamentos]
        _post("lancamentos", rows)

    # Registrar mês
    _upsert("meses_importados", {
        "mes": mes, "ano": ano,
        "importado_em": datetime.now().isoformat()
    }, "mes,ano")

def atualizar_categoria(lancamento_id: int, categoria: str, descricao: str):
    _patch("lancamentos", {"id": lancamento_id}, {
        "categoria": categoria,
        "status": "confirmado"
    })
    salvar_memoria(descricao, categoria)

def atualizar_lancamento(lancamento_id: int, fields: dict):
    """Atualiza campos arbitrários de um lançamento."""
    _patch("lancamentos", {"id": lancamento_id}, fields)

def excluir_lancamento(lancamento_id: int):
    _delete("lancamentos", {"id": lancamento_id})

def excluir_mes(mes: int, ano: int):
    url = f"{SUPABASE_URL}/rest/v1/lancamentos?mes=eq.{mes}&ano=eq.{ano}"
    req = urllib.request.Request(url, headers=_headers(), method="DELETE")
    with urllib.request.urlopen(req) as r:
        r.read()
    url2 = f"{SUPABASE_URL}/rest/v1/meses_importados?mes=eq.{mes}&ano=eq.{ano}"
    req2 = urllib.request.Request(url2, headers=_headers(), method="DELETE")
    with urllib.request.urlopen(req2) as r:
        r.read()

def buscar_lancamentos(mes: int = None, ano: int = None) -> list:
    params = {"select": "*", "order": "dia.asc,id.asc"}
    if mes and ano:
        params["mes"] = f"eq.{mes}"
        params["ano"] = f"eq.{ano}"
    return _get("lancamentos", params)

def buscar_meses_importados() -> list:
    return _get("meses_importados", {
        "select": "mes,ano,importado_em",
        "order": "ano.desc,mes.desc"
    })

def buscar_pendentes(mes: int, ano: int) -> list:
    return _get("lancamentos", {
        "select": "*",
        "mes": f"eq.{mes}",
        "ano": f"eq.{ano}",
        "status": "eq.pendente",
        "order": "dia.asc"
    })

def buscar_historico_dre() -> list:
    from categorizador import CMV_CATS, CMO_CATS, PROLABORE_CATS
    meses = buscar_meses_importados()
    historico = []
    for m in meses:
        rows = buscar_lancamentos(m["mes"], m["ano"])
        _excluir = CMV_CATS | CMO_CATS | PROLABORE_CATS
        receita = sum(r["valor"] for r in rows if r["tipo"] == "entrada" and r["status"] != "ignorado")
        cmv     = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] in CMV_CATS)
        cmo     = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] in CMO_CATS)
        pl      = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] in PROLABORE_CATS)
        cf      = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] not in _excluir)
        ll      = receita - cmv - cmo - pl - cf
        historico.append({
            "mes": m["mes"], "ano": m["ano"],
            "label": f"{['','Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'][m['mes']]}/{str(m['ano'])[2:]}",
            "receita": receita, "cmv": cmv, "cmo": cmo, "prolabore": pl, "cf": cf,
            "lucro": ll,
            "pct_lucro": round(ll / receita * 100, 1) if receita else 0,
        })
    return list(reversed(historico))
