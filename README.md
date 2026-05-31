# Autofill Autocertificazione Welfare

Compila automaticamente il modulo di dichiarazione sostitutiva (autocertificazione) Jointly, estraendo i dati da una ricevuta PDF tramite LLM e sovrapponendo il testo al template. Per comodità si suggerisce di fornire al sistema un file PDF con già mergiata la carta d'identità del pagatore, come specificato dalle istruzioni. Così il file prodotto sarà praticamente solo pronto per un check manuale ed eventualmente la firma.

ATTENZIONE, l'AI può sbagliare, ricontrollare sempre i file prodotti prima di sottometterli nella piattaforma jointly

## Requisiti

- Python 3.11+
- Una chiave API OpenAI

## Installazione

```bash
pip install pdfplumber openai pypdf python-dotenv reportlab pydantic pymupdf
```

## Configurazione

### 1. Chiave OpenAI

Crea un file `.env` nella cartella del progetto:

```
OPENAI_API_KEY=sk-...
```

### 2. Dati personali

Copia il file di esempio e compilalo con i tuoi dati:

```bash
cp config.example.json config.json
```

Struttura di `config.json`:

```json
{
  "dichiarante": {
    "nome": "MARIO ROSSI",
    "codice_fiscale": "RSSMRA80A01H501Z"
  },
  "luogo": "Milano",
  "familiari": [
    {
      "nome": "Giulia Rossi",
      "parentela": "Figlio",
      "codice_fiscale": "RSSGLI10B15F205X"
    },
    {
      "nome": "Laura Bianchi",
      "parentela": "Coniuge",
      "codice_fiscale": "BNCLRA82C45H501Y"
    }
  ],
  "modello_openai": "gpt-4o",
  "firma_png": "C:\\Users\\MarioRossi\\Documents\\Welfare\\firma.png",
  "template_pdf": "C:\\Users\\MarioRossi\\Documents\\Welfare\\Autocertificazione_Template.pdf"
}
```

| Campo | Descrizione |
|-------|-------------|
| `dichiarante.nome` | Nome e cognome del dipendente (maiuscolo) |
| `dichiarante.codice_fiscale` | Codice fiscale del dipendente |
| `luogo` | Luogo usato nel campo "Luogo e data" (opzionale, default: solo data) |
| `familiari` | Lista dei familiari art. 12 TUIR (coniuge, figli, genitori, nonni) |
| `familiari[].parentela` | Relazione con il dipendente |
| `modello_openai` | Modello OpenAI da usare (default: `gpt-4o`) |
| `firma_png` | Percorso assoluto firma PNG da applicare nel campo firma (opzionale) |
| `template_pdf` | Percorso assoluto del PDF del modulo di autocertificazione Jointly (nuovo modello 2026) |

## Uso

```bash
python autofill.py ricevuta.pdf
```

Il file di output viene generato automaticamente nella stessa cartella della ricevuta, con il nome `<ricevuta>-autocertificazione.pdf`.

| Argomento | Descrizione |
|-----------|-------------|
| `ricevuta.pdf` | PDF della ricevuta/fattura da cui estrarre i dati |

Il template di autocertificazione viene letto da `config.json` (campo `template_pdf`).

### Esempio

```bash
python autofill.py "Contributo_Volontario.pdf"
```

Produce `Contributo_Volontario-autocertificazione.pdf` nella stessa cartella della ricevuta.

### Esecuzione batch da lista

Se vuoi processare piu' ricevute in una volta, usa `autofill_all.py`.

Formato di `lista.txt` (una riga per file):

```
C:\\path\\file1.pdf
C:\\path\\file2.pdf --> Il pagatore e' Mario Rossi
```

Comandi:

```bash
python3 autofill_all.py
python3 autofill_all.py lista.txt
python3 autofill_all.py lista.txt --stop-on-error
```

Lo script esegue internamente `autofill.py` per ogni riga, passando `--hint` solo quando presente dopo `-->`.

## Come funziona

1. **Estrazione testo**: legge il testo dalla ricevuta PDF con `pdfplumber`
2. **Verifica leggibilità**: controlla che il testo estratto sia effettivamente leggibile (alcuni PDF usano font custom con encoding non standard che producono spazzatura tipo `(cid:XX)`)
3. **Fallback vision**: se il testo non è leggibile, renderizza il PDF come immagine con `pymupdf` e la invia all'API OpenAI vision per l'analisi
4. **Analisi LLM**: invia il testo (o l'immagine) a OpenAI per estrarre i dati strutturati (beneficiario, ente, importo, data, causale, P.IVA, pagatore)
5. **Risoluzione beneficiario**: confronta il nome del beneficiario con dichiarante e familiari per ricavare il codice fiscale
6. **Compilazione**: genera un overlay PDF con `reportlab` e lo sovrappone al template con `pypdf`

### Parametro `--hint`

Se l'AI sbaglia a interpretare qualche campo (es. pagatore non correttamente identificato in PDF tabulari), si può forzare con un'istruzione aggiuntiva:

```bash
python autofill.py ricevuta.pdf --hint "Il pagatore è BRAMBILLA MATTEO"
python autofill.py ricevuta.pdf --hint "La partita IVA dell'ente è 12621570154"
```

### Logica "Me stesso / Familiare"

- Se il **beneficiario** (o in fallback il **pagatore**) coincide con un familiare presente in `config.json` → viene selezionato **Familiare** e compilata la sezione familiare (nome, CF e parentela)
- Altrimenti viene selezionato **Me stesso**

> **Nota**: il campo "Firma" viene lasciato vuoto per l'apposizione manuale.

Se configuri `firma_png`, la firma viene sovrapposta automaticamente nell'area firma del template.
Se il campo manca o e' vuoto, questo passaggio viene saltato.

## Errori comuni

| Errore | Soluzione |
|--------|-----------|
| `File di configurazione non trovato` | Creare `config.json` a partire da `config.example.json` |
| `OPENAI_API_KEY non configurata` | Creare il file `.env` con la chiave API |
| `Beneficiario non riconosciuto` | Il nome estratto dalla ricevuta non corrisponde a nessun nominativo in `config.json`. Verificare i nomi configurati |
| `Nessun testo estraibile` | Il PDF non contiene né testo estraibile né immagini analizzabili |
| `Dati mancanti dalla ricevuta` | La ricevuta non contiene tutti i campi necessari (data, importo, ente). Provare con `--hint` |

## Changelog

| Versione | Descrizione |
|----------|-------------|
| `9f4e288` | Rilascio iniziale: estrazione dati da ricevuta PDF via LLM e compilazione automatica del modulo di autocertificazione |
| `5e920e9` | Nome file di output generato automaticamente (`<ricevuta>-autocertificazione.pdf`) |
| `020f218` | Percorso del template PDF configurabile da `config.json` (`template_pdf`) |
| `cff5e41` | Fallback vision per PDF con font non standard; parametro `--hint` per istruzioni aggiuntive all'AI |
