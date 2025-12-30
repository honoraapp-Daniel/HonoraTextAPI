# HonoraWebScraper

Web scraper til at downloade bøger fra [sacred-texts.com](https://sacred-texts.com) som PDF-filer.

## Installation

```bash
npm install
```

## Brug

### Vis alle kategorier
```bash
node src/index.js --list-categories
```

### Download alle bøger fra en kategori
```bash
node src/index.js --category "Buddhism"
```

### Download en enkelt bog
```bash
node src/index.js --book "https://sacred-texts.com/afr/saft/index.htm"
```

## Output

PDF-filer gemmes i:
```
output/
├── Buddhism/
│   ├── A_Buddhist_Bible.pdf
│   └── ...
├── African/
│   ├── South_African_Folk_Tales.pdf
│   └── ...
```

## Indstillinger

Rediger `config.js` for at ændre:
- `requestDelay` - Tid mellem requests (standard: 800ms)
- `outputDir` - Output-mappe for PDFs
- PDF formatering (margins, format, etc.)
