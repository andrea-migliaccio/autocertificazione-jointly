# Autofill Autocertificazione Welfare

Compila automaticamente il modulo di dichiarazione sostitutiva (autocertificazione) Jointly, estraendo i dati da una ricevuta PDF tramite LLM e sovrapponendo il testo al template. Per comodità si suggerisce di fornire al sistema un file PDF con già mergiata la carta d'identità del pagatore, come specificato dalle istruzioni. Così il file prodotto sarà praticamente solo pronto per un check manuale ed eventualmente la firma.

ATTENZIONE, l'AI può sbagliare, ricontrollare sempre i file prodotti prima di sottometterli nella piattaforma jointly

## Requisiti

- Python 3.11+
- Una chiave API OpenAI

## Installazione

```bash
pip install pdfplumber openai pypdf python-dotenv reportlab pydantic
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
  "template_pdf": "C:\\Users\\MarioRossi\\Documents\\Welfare\\Autocertificazione_Template.pdf"
}
```

| Campo | Descrizione |
|-------|-------------|
| `dichiarante.nome` | Nome e cognome del dipendente (maiuscolo) |
| `dichiarante.codice_fiscale` | Codice fiscale del dipendente |
| `familiari` | Lista dei familiari art. 12 TUIR (coniuge, figli, genitori, nonni) |
| `familiari[].parentela` | Relazione con il dipendente |
| `modello_openai` | Modello OpenAI da usare (default: `gpt-4o`) |
| `template_pdf` | Percorso assoluto del PDF del modulo di autocertificazione Jointly (con carta d'identità allegata) |

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

## Come funziona

1. **Estrazione testo**: legge il testo dalla ricevuta PDF con `pdfplumber`
2. **Analisi LLM**: invia il testo a OpenAI per estrarre i dati strutturati (beneficiario, ente, importo, data, causale, P.IVA, pagatore)
3. **Risoluzione beneficiario**: confronta il nome del beneficiario con dichiarante e familiari per ricavare il codice fiscale
4. **Compilazione**: genera un overlay PDF con `reportlab` e lo sovrappone al template con `pypdf`

### Logica "PERSONALMENTE / DAL FAMILIARE"

- Se il **pagatore** non è indicato nella ricevuta o è il dichiarante → viene selezionato **PERSONALMENTE**
- Se il **pagatore** è un familiare presente in `config.json` → viene compilata la sezione **DAL FAMILIARE** con i dati del familiare

> **Nota**: il campo "In fede (firma autografa)" viene lasciato vuoto per l'apposizione manuale della firma.

## Errori comuni

| Errore | Soluzione |
|--------|-----------|
| `File di configurazione non trovato` | Creare `config.json` a partire da `config.example.json` |
| `OPENAI_API_KEY non configurata` | Creare il file `.env` con la chiave API |
| `Beneficiario non riconosciuto` | Il nome estratto dalla ricevuta non corrisponde a nessun nominativo in `config.json`. Verificare i nomi configurati |
| `Nessun testo estraibile` | La ricevuta è probabilmente un'immagine scannerizzata, non un PDF testuale |
| `Dati mancanti dalla ricevuta` | La ricevuta non contiene tutti i campi necessari (data, importo, ente) |
