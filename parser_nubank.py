"""Parser do extrato PDF do Nubank — Marmitaria do Engenheiro."""
import pdfplumber
import re
from dataclasses import dataclass

MESES = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12
}

@dataclass
class Transacao:
    dia: int; mes: int; ano: int
    tipo: str        # "saida" | "entrada"
    descricao: str; valor: float
    tipo_mov: str    # "pix_enviado" | "pix_recebido" | "debito" | "boleto" | "reembolso"
    raw: str = ""

RE_DATA       = re.compile(r'^(\d{2})\s+(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s+(\d{4})', re.IGNORECASE)
RE_VALOR_FIM  = re.compile(r'([\d]+(?:\.[\d]{3})*,[\d]{2})\s*$')
RE_INICIO_MOV = re.compile(r'^(Transferência enviada|Transferência recebida|Transferência Recebida|Compra no débito|Pagamento de boleto|Reembolso recebido)')

IGNORAR_SUBSTRINGS = [
    "Tem alguma dúvida", "Caso a solução", "Extrato gerado",
    "Total de entradas", "Total de saídas", "Saldo do dia",
    "Saldo inicial", "Saldo final", "Rendimento líquido",
    "CNPJ 60.004.242", "Agência 0001 Conta",
    "VALORES EM R$", "Movimentações",
    "Nu Financeira", "Nu Pagamentos S.A. -",
    "O saldo líquido", "Não nos responsabilizamos", "Asseguramos",
    "metropolitanas)", "0800 591", "4020 0185", "Atendimento 24h",
    "disponíveis em nubank", "ouvidoria",
    "CNPJ: 18.236", "CNPJ: 30.680",
]
IGNORAR_EXATOS = {"LOUISE LIMA LTDA"}

def _linha_ignorar(linha: str) -> bool:
    if not linha.strip():
        return True
    if linha.strip() in IGNORAR_EXATOS:
        return True
    return any(sub in linha for sub in IGNORAR_SUBSTRINGS)

def _extrair_descricao(raw: str) -> str:
    prefixos = [
        "Transferência enviada pelo Pix ",
        "Transferência recebida pelo Pix ",
        "Transferência Recebida ",
        "Compra no débito ",
        "Pagamento de boleto efetuado ",
        "Reembolso recebido pelo Pix ",
    ]
    t = raw
    for p in prefixos:
        if t.startswith(p):
            t = t[len(p):]
            break
    t = re.sub(r'\s*-\s*•{3}\.\d{3}\.\d{3}-••.*$', '', t)
    t = re.sub(r'\s*-\s*\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}.*$', '', t)
    bancos = r'(BCO |BANCO |NU PAGAMENTOS|PICPAY|NEON PAG|CAIXA ECON|ITAÚ UNI|MERCADO PAGO|EBANX|COOP SICRE|STONE IP|IFOOD PAGO|INTER \(|BRADESCO|SANTANDER)'
    t = re.sub(r'\s*-\s*' + bancos + r'.*$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^\d{2}\.\d{3}\.\d{3}/?\d{0,4}-?\d{0,2}\s+', '', t)
    t = re.sub(r'\s*[\d]+(?:\.[\d]{3})*,[\d]{2}\s*$', '', t)
    return t.strip()

def extrair_transacoes(pdf_path: str) -> list:
    linhas = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            texto = page.extract_text()
            if texto:
                linhas.extend(texto.split("\n"))

    transacoes = []
    dia_atual = mes_atual = ano_atual = None
    i = 0

    while i < len(linhas):
        linha = linhas[i].strip()
        m = RE_DATA.match(linha)
        if m:
            dia_atual = int(m.group(1))
            mes_atual = MESES[m.group(2).upper()]
            ano_atual = int(m.group(3))
            i += 1
            continue

        if _linha_ignorar(linha) or dia_atual is None or not RE_INICIO_MOV.match(linha):
            i += 1
            continue

        if linha.startswith("Transferência enviada"):
            tipo_mov, tipo = "pix_enviado", "saida"
        elif linha.startswith("Transferência recebida") or linha.startswith("Transferência Recebida"):
            tipo_mov, tipo = "pix_recebido", "entrada"
        elif linha.startswith("Compra no débito"):
            tipo_mov, tipo = "debito", "saida"
        elif linha.startswith("Pagamento de boleto"):
            tipo_mov, tipo = "boleto", "saida"
        else:
            tipo_mov, tipo = "reembolso", "entrada"

        linhas_mov = [linha]
        valor = None
        m_val = RE_VALOR_FIM.search(linha)
        if m_val:
            valor = float(m_val.group(1).replace(".", "").replace(",", "."))
            i += 1
        else:
            j = i + 1
            while j < len(linhas):
                prox = linhas[j].strip()
                if RE_DATA.match(prox) or RE_INICIO_MOV.match(prox):
                    break
                if not _linha_ignorar(prox):
                    linhas_mov.append(prox)
                    m_val = RE_VALOR_FIM.search(prox)
                    if m_val:
                        valor = float(m_val.group(1).replace(".", "").replace(",", "."))
                        j += 1
                        break
                j += 1
            i = j

        if valor is None:
            continue

        raw = " ".join(linhas_mov)
        transacoes.append(Transacao(
            dia=dia_atual, mes=mes_atual, ano=ano_atual,
            tipo=tipo, descricao=_extrair_descricao(raw),
            valor=valor, tipo_mov=tipo_mov, raw=raw
        ))

    return transacoes
