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
- Se ci sono modifiche funzionali significative, aggiorna SEMPRE il changelog nel `README.md` con il commit-id.
- Workflow obbligatorio quando chiedo "commit e push":
	1. fai un primo commit con le modifiche di codice/documentazione;
	2. recupera il commit-id;
	3. aggiungi la riga nel changelog del `README.md` con quel commit-id e descrizione breve;
	4. fai un secondo commit SOLO del `README.md`;
	5. pusha tutto.