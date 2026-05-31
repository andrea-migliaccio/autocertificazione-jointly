"""Analizza un template PDF e propone coordinate per campi e radio del modello 2026."""

import sys

import pdfplumber


def find_word(words: list[dict], exact_text: str) -> dict | None:
    for w in words:
        if w["text"].strip() == exact_text:
            return w
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python analyze_template.py <template.pdf>")
        raise SystemExit(1)

    template_path = sys.argv[1]

    with pdfplumber.open(template_path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(x_tolerance=1, y_tolerance=1)

    print(f"Pagina: {page.width} x {page.height}")
    print(f"Parole estratte: {len(words)}")
    print()

    anchors = {
        "label_nome": find_word(words, "Nome"),
        "label_codice": find_word(words, "Codice"),
        "label_me_stesso": find_word(words, "stesso"),
        "label_familiare": find_word(words, "Familiare"),
        "label_coniuge": find_word(words, "Coniuge"),
        "label_figli": find_word(words, "Figli"),
        "label_genitori": find_word(words, "Genitori"),
        "label_fratelli": find_word(words, "Fratelli/Sorelle"),
        "label_suoceri": find_word(words, "Suoceri"),
        "label_nuore": find_word(words, "Nuore/Generi"),
        "label_luogo": find_word(words, "Luogo"),
    }

    print("Anchor trovati:")
    for key, value in anchors.items():
        if value:
            print(
                f"- {key}: x0={value['x0']:.1f}, x1={value['x1']:.1f}, "
                f"top={value['top']:.1f}, text={value['text']}"
            )
        else:
            print(f"- {key}: NON TROVATO")

    print()
    print("Coordinate suggerite (overlay):")
    print("- nome_dichiarante: x=36, y_top=160")
    print("- cf_dichiarante: x=328, y_top=160")
    print("- radio_me_stesso: x=37, y_top=258")
    print("- radio_familiare: x=37, y_top=277")
    print("- nome_familiare: x=36, y_top=322")
    print("- cf_familiare: x=218, y_top=322")
    print("- parentela_coniuge: x=391, y_top=314")
    print("- parentela_figli: x=391, y_top=324")
    print("- parentela_genitori: x=391, y_top=334")
    print("- parentela_fratelli_sorelle: x=463, y_top=314")
    print("- parentela_suoceri: x=463, y_top=324")
    print("- parentela_nuore_generi: x=463, y_top=334")
    print("- luogo_data: x=36, y_top=732")


if __name__ == "__main__":
    main()
