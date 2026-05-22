#!/usr/bin/env python3

"""
Compila automaticamente un PDF di autocertificazione
estraendo i dati da una ricevuta PDF testuale e sovrapponendo
testo alle coordinate dei placeholder.

Uso:

    python autofill.py ricevuta.pdf [--hint "istruzione aggiuntiva"]

Dipendenze:

    pip install pdfplumber openai pypdf python-dotenv reportlab pydantic pymupdf

Variabili ambiente richieste:

    OPENAI_API_KEY=...
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
from datetime import datetime
from typing import Optional

import fitz
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

TEMPLATE_PDF = CFG.get("template_pdf", "")

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


def is_readable_text(text: str) -> bool:
    """Verifica se il testo estratto è leggibile (non garbled da font custom)."""
    if not text.strip():
        return False
    # Font custom con CID mapping: pdfplumber produce "(cid:XX)"
    if "(cid:" in text:
        return False
    # Conta caratteri ASCII stampabili + lettere accentate comuni
    normal = sum(1 for c in text if c.isascii() or c in "àèéìòùÀÈÉÌÒÙ€")
    return normal / len(text) > 0.5


def render_pdf_to_images(pdf_path: str) -> list[bytes]:
    """Renderizza le pagine del PDF come immagini PNG con pymupdf."""
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


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

def extract_structured_data(text: str, hint: str = "") -> ReceiptData:
    """Estrae dati strutturati da testo leggibile."""
    client = OpenAI(timeout=60)

    prompt = _build_prompt(text)
    system = _build_system_prompt(hint)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ]
        )
    except Exception as e:
        print(f"ERRORE nella chiamata API OpenAI: {e}")
        sys.exit(1)

    return _parse_response(response)


def extract_structured_data_from_images(images: list[bytes], hint: str = "") -> ReceiptData:
    """Estrae dati strutturati da immagini del PDF (fallback vision)."""
    client = OpenAI(timeout=60)

    prompt = _build_prompt(None)
    system = _build_system_prompt(hint)

    content: list[dict] = [{"type": "text", "text": prompt}]
    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content}
            ]
        )
    except Exception as e:
        print(f"ERRORE nella chiamata API OpenAI: {e}")
        sys.exit(1)

    return _parse_response(response)


def _build_system_prompt(hint: str = "") -> str:
    base = (
        "Sei un estrattore documentale preciso. "
        "Estrai SOLO informazioni esplicitamente presenti nel documento. "
        "NON inventare, NON indovinare, NON usare date odierne o di default. "
        "Se un dato non è chiaramente leggibile nel documento, restituisci null."
    )
    if hint:
        return f"{base} {hint}"
    return base


def _build_prompt(text: str | None) -> str:
    header = """Estrai i dati dalla seguente ricevuta.

Rispondi SOLO con JSON valido.

Campi richiesti:
- beneficiario: nome della persona a cui è intestata la ricevuta / per cui è stata sostenuta la spesa
- ente: nome della struttura / ente che ha emesso la ricevuta
- partita_iva: P.IVA dell'ente
- codice_fiscale_ente: codice fiscale dell'ente (se presente, diverso dalla P.IVA)
- numero_documento: numero della ricevuta/fattura
- data_documento: data di emissione della ricevuta o data di pagamento, nel formato dd/mm/yyyy. ATTENZIONE: estrai SOLO la data esplicitamente scritta nel documento. NON inventare, NON indovinare, NON usare la data odierna. Se la data non è chiaramente indicata nel documento, usa null.
- importo: importo totale pagato (con virgola decimale italiana, es. "50,00")
- causale: descrizione della spesa / causale di pagamento
- pagatore: nome di chi ha effettuato il pagamento (se indicato nella ricevuta)

IMPORTANTE: usa null per ogni campo il cui valore non è ESPLICITAMENTE presente nel documento. Non inventare o dedurre valori non scritti chiaramente."""

    if text:
        return f"{header}\n\nRicevuta:\n----------------\n{text}\n----------------"
    return f"{header}\n\nAnalizza l'immagine della ricevuta allegata."


def _parse_response(response) -> ReceiptData:
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
        pagatore_upper = data.pagatore.upper()
        # Controlla che non sia il dichiarante
        is_dichiarante = all(
            part in pagatore_upper for part in DICHIARANTE_NOME.upper().split()
        )
        if not is_dichiarante:
            # Cerca il pagatore nella mappa familiari per parole del nome
            for cf, (nome, parentela, _) in FAMILIARI.items():
                if all(part in pagatore_upper for part in nome.upper().split()):
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
    parser.add_argument(
        "--hint",
        default="",
        help="Istruzione aggiuntiva per l'AI (es. 'Il pagatore è MIGLIACCIO MATTEO')",
    )

    args = parser.parse_args()

    if not TEMPLATE_PDF or not os.path.exists(TEMPLATE_PDF):
        print(f"ERRORE: Template PDF non trovato: '{TEMPLATE_PDF}'")
        print("Configurare 'template_pdf' in config.json con il percorso del modulo di autocertificazione.")
        sys.exit(1)

    # Genera nome output: XXXX.pdf -> XXXX-autocertificazione.pdf
    ricevuta_dir = os.path.dirname(os.path.abspath(args.ricevuta))
    ricevuta_base = os.path.splitext(os.path.basename(args.ricevuta))[0]
    output_pdf = os.path.join(ricevuta_dir, f"{ricevuta_base}-autocertificazione.pdf")

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY non configurata")

    print("Estrazione testo dal PDF...")
    text = extract_text_from_pdf(args.ricevuta)

    print("Estrazione dati strutturati...")
    print(text[:200] + "\n...")  # Mostra un'anteprima del testo estratto
    if is_readable_text(text):
        extracted = extract_structured_data(text, hint=args.hint)
    else:
        print("  Testo non leggibile, fallback a modalità visione...")
        images = render_pdf_to_images(args.ricevuta)
        extracted = extract_structured_data_from_images(images, hint=args.hint)

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
        print("Compilare manualmente o fornire una ricevuta più dettagliata. In alternativa usare l'argomento --hint per guidare l'estrazione (es. '--hint \"La data è indicata come 'Data: 01/02/2025'\"').")
        sys.exit(1)

    print("Compilazione PDF...")
    fill_pdf_overlay(TEMPLATE_PDF, output_pdf, extracted, bf_cf)

    print(f"PDF generato: {output_pdf}")


if __name__ == "__main__":
    main()