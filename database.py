"""
Banco de dados — Marmita do Engenheiro.
Usa Postgres (Neon), via psycopg2.
Requer variável de ambiente: DATABASE_URL.
"""
import os
import unicodedata
from contextlib import contextmanager
from datetime import datetime

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_cthlV8wH2gYN@ep-lingering-moon-ax09g9w5.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require")


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
                descricao_norm  TEXT,
                descricao_orig  TEXT,
                categoria       TEXT,
                mes_efetivo     INTEGER,
                ano_efetivo     INTEGER,
                atualizado_em   TEXT
            )
        """)
        # Migração: memória passa a ser versionada por mês/ano de vigência —
        # bancos antigos tinham só um valor global (unique por descricao_norm).
        # Garante as colunas novas, faz backfill das linhas antigas para valerem
        # "desde sempre" (01/2000) e troca a constraint de unicidade.
        cur.execute("ALTER TABLE memoria_classificacoes ADD COLUMN IF NOT EXISTS mes_efetivo INTEGER")
        cur.execute("ALTER TABLE memoria_classificacoes ADD COLUMN IF NOT EXISTS ano_efetivo INTEGER")
        cur.execute("UPDATE memoria_classificacoes SET mes_efetivo = 1, ano_efetivo = 2000 WHERE mes_efetivo IS NULL")
        cur.execute("ALTER TABLE memoria_classificacoes DROP CONSTRAINT IF EXISTS memoria_classificacoes_descricao_norm_key")
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS memoria_desc_efetivo_idx
            ON memoria_classificacoes (descricao_norm, mes_efetivo, ano_efetivo)
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
# A memória é versionada por mês/ano de vigência: cada correção feita pelo
# usuário fica associada ao mês/ano do lançamento que originou a correção.
# Ao aplicar memória num extrato importado para o mês M, usamos a entrada mais
# recente cuja vigência seja <= M — assim, meses anteriores ao da correção
# continuam com a categorização antiga, e meses posteriores já usam a nova.

def salvar_memoria(descricao: str, categoria: str, mes: int, ano: int):
    dn = _norm(descricao)
    with _cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO memoria_classificacoes
                (descricao_norm, descricao_orig, categoria, mes_efetivo, ano_efetivo, atualizado_em)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (descricao_norm, mes_efetivo, ano_efetivo) DO UPDATE
            SET descricao_orig = EXCLUDED.descricao_orig,
                categoria = EXCLUDED.categoria,
                atualizado_em = EXCLUDED.atualizado_em
        """, (dn, descricao, categoria, mes, ano, datetime.now().isoformat()))


def buscar_memoria(mes: int, ano: int) -> dict:
    """Retorna a memória vigente para o mês/ano informado: para cada descrição,
    a correção mais recente com vigência <= (ano, mes)."""
    with _cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (descricao_norm) descricao_norm, categoria
            FROM memoria_classificacoes
            WHERE (ano_efetivo, mes_efetivo) <= (%s, %s)
            ORDER BY descricao_norm, ano_efetivo DESC, mes_efetivo DESC
        """, (ano, mes))
        rows = cur.fetchall()
    return {r["descricao_norm"]: r["categoria"] for r in rows}


def listar_memoria() -> list:
    """Lista a classificação vigente (mais recente) de cada descrição —
    é o que será aplicado a partir de agora nos próximos meses."""
    with _cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (descricao_norm) *
            FROM memoria_classificacoes
            ORDER BY descricao_norm, ano_efetivo DESC, mes_efetivo DESC, atualizado_em DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def excluir_memoria(descricao_norm: str):
    """Remove todo o histórico de correções dessa descrição (reset completo)."""
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


def inserir_lancamento_manual(dia: int, mes: int, ano: int, tipo: str, descricao: str,
                               valor: float, categoria: str, subcategoria: str = "") -> int:
    """Insere um lancamento manual (dinheiro em especie) para um mes ja importado.
    Diferente de salvar_lancamentos, NAO apaga os lancamentos existentes do mes -
    apenas adiciona um novo. Marcado com tipo_mov='especie' para diferenciar dos
    lancamentos vindos do extrato bancario."""
    with _cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO lancamentos
                (dia, mes, ano, tipo, descricao, valor, categoria, subcategoria, status, tipo_mov, raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'confirmado','especie','Lançamento manual em espécie')
            RETURNING id
        """, (dia, mes, ano, tipo, descricao, valor, categoria, subcategoria))
        row = cur.fetchone()
        return row["id"] if row else None


def buscar_lancamento(lancamento_id: int):
    with _cursor() as cur:
        cur.execute("SELECT * FROM lancamentos WHERE id = %s", (lancamento_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def atualizar_categoria(lancamento_id: int, categoria: str, descricao: str):
    lanc = buscar_lancamento(lancamento_id)
    with _cursor(commit=True) as cur:
        cur.execute("""
            UPDATE lancamentos SET categoria = %s, status = 'confirmado' WHERE id = %s
        """, (categoria, lancamento_id))
    if lanc:
        salvar_memoria(descricao, categoria, lanc["mes"], lanc["ano"])


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
    from categorizador import CMV_CATS, CMO_CATS, PROLABORE_CATS, INVESTIMENTOS_CATS
    meses = buscar_meses_importados()
    historico = []
    for m in meses:
        rows = buscar_lancamentos(m["mes"], m["ano"])
        _excluir = CMV_CATS | CMO_CATS | PROLABORE_CATS | INVESTIMENTOS_CATS
        receita = sum(r["valor"] for r in rows if r["tipo"] == "entrada" and r["status"] != "ignorado")
        cmv     = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] in CMV_CATS)
        cmo     = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] in CMO_CATS)
        pl      = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] in PROLABORE_CATS)
        inv     = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] in INVESTIMENTOS_CATS)
        cf      = sum(r["valor"] for r in rows if r["tipo"] == "saida" and r["categoria"] not in _excluir)
        ll      = receita - cmv - cmo - pl - cf
        fc      = ll - inv
        historico.append({
            "mes": m["mes"], "ano": m["ano"],
            "label": f"{['','Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'][m['mes']]}/{str(m['ano'])[2:]}",
            "receita": receita, "cmv": cmv, "cmo": cmo, "prolabore": pl, "cf": cf,
            "lucro": ll,
            "pct_lucro": round(ll / receita * 100, 1) if receita else 0,
            "investimentos": inv,
            "fundo_caixa": fc,
            "pct_fundo_caixa": round(fc / receita * 100, 1) if receita else 0,
        })
    return list(reversed(historico))
