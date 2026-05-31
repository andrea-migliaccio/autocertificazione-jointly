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
from reportlab.lib.utils import ImageReader
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
DICHIARANTE_LUOGO = CFG.get("luogo", "")

# Mappa familiari: CF -> (nome, parentela, CF)
FAMILIARI = {
    fam["codice_fiscale"]: (fam["nome"], fam["parentela"], fam["codice_fiscale"])
    for fam in CFG.get("familiari", [])
}

TEMPLATE_PDF = CFG.get("template_pdf", "")
SIGNATURE_PNG = CFG.get("firma_png", "")

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


def resolve_family_cf_from_name(nome: str | None) -> str | None:
    """Risolvi il CF di un familiare noto dal nome completo/parziale."""
    if not nome:
        return None
    nome_upper = nome.upper()
    for cf, (nome_fam, _, _) in FAMILIARI.items():
        if all(part in nome_upper for part in nome_fam.upper().split()):
            return cf
    return None


def normalize_parentela(parentela: str) -> str | None:
    """Normalizza le varianti di parentela alle opzioni presenti nel template."""
    p = parentela.strip().lower()
    mapping = {
        "coniuge": "coniuge",
        "figlio": "figli",
        "figlia": "figli",
        "figli": "figli",
        "genitore": "genitori conviventi",
        "genitori": "genitori conviventi",
        "genitori conviventi": "genitori conviventi",
        "fratello": "fratelli/sorelle conviventi",
        "sorella": "fratelli/sorelle conviventi",
        "fratelli": "fratelli/sorelle conviventi",
        "sorelle": "fratelli/sorelle conviventi",
        "fratelli/sorelle conviventi": "fratelli/sorelle conviventi",
        "suocero": "suoceri conviventi",
        "suocera": "suoceri conviventi",
        "suoceri": "suoceri conviventi",
        "suoceri conviventi": "suoceri conviventi",
        "nuora": "nuore/generi conviventi",
        "genero": "nuore/generi conviventi",
        "nuore": "nuore/generi conviventi",
        "generi": "nuore/generi conviventi",
        "nuore/generi conviventi": "nuore/generi conviventi",
    }
    return mapping.get(p)


def pick_familiare_for_template(data: ReceiptData) -> str | None:
    """Sceglie il familiare da usare nel modello 2026 (beneficiario priorita')."""
    # Priorita': beneficiario, poi pagatore (se familiare noto)
    cf = resolve_family_cf_from_name(data.beneficiario)
    if cf:
        return cf
    return resolve_family_cf_from_name(data.pagatore)


# ============================================================
# PDF OVERLAY
# ============================================================

def create_overlay(data: ReceiptData) -> io.BytesIO:
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

    def mark_radio(x: float, y_top: float):
        """Riempie il pallino di una radio gia' presente nel template."""
        y_bottom = PAGE_HEIGHT - y_top
        c.circle(x, y_bottom, 2.8, stroke=0, fill=1)

    def draw_signature_if_configured(path: str):
        """Disegna la firma PNG nel campo firma se il percorso e' configurato e valido."""
        if not path:
            return
        if not os.path.exists(path):
            print(f"Avviso: file firma non trovato, salto firma: {path}")
            return
        try:
            img = ImageReader(path)
            img_w, img_h = img.getSize()

            # Box firma nel modello 2026 (zona destra del footer, vicino a 'Firma').
            box_x = 322
            box_y_top = 718
            box_w = 220
            box_h = 42

            # Mantieni proporzioni adattando l'immagine al box.
            scale = min(box_w / img_w, box_h / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale
            draw_x = box_x + (box_w - draw_w) / 2
            draw_y_bottom = PAGE_HEIGHT - box_y_top - draw_h

            c.drawImage(
                img,
                draw_x,
                draw_y_bottom,
                width=draw_w,
                height=draw_h,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception as e:
            print(f"Avviso: impossibile applicare la firma PNG ({path}): {e}")

    # Nuovo template 2026 - Informazioni personali
    draw(36, 157, DICHIARANTE_NOME)
    draw(328, 157, DICHIARANTE_CF)

    familiare_cf = pick_familiare_for_template(data)
    if familiare_cf:
        mark_radio(37, 274)
        nome_fam, parentela, cf_fam = FAMILIARI[familiare_cf]
        draw(36, 322, nome_fam)
        draw(218, 322, cf_fam)

        parentela_key = normalize_parentela(parentela)
        parentela_radios = {
            "coniuge": (395, 314),
            "figli": (395, 324),
            "genitori conviventi": (395, 334),
            "fratelli/sorelle conviventi": (467, 314),
            "suoceri conviventi": (467, 324),
            "nuore/generi conviventi": (467, 334),
        }
        if parentela_key in parentela_radios:
            x, y = parentela_radios[parentela_key]
            mark_radio(x, y)
    else:
        # Intestatario/pagatore e' il dichiarante
        mark_radio(37, 255)

    # Luogo e data in fondo, firma lasciata vuota per firma autografa
    oggi = datetime.now().strftime("%d/%m/%Y")
    luogo_data = f"{DICHIARANTE_LUOGO}, {oggi}" if DICHIARANTE_LUOGO else oggi
    draw(36, 732, luogo_data)
    draw_signature_if_configured(SIGNATURE_PNG)

    c.save()
    buf.seek(0)
    return buf


def fill_pdf_overlay(
    template_path: str,
    output_path: str,
    data: ReceiptData,
):
    """Sovrappone i dati compilati al template PDF."""
    overlay_buf = create_overlay(data)

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

    # Nel modello 2026, se beneficiario/pagatore non sono leggibili si procede comunque:
    # verra' selezionato automaticamente "Me stesso".
    if not extracted.beneficiario and not extracted.pagatore:
        print("Avviso: beneficiario/pagatore non identificati. Verra' selezionato 'Me stesso'.")

    print("Compilazione PDF...")
    fill_pdf_overlay(TEMPLATE_PDF, output_pdf, extracted)

    print(f"PDF generato: {output_pdf}")


if __name__ == "__main__":
    main()