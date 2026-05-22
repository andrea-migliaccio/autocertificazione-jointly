"""Dump ALL text lines with coordinates from the template PDF."""
import sys
import pdfplumber

template_path = sys.argv[1]

with pdfplumber.open(template_path) as pdf:
    page = pdf.pages[0]
    print(f"Pagina: {page.width} x {page.height}")
    
    chars = page.chars
    lines = {}
    for c in chars:
        y_key = round(c["top"], 0)
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append(c)
    
    for y_key in sorted(lines.keys()):
        line_chars = sorted(lines[y_key], key=lambda c: c["x0"])
        text = "".join(c["text"] for c in line_chars)
        first_x = line_chars[0]["x0"]
        last_x = line_chars[-1]["x1"]
        font = line_chars[0].get("fontname", "?")
        size = line_chars[0].get("size", "?")
        print(f"Y={y_key:6.1f} | x0={first_x:6.1f} x1={last_x:6.1f} | sz={size} | {text[:120]}")
