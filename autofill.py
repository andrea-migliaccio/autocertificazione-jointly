#!/usr/bin/env python3

"""
Compila automaticamente un PDF di autocertificazione
estraendo i dati da una ricevuta PDF testuale e sovrapponendo
testo alle coordinate dei placeholder.

Uso:

    python autofill.py ricevuta.pdf template.pdf

Dipendenze:

    pip install pdfplumber openai pypdf python-dotenv reportlab pydantic

Variabili ambiente richieste:

    OPENAI_API_KEY=...
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime
from typing import Optional

import pdfplumber
from openai import OpenAI
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config(path: str = CONFIG_PATH) -> dict:
    """Carica la configurazione da file JSON."""
    if not os.path.exists(path):
        print(f"ERRORE: File di configurazione non trovato: {path}")
        print("Creare un file config.json con i dati del dichiarante e dei familiari.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

CFG = load_config()

MODEL = CFG.get("modello_openai", "gpt-4o")

DICHIARANTE_NOME = CFG["dichiarante"]["nome"]
DICHIARANTE_CF = CFG["dichiarante"]["codice_fiscale"]

# Mappa familiari: CF -> (nome, parentela, CF)
FAMILIARI = {
    fam["codice_fiscale"]: (fam["nome"], fam["parentela"], fam["codice_fiscale"])
    for fam in CFG.get("familiari", [])
}

PAGE_HEIGHT = 842  # A4 height in points


# ============================================================
# SCHEMA
# ============================================================

class ReceiptData(BaseModel):
    beneficiario: Optional[str] = Field(default=None)
    ente: Optional[str] = Field(default=None)
    partita_iva: Optional[str] = Field(default=None)
    codice_fiscale_ente: Optional[str] = Field(default=None)
    numero_documento: Optional[str] = Field(default=None)
    data_documento: Optional[str] = Field(default=None)
    importo: Optional[str] = Field(default=None)
    causale: Optional[str] = Field(default=None)
    pagatore: Optional[str] = Field(default=None)


# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

def extract_text_from_pdf(pdf_path: str) -> str:
    chunks = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            chunks.append(text)

    return "\n".join(chunks)


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_date(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None

    patterns = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    ]

    for pattern in patterns:
        try:
            dt = datetime.strptime(date_str.strip(), pattern)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            pass

    return date_str


def normalize_amount(amount: Optional[str]) -> Optional[str]:
    if not amount:
        return None

    cleaned = amount.replace("€", "")
    cleaned = cleaned.replace(".", "")
    cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.strip()

    try:
        value = float(cleaned)
        return f"{value:.2f}"
    except Exception:
        return amount


def normalize_piva(piva: Optional[str]) -> Optional[str]:
    if not piva:
        return None

    return re.sub(r"\D", "", piva)


# ============================================================
# LLM EXTRACTION
# ============================================================

def extract_structured_data(text: str) -> ReceiptData:
    client = OpenAI()

    prompt = f"""
Estrai i dati dalla seguente ricevuta.

Rispondi SOLO con JSON valido.

Campi richiesti:
- beneficiario: nome della persona a cui è intestata la ricevuta / per cui è stata sostenuta la spesa
- ente: nome della struttura / ente che ha emesso la ricevuta
- partita_iva: P.IVA dell'ente
- codice_fiscale_ente: codice fiscale dell'ente (se presente, diverso dalla P.IVA)
- numero_documento: numero della ricevuta/fattura
- data_documento: data della ricevuta (formato dd/mm/yyyy)
- importo: importo totale pagato (con virgola decimale italiana, es. "50,00")
- causale: descrizione della spesa / causale di pagamento
- pagatore: nome di chi ha effettuato il pagamento (se indicato nella ricevuta)

Usa null se un campo non è presente o se il pagatore non è esplicitamente indicato.

Ricevuta:
----------------
{text}
----------------
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Sei un estrattore documentale preciso."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    raw = response.choices[0].message.content.strip()

    raw = raw.removeprefix("```json")
    raw = raw.removesuffix("```")
    raw = raw.strip()

    data = json.loads(raw)

    receipt = ReceiptData(**data)

    receipt.data_documento = normalize_date(receipt.data_documento)
    receipt.importo = normalize_amount(receipt.importo)
    receipt.partita_iva = normalize_piva(receipt.partita_iva)

    return receipt


def resolve_beneficiario_cf(nome: str) -> str | None:
    """Risolve il CF del beneficiario dal nome, cercando tra dichiarante e familiari."""
    nome_upper = nome.upper()
    # Controlla dichiarante
    if all(part in nome_upper for part in DICHIARANTE_NOME.upper().split()):
        return DICHIARANTE_CF
    # Controlla familiari
    for cf, (nome_fam, _, _) in FAMILIARI.items():
        if all(part in nome_upper for part in nome_fam.upper().split()):
            return cf
    return None


# ============================================================
# PDF OVERLAY
# ============================================================

def create_overlay(data: ReceiptData, beneficiario_cf: str) -> io.BytesIO:
    """Crea un PDF overlay con i testi posizionati sui placeholder."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 9)

    def draw(x: float, y_top: float, text: str, font_size: float = 9):
        """Disegna testo alle coordinate (x, y_top) dove y_top è dal top della pagina."""
        if not text:
            return
        c.setFont("Helvetica", font_size)
        y_bottom = PAGE_HEIGHT - y_top
        c.drawString(x, y_bottom, text)

    # Campo 1: Nome dichiarante (Y=160, underscore x0=56.8..297.8)
    draw(60, 160, DICHIARANTE_NOME)

    # Campo 2: CF dichiarante (Y=160, underscore x0=317.6..509.0)
    draw(320, 160, DICHIARANTE_CF)

    # Campo 3: Data spesa (Y=280, underscore x0=356.1..503.6)
    draw(358, 280, data.data_documento or "")

    # Campo 4: Importo (Y=294, underscore x0=107.0..236.0)
    draw(109, 294, data.importo or "")

    # Campo 5: Causale - prima parte (Y=290, underscore x0=345.0..529.8)
    causale = data.causale or ""
    # Se la causale è lunga, la spezziamo su due righe
    if len(causale) > 45:
        draw(347, 294, causale[:45])
        # Continuazione causale (Y=308, underscore x0=56.8..284.4)
        draw(60, 308, causale[45:])
    else:
        draw(347, 294, causale)

    # Campo 6: Nome beneficiario del servizio (Y=308, underscore x0=301.9..531.5)
    draw(304, 308, data.beneficiario or "")

    # Campo 7: CF beneficiario del servizio (Y=322, underscore x0=317.6..520.6)
    draw(320, 322, beneficiario_cf)

    # Campo 8: Ente / struttura (Y=336, underscore x0=98.5..393.8)
    draw(100, 336, data.ente or "")

    # Campo 9: Partita IVA ente (Y=349, underscore x0=106.5..254.2)
    # Se manca la P.IVA, usa il codice fiscale dell'ente
    draw(108, 349, data.partita_iva or data.codice_fiscale_ente or "")

    # Sezione "DAL FAMILIARE" - compilata solo se il pagatore è un familiare noto
    # (diverso dal dichiarante Andrea Migliaccio)
    pagatore_cf = None
    if data.pagatore:
        # Cerca il pagatore nella mappa familiari per nome
        pagatore_upper = data.pagatore.upper()
        for cf, (nome, parentela, _) in FAMILIARI.items():
            if nome.upper() in pagatore_upper or pagatore_upper in nome.upper():
                pagatore_cf = cf
                break

    if pagatore_cf:
        familiare_info = FAMILIARI[pagatore_cf]
        nome_fam, parentela, cf_fam = familiare_info
        # Campo 10: Nome familiare pagante (Y=378, x0=311.1..520.3)
        draw(313, 378, nome_fam)
        # Campo 11: Qualità / parentela (Y=392, x0=145.7..336.2)
        draw(148, 392, parentela)
        # Campo 12: CF familiare pagante (Y=406, x0=92.8..283.5)
        draw(95, 406, cf_fam)
    else:
        # Pagatore è il dichiarante o non specificato -> PERSONALMENTE
        draw(65, 368, "X", font_size=12)

    # Data in fondo (Y=581) - la firma resta vuota per apposizione manuale
    draw(386, 581, datetime.now().strftime("%d/%m/%Y"))

    c.save()
    buf.seek(0)
    return buf


def fill_pdf_overlay(
    template_path: str,
    output_path: str,
    data: ReceiptData,
    beneficiario_cf: str,
):
    """Sovrappone i dati compilati al template PDF."""
    overlay_buf = create_overlay(data, beneficiario_cf)

    template_reader = PdfReader(template_path)
    overlay_reader = PdfReader(overlay_buf)
    writer = PdfWriter()

    # Unisci overlay con la prima pagina del template
    template_page = template_reader.pages[0]
    overlay_page = overlay_reader.pages[0]
    template_page.merge_page(overlay_page)
    writer.add_page(template_page)

    # Aggiungi le altre pagine del template (es. carta d'identità)
    for page in template_reader.pages[1:]:
        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)


# ============================================================
# MAIN
# ============================================================

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Compila autocertificazione da ricevuta PDF"
    )
    parser.add_argument("ricevuta", help="PDF della ricevuta")
    parser.add_argument("template", help="PDF del template autocertificazione")

    args = parser.parse_args()

    # Genera nome output: XXXX.pdf -> XXXX-autocertificazione.pdf
    ricevuta_dir = os.path.dirname(os.path.abspath(args.ricevuta))
    ricevuta_base = os.path.splitext(os.path.basename(args.ricevuta))[0]
    output_pdf = os.path.join(ricevuta_dir, f"{ricevuta_base}-autocertificazione.pdf")

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY non configurata")

    print("Estrazione testo dal PDF...")
    text = extract_text_from_pdf(args.ricevuta)

    if not text.strip():
        print("ERRORE: Nessun testo estraibile dalla ricevuta.")
        sys.exit(1)

    print("Estrazione dati strutturati...")
    extracted = extract_structured_data(text)

    print("\n=== DATI ESTRATTI ===")
    print(extracted.model_dump_json(indent=2))
    print("=====================\n")

    # Risolvi CF del beneficiario dal nome
    if not extracted.beneficiario:
        print("ERRORE: Beneficiario non identificato dalla ricevuta.")
        sys.exit(1)

    bf_cf = resolve_beneficiario_cf(extracted.beneficiario)
    if not bf_cf:
        print(f"ERRORE: Beneficiario '{extracted.beneficiario}' non riconosciuto.")
        print(f"Nomi noti: {DICHIARANTE_NOME} (dichiarante)")
        for cf, (nome, par, _) in FAMILIARI.items():
            print(f"  {nome} ({par})")
        sys.exit(1)

    # Verifica campi obbligatori
    missing = []
    if not extracted.data_documento:
        missing.append("data_documento")
    if not extracted.importo:
        missing.append("importo")
    if not extracted.ente:
        missing.append("ente")

    if missing:
        print(f"ERRORE: Dati mancanti dalla ricevuta: {', '.join(missing)}")
        print("Compilare manualmente o fornire una ricevuta più dettagliata.")
        sys.exit(1)

    print("Compilazione PDF...")
    fill_pdf_overlay(args.template, output_pdf, extracted, bf_cf)

    print(f"PDF generato: {output_pdf}")


if __name__ == "__main__":
    main()