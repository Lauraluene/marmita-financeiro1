"""Motor de categorização — Marmitaria do Engenheiro."""
import unicodedata
import re
from dataclasses import dataclass
from typing import Optional

MESES_NOME = {
    1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",
    7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"
}

# ── CATEGORIAS DE SAÍDAS ──────────────────────────────────────────────────────
CATEGORIAS_SAIDAS = {
    "Gás": ["ivan", "ivangas"],
    "Motoboys / Entregas": [
        "ronnan araujo","adam holanda","claudio roberto lopes",
        "julio cesar veras","renato gomes","ayale","arnold lopes torres",
        "marcelo vinicius pinto","kilmer richard","daniel vinicius silva ferreira",
        "marcos paulo nascimento","antonio silva dos santos","antônio silva dos santos",
        "gabriel frazao","gabriel frazão","joao damasceno","wanderson do nascimento",
        "adonias dos santos","arthur lopes torres","amanda kammily",
        "wellington silva viegas","fabiano da silva silva",
        "kayro eduardo da silva oliveira","vinicius henrique do nascimento",
        "luis carlos viegas","brayan rodrigues soares",
        "jonas fernandes de sousa neto","angeliky paula piedade sodre",
        "luis vitor andrade dos reis","julio cesar veras aleixo",
    ],
    "Salários": [
        "robson dos santos ferreira","aurideia santos ferreira","leidiane abreu moraes",
        "parizalda de jesus alves reis",
    ],
    "Diaristas": [
        "bruna bianca mendes ribeiro","shara","leonardo henrique borges da silva",
        "jeruzalena candeira","raquel costa do nascimento","juliana tavares andrade",
        "gabriel pinto farias",
    ],
    "Supermercado": [
        "armazem mateus","assai","assaí","emporio oriental","mcj supermercados",
        "l d a com gener aliment","mateus food","mateus supermercad",
        "comercial dio","emporio turu","emporio cohama","supermercados sao luis","spazio mateus",
    ],
    "Fornecedor de Proteínas": [
        "regiane de j p pereira comercio","regiane frigorifico","regiane frigorífico",
        "g borges branco comercio","c. a. cantanhede filho","a dos s inocentes",
        "ind de lat buriti","distribuidora e comercio rr",
    ],
    "Hortifruti": ["g s coelho comercio","gs coelho"],
    "Embalagens": ["m f franco matos","ilha plastic","plastik","plasticos maranhense"],
    "Pró-labore": [
        "louise luene holanda cutrim","louise luene",
        "erica maria silva lima","rosinete dos santos costa",
        "catharina nogueira santos","rhayane millena franca rabelo",
        "grafica dunas","gráfica dunas","hortix","okeo armazem","okeo",
        "amazon.com.br","amazon","shpp brasil","jim.com","pix marketplace",
        "fundacao assistencial servidores","fundação assistencial","alergocenter",
        "pagar me pagamentos","pagar.me","l e l hamburgeria","burguer do engenheiro",
        "vilaide holanda","hot in box pizza","pink concept","arabian grill",
        "frosty parque","realize credito","ifood.com agencia","col servicos",
        "dlknet","potiguar cohama","a. faria de m. rangel","lushe","fouet e afeto",
        "djanira presentes","franciane leite","orquideapresentes","panificadorapaes",
        "midway","rd saude","raia drogasil","vitta job",
    ],
    "Contabilidade": ["mesquita e cruz","mesquita cruz"],
    "Impostos": ["das-simples nacional","das simples","prefeitura sao luis","prefeitura são luis","receita federal"],
    "FGTS": ["cef matriz"],
    "Manutenção": ["adirson soeiro costa","wagner roberto ribeiro"],
    "Troco": [
        "marcela alves costa","arena do iphone","keyth shayanne","clara damiana",
        "karine pereira de jesus","conceicao de maria pires","anna paula santalucia",
        "marinete de fatima abreu","clauber herlano silva nery",
    ],
    "Outros / Diversos": ["claro pay","himacol material","bagatela papelarias"],
}

# ── ENTRADAS ──────────────────────────────────────────────────────────────────
IGNORAR_ENTRADAS = [
    "louise l holanda cutrim","louise luene holanda cutrim","louise luene lima",
]
FONTES_IFOOD  = ["ifood pago ip","ifood"]
FONTES_CARTAO = ["stone ip","marmita do engenheiro"]
LL_CNPJ = "35.390.952"

# DRE
CMV_CATS       = {"Supermercado","Fornecedor de Proteínas","Hortifruti","Embalagens","Gás"}
CMO_CATS       = {"Motoboys / Entregas","Salários","Diaristas"}
PROLABORE_CATS = {"Pró-labore"}
CF_CATS        = {"Contabilidade","Impostos","FGTS","Manutenção","Troco","Outros / Diversos"}

# ── HELPERS ───────────────────────────────────────────────────────────────────
def norm(t: str) -> str:
    t = t.lower().strip()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

def match_saida(desc: str) -> Optional[str]:
    dn = norm(desc)
    for cat, palavras in CATEGORIAS_SAIDAS.items():
        for p in palavras:
            if norm(p) in dn:
                return cat
    return None

def faixa_valor(valor: float, tipo_mov: str) -> tuple:
    if tipo_mov != "pix_enviado":
        return "Outros / Diversos", "pendente"
    if valor < 60:
        return "Troco", "auto"
    elif valor <= 150:
        return "Outros / Diversos", "pendente"
    else:
        return "Pró-labore", "pendente"

def classificar_entrada(desc: str, tipo_mov: str, raw: str) -> tuple:
    dn = norm(desc)
    rn = norm(raw)
    for nome in IGNORAR_ENTRADAS:
        if norm(nome) in dn:
            return "ignorado", "ignorado"
    if LL_CNPJ in raw:
        return "ignorado", "ignorado"
    if tipo_mov == "reembolso":
        return "ignorado", "ignorado"
    for f in FONTES_IFOOD:
        if norm(f) in rn:
            return "iFood", "auto"
    for f in FONTES_CARTAO:
        if norm(f) in rn:
            return "Cartão", "auto"
    return "Outras", "auto"

# ── DATACLASS ─────────────────────────────────────────────────────────────────
@dataclass
class Lancamento:
    dia: int; mes: int; ano: int
    tipo: str; descricao: str; valor: float
    categoria: str; subcategoria: str; status: str
    tipo_mov: str; raw: str = ""; id: int = None

    @property
    def mes_nome(self):
        return MESES_NOME.get(self.mes, str(self.mes))

    def to_dict(self):
        return {
            "dia": self.dia, "mes": self.mes, "ano": self.ano,
            "mes_nome": self.mes_nome, "tipo": self.tipo,
            "descricao": self.descricao, "valor": self.valor,
            "categoria": self.categoria, "subcategoria": self.subcategoria,
            "status": self.status, "tipo_mov": self.tipo_mov,
        }

# ── CATEGORIZAÇÃO ─────────────────────────────────────────────────────────────
def categorizar(transacoes: list) -> list:
    resultado = []
    for t in transacoes:
        if t.tipo == "entrada":
            sub, status = classificar_entrada(t.descricao, t.tipo_mov, t.raw)
            resultado.append(Lancamento(
                dia=t.dia, mes=t.mes, ano=t.ano, tipo="entrada",
                descricao=t.descricao, valor=t.valor,
                categoria="Ignorado" if status == "ignorado" else "Receita",
                subcategoria=sub, status=status,
                tipo_mov=t.tipo_mov, raw=t.raw
            ))
        else:
            cat = match_saida(t.descricao)
            if cat:
                status = "auto"
            else:
                cat, status = faixa_valor(t.valor, t.tipo_mov)
            resultado.append(Lancamento(
                dia=t.dia, mes=t.mes, ano=t.ano, tipo="saida",
                descricao=t.descricao, valor=t.valor,
                categoria=cat, subcategoria="", status=status,
                tipo_mov=t.tipo_mov, raw=t.raw
            ))
    return resultado

# ── DRE ───────────────────────────────────────────────────────────────────────
def calcular_dre(lancamentos: list) -> dict:
    receitas = [l for l in lancamentos if l.tipo == "entrada" and l.status != "ignorado"]
    saidas   = [l for l in lancamentos if l.tipo == "saida"   and l.status != "ignorado"]
    rb  = sum(l.valor for l in receitas)
    cmv = sum(l.valor for l in saidas if l.categoria in CMV_CATS)
    cmo = sum(l.valor for l in saidas if l.categoria in CMO_CATS)
    pl  = sum(l.valor for l in saidas if l.categoria in PROLABORE_CATS)
    # CF = tudo que não é CMV, CMO ou Pró-labore (inclui categorias personalizadas automaticamente)
    _excluir = CMV_CATS | CMO_CATS | PROLABORE_CATS
    cf  = sum(l.valor for l in saidas if l.categoria not in _excluir)
    mb  = rb - cmv
    mc  = mb - cmo
    ll  = mc - pl - cf
    return {
        "receita_bruta": rb,
        "cmv": cmv,
        "margem_bruta": mb,
        "pct_margem_bruta": (mb / rb * 100) if rb else 0,
        "cmo": cmo,
        "margem_contrib": mc,
        "pct_margem_contrib": (mc / rb * 100) if rb else 0,
        "prolabore": pl,
        "custo_fixo": cf,
        "lucro_liquido": ll,
        "pct_margem_liquida": (ll / rb * 100) if rb else 0,
    }

# ── RECEITAS POR SEMANA ───────────────────────────────────────────────────────
def receitas_por_semana(lancamentos: list) -> list:
    semanas = [{"sem": f"Sem {i}", "dias": d, "Cartão": 0, "iFood": 0, "Espécie": 0, "Outras": 0}
               for i, d in enumerate(["1-7","8-14","15-21","22-28","29-31"], 1)]

    def semana_idx(dia):
        if dia <= 7:   return 0
        if dia <= 14:  return 1
        if dia <= 21:  return 2
        if dia <= 28:  return 3
        return 4

    for l in lancamentos:
        if l.tipo == "entrada" and l.status not in ("ignorado",) and l.subcategoria in ("Cartão","iFood","Espécie","Outras"):
            idx = semana_idx(l.dia)
            semanas[idx][l.subcategoria] += l.valor

    return semanas
