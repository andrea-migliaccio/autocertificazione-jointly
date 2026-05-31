#!/usr/bin/env python3

"""Esegue autofill.py su una lista di ricevute con hint opzionale.

Formato file input (una riga per ricevuta):
- C:\\path\\to\\file.pdf
- C:\\path\\to\\file.pdf --> hint opzionale
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Job:
    pdf_path: str
    hint: str | None = None


def parse_jobs(list_path: Path) -> list[Job]:
    jobs: list[Job] = []

    with list_path.open("r", encoding="utf-8") as f:
        for idx, raw_line in enumerate(f, start=1):
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            left, sep, right = line.partition("-->")
            pdf_path = left.strip()
            hint = right.strip() if sep else ""

            if not pdf_path:
                print(f"Riga {idx}: path PDF vuoto, salto.")
                continue

            jobs.append(Job(pdf_path=pdf_path, hint=hint or None))

    return jobs


def run_jobs(jobs: list[Job], autofill_script: Path, stop_on_error: bool) -> int:
    ok = 0
    failed = 0

    for i, job in enumerate(jobs, start=1):
        cmd = [sys.executable, str(autofill_script), job.pdf_path]
        if job.hint:
            cmd.extend(["--hint", job.hint])

        print("=" * 72)
        print(f"[{i}/{len(jobs)}] PDF: {job.pdf_path}")
        if job.hint:
            print(f"Hint: {job.hint}")
        print("Comando:", " ".join(cmd))

        result = subprocess.run(cmd)
        if result.returncode == 0:
            ok += 1
            print("Esito: OK")
        else:
            failed += 1
            print(f"Esito: ERRORE (exit code {result.returncode})")
            if stop_on_error:
                print("Interruzione per --stop-on-error.")
                break

    print("=" * 72)
    print(f"Totale job: {len(jobs)} | OK: {ok} | Errori: {failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Esegue autofill.py su tutti i PDF elencati in un file lista.",
    )
    parser.add_argument(
        "input_list",
        nargs="?",
        default="lista.txt",
        help="File input con path PDF e hint opzionale (default: lista.txt)",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Interrompe al primo errore invece di proseguire.",
    )

    args = parser.parse_args()

    list_path = Path(args.input_list)
    if not list_path.exists():
        print(f"ERRORE: file lista non trovato: {list_path}")
        return 1

    autofill_script = Path(__file__).with_name("autofill.py")
    if not autofill_script.exists():
        print(f"ERRORE: script non trovato: {autofill_script}")
        return 1

    jobs = parse_jobs(list_path)
    if not jobs:
        print("Nessun job valido trovato nel file lista.")
        return 0

    print(f"Trovati {len(jobs)} job in {list_path}")
    return run_jobs(jobs, autofill_script, stop_on_error=args.stop_on_error)


if __name__ == "__main__":
    raise SystemExit(main())
