"""
Banco de dados — Marmita do Engenheiro.
Usa Postgres nativo (Railway), via psycopg2.
Requer variável de ambiente: DATABASE_URL.
"""
import os
import unicodedata
from contextlib import contextmanager
from datetime import datetime

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _conn_url():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


@contextmanager
def _cursor(commit=False):
    conn = psycopg2.connect(_conn_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()


# ── INIT ─────────────────────────────────────────────────────────────────────

def init_db():
    """Cria as tabelas se ainda não existirem."""
    with _cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lancamentos (
                id           SERIAL PRIMARY KEY,
                dia          INTEGER, mes INTEGER, ano INTEGER,
                tipo         TEXT, descricao TEXT, valor REAL,
                categoria    TEXT, subcategoria TEXT,
                status       TEXT, tipo_mov TEXT, raw TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meses_importados (
                id           SERIAL PRIMARY KEY,
                mes INTEGER, ano INTEGER, importado_em TEXT,
                UNIQUE(mes, ano)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS memoria_classificacoes (
                id              SERIAL PRIMARY KEY,
                descricao_norm  TEXT UNIQUE,
                descricao_orig  TEXT,
                categoria       TEXT,
                atualizado_em   TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categorias_custom (
                id   SERIAL PRIMARY KEY,
                nome TEXT UNIQUE
            )
        """)
        # Tabela pode ter sido criada antes da coluna 'tipo' existir (banco original do Railway) — garante que existe.
        cur.execute("""
            ALTER TABLE categorias_custom ADD COLUMN IF NOT EXISTS tipo TEXT DEFAULT 'saida'
        """)


# ── HELPERS ──────────────────────────────────────────────────────────────────

def _norm(t: str) -> str:
    t = t.lower().strip()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# ── MEMÓRIA DE CLASSIFICAÇÕES ─────────────────────────────────────────────────

def salvar_memoria(descricao: str, categoria: str):
    dn = _norm(descricao)
    with _cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO memoria_classificacoes (descricao_norm, descricao_orig, categoria, atualizado_em)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (descricao_norm) DO UPDATE
            SET descricao_orig = EXCLUDED.descricao_orig,
                categoria = EXCLUDED.categoria,
                atualizado_em = EXCLUDED.atualizado_em
        """, (dn, descricao, categoria, datetime.now().isoformat()))


def buscar_memoria() -> dict:
    with _cursor() as cur:
        cur.execute("SELECT descricao_norm, categoria FROM memoria_classificacoes")
        rows = cur.fetchall()
    return {r["descricao_norm"]: r["categoria"] for r in rows}


def listar_memoria() -> list:
    with _cursor() as cur:
        cur.execute("SELECT * FROM memoria_classificacoes ORDER BY atualizado_em DESC")
        return [dict(r) for r in cur.fetchall()]


def excluir_memoria(descricao_norm: str):
    with _cursor(commit=True) as cur:
        cur.execute("DELETE FROM memoria_classificacoes WHERE descricao_norm = %s", (descricao_norm,))


# ── CATEGORIAS PERSONALIZADAS ─────────────────────────────────────────────────

def salvar_categoria_custom(nome: str, tipo: str = "saida"):
    nome = nome.strip()
    if not nome:
        return
    with _cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO categorias_custom (nome, tipo) VALUES (%s, %s)
            ON CONFLICT (nome) DO UPDATE SET tipo = EXCLUDED.tipo
        """, (nome, tipo))


def buscar_categorias_custom(tipo: str = "saida") -> list:
    with _cursor() as cur:
        cur.execute("SELECT nome, tipo FROM categorias_custom ORDER BY nome")
        rows = cur.fetchall()
    return [r["nome"] for r in rows if (r.get("tipo") or "saida") == tipo]


# ── LANÇAMENTOS ───────────────────────────────────────────────────────────────

def salvar_lancamentos(lancamentos: list, mes: int, ano: int):
    with _cursor(commit=True) as cur:
        cur.execute("DELETE FROM lancamentos WHERE mes = %s AND ano = %s", (mes, ano))
        cur.execute("DELETE FROM meses_importados WHERE mes = %s AND ano = %s", (mes, ano))

        if lancamentos:
            for l in lancamentos:
                cur.execute("""
                    INSERT INTO lancamentos
                        (dia, mes, ano, tipo, descricao, valor, categoria, subcategoria, status, tipo_mov, raw)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (l.dia, l.mes, l.ano, l.tipo, l.descricao, l.valor,
                      l.categoria, l.subcategoria, l.status, l.tipo_mov, l.raw))

        cur.execute("""
            INSERT INTO meses_importados (mes, ano, importado_em) VALUES (%s, %s, %s)
            ON CONFLICT (mes, ano) DO UPDATE SET importado_em = EXCLUDED.importado_em
        """, (mes, ano, datetime.now().isoformat()))


def atualizar_categoria(lancamento_id: int, categoria: str, descricao: str):
    with _cursor(commit=True) as cur:
        cur.execute("""
            UPDATE lancamentos SET categoria = %s, status = 'confirmado' WHERE id = %s
        """, (categoria, lancamento_id))
    salvar_memoria(descricao, categoria)


def atualizar_lancamento(lancamento_id: int, fields: dict):
    """Atualiza campos arbitrários de um lançamento."""
    if not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields.keys())
    valores = list(fields.values()) + [lancamento_id]
    with _cursor(commit=True) as cur:
        cur.execute(f"UPDATE lancamentos SET {sets} WHERE id = %s", valores)


def excluir_lancamento(lancamento_id: int):
    with _cursor(commit=True) as cur:
        cur.execute("DELETE FROM lancamentos WHERE id = %s", (lancamento_id,))


def excluir_mes(mes: int, ano: int):
    with _cursor(commit=True) as cur:
        cur.execute("DELETE FROM lancamentos WHERE mes = %s AND ano = %s", (mes, ano))
        cur.execute("DELETE FROM meses_importados WHERE mes = %s AND ano = %s", (mes, ano))


def buscar_lancamentos(mes: int = None, ano: int = None) -> list:
    with _cursor() as cur:
        if mes and ano:
            cur.execute("""
                SELECT * FROM lancamentos WHERE mes = %s AND ano = %s ORDER BY dia ASC, id ASC
            """, (mes, ano))
        else:
            cur.execute("SELECT * FROM lancamentos ORDER BY dia ASC, id ASC")
        return [dict(r) for r in cur.fetchall()]


def buscar_meses_importados() -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT mes, ano, importado_em FROM meses_importados ORDER BY ano DESC, mes DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def buscar_pendentes(mes: int, ano: int) -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT * FROM lancamentos
            WHERE mes = %s AND ano = %s AND status = 'pendente'
            ORDER BY dia ASC
        """, (mes, ano))
        return [dict(r) for r in cur.fetchall()]


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
