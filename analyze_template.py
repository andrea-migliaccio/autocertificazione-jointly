"""Estrae le coordinate dei caratteri dal template PDF per trovare le posizioni dei placeholder."""
import sys
import pdfplumber

template_path = sys.argv[1]

with pdfplumber.open(template_path) as pdf:
    page = pdf.pages[0]
    
    # Dimensioni pagina
    print(f"Pagina: {page.width} x {page.height}")
    print()
    
    # Estrai tutti i caratteri con le loro coordinate
    chars = page.chars
    
    # Raggruppa per riga (per y approssimata)
    lines = {}
    for c in chars:
        y_key = round(c["top"], 0)
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append(c)
    
    # Ordina per y
    for y_key in sorted(lines.keys()):
        line_chars = sorted(lines[y_key], key=lambda c: c["x0"])
        text = "".join(c["text"] for c in line_chars)
        
        # Mostra righe con underscore o numeri di campo interessanti
        if "_" in text or any(marker in text for marker in ["C.F.", "data", "somma", "€", "favore", "Partita", "qualità", "FAMILIARE"]):
            # Trova i segmenti di underscore
            first_x = line_chars[0]["x0"]
            last_x = line_chars[-1]["x1"]
            print(f"Y={y_key:6.1f} | x0={first_x:6.1f} x1={last_x:6.1f} | {text}")
            
            # Mostra posizioni degli underscore
            underscore_start = None
            underscore_end = None
            for c in line_chars:
                if c["text"] == "_":
                    if underscore_start is None:
                        underscore_start = c["x0"]
                    underscore_end = c["x1"]
                else:
                    if underscore_start is not None:
                        print(f"   UNDERSCORE: x0={underscore_start:6.1f} x1={underscore_end:6.1f}")
                        underscore_start = None
                        underscore_end = None
            if underscore_start is not None:
                print(f"   UNDERSCORE: x0={underscore_start:6.1f} x1={underscore_end:6.1f}")
