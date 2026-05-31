# GitHub Instructions

## 1) Scopo del progetto
Questo progetto automatizza la compilazione del modulo di autocertificazione welfare partendo da una ricevuta PDF.

In sintesi:
- estrae e interpreta i dati dalla ricevuta;
- compila il template PDF di autocertificazione;
- produce un file pronto per verifica manuale e firma.

## 2) Uso del comando di analyze
Gli script di analisi servono per leggere coordinate/testo dal template PDF e supportare il debug del posizionamento campi.

Comandi principali:
- `python3 analyze_template.py "C:\\percorso\\template.pdf"`
- `python3 analyze_all.py "C:\\percorso\\template.pdf"`

## 3) Regola runtime Python
Per eseguire script Python in questo progetto usare sempre e solo `python3`.

Non usare:
- `py`
- `python`

Motivo: in questo ambiente i comandi `py` e `python` possono puntare a interpreti non corretti o non disponibili.

## 4) Commit e push

Quando ti chiedo di fare un commit, assicurati di:
- Aggiungere un messaggio chiaro e descrittivo al commit.
- Fai prima un commit con le modifiche effettive, poi aggiungi una voce al changelog con il commit-id, se ci sono modifiche funzionali significative
- Committa solo il readme
- pusha tutto