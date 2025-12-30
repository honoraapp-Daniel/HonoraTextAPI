#!/usr/bin/env node

// HonoraWebScraper - CLI til at downloade bøger fra sacred-texts.com som PDF

import { getAllCategories, getBooksInCategory, getCategoryNameFromUrl } from './categoryCrawler.js';
import { scrapeFullBook, sanitizeFilename } from './bookScraper.js';
import { bookToPdf } from './pdfGenerator.js';

/**
 * Parser kommando-linje argumenter
 */
function parseArgs() {
    const args = process.argv.slice(2);
    const options = {
        mode: null,
        value: null
    };

    for (let i = 0; i < args.length; i++) {
        const arg = args[i];

        if (arg === '--list-categories' || arg === '-l') {
            options.mode = 'list-categories';
        } else if (arg === '--category' || arg === '-c') {
            options.mode = 'category';
            options.value = args[++i];
        } else if (arg === '--book' || arg === '-b') {
            options.mode = 'book';
            options.value = args[++i];
        } else if (arg === '--help' || arg === '-h') {
            options.mode = 'help';
        }
    }

    return options;
}

/**
 * Viser hjælp-tekst
 */
function showHelp() {
    console.log(`
╔══════════════════════════════════════════════════════════════════╗
║                    HonoraWebScraper v1.0                        ║
║         Download bøger fra sacred-texts.com som PDF             ║
╚══════════════════════════════════════════════════════════════════╝

BRUG:
  node src/index.js [OPTIONS]

OPTIONS:
  -l, --list-categories     Vis alle tilgængelige kategorier
  -c, --category <navn>     Download alle bøger fra en kategori
  -b, --book <url>          Download en enkelt bog fra dens URL
  -h, --help                Vis denne hjælp

EKSEMPLER:
  # Vis alle kategorier
  node src/index.js --list-categories

  # Download alle bøger fra "African" kategorien
  node src/index.js --category "African"

  # Download en specifik bog
  node src/index.js --book "https://sacred-texts.com/afr/saft/index.htm"

OUTPUT:
  PDF-filer gemmes i ./output/<Kategori>/<Bog_Titel>.pdf
`);
}

/**
 * Viser alle kategorier
 */
async function listCategories() {
    console.log('\n📚 Henter kategorier fra sacred-texts.com...\n');

    const categories = await getAllCategories();

    console.log(`Fandt ${categories.length} kategorier:\n`);
    console.log('─'.repeat(60));

    categories.forEach((cat, i) => {
        console.log(`  ${(i + 1).toString().padStart(2)}. ${cat.name}`);
    });

    console.log('─'.repeat(60));
    console.log('\nBrug: node src/index.js --category "<Kategori-navn>" for at downloade');
}

/**
 * Downloader alle bøger fra en kategori
 */
async function downloadCategory(categoryName) {
    console.log(`\n📂 Søger efter kategori: "${categoryName}"...\n`);

    // Find kategori-URL
    const categories = await getAllCategories();
    const category = categories.find(c =>
        c.name.toLowerCase() === categoryName.toLowerCase() ||
        c.name.toLowerCase().includes(categoryName.toLowerCase())
    );

    if (!category) {
        console.error(`❌ Kategori ikke fundet: "${categoryName}"`);
        console.log('\nBrug --list-categories for at se alle kategorier.');
        return;
    }

    console.log(`✅ Fandt kategori: ${category.name}`);
    console.log(`   URL: ${category.url}\n`);

    // Hent bøger i kategorien
    const books = await getBooksInCategory(category.url);

    if (books.length === 0) {
        console.log('⚠️ Ingen bøger fundet i denne kategori.');
        return;
    }

    console.log(`📖 Fandt ${books.length} bøger:\n`);
    books.forEach((book, i) => {
        console.log(`  ${(i + 1).toString().padStart(2)}. ${book.title}`);
    });
    console.log();

    // Download hver bog
    const results = {
        success: [],
        failed: []
    };

    for (let i = 0; i < books.length; i++) {
        const book = books[i];
        console.log(`\n${'═'.repeat(60)}`);
        console.log(`📥 Downloader bog ${i + 1}/${books.length}: ${book.title}`);
        console.log('═'.repeat(60));

        try {
            const { title, html } = await scrapeFullBook(book.url);
            const pdfPath = await bookToPdf(html, title, category.name);
            results.success.push({ title, path: pdfPath });
        } catch (error) {
            console.error(`❌ Fejl: ${error.message}`);
            results.failed.push({ title: book.title, error: error.message });
        }
    }

    // Vis opsummering
    console.log(`\n${'═'.repeat(60)}`);
    console.log('📊 OPSUMMERING');
    console.log('═'.repeat(60));
    console.log(`✅ Succesfulde: ${results.success.length}`);
    console.log(`❌ Fejlede: ${results.failed.length}`);

    if (results.failed.length > 0) {
        console.log('\nFejlede bøger:');
        results.failed.forEach(f => console.log(`  - ${f.title}: ${f.error}`));
    }
}

/**
 * Downloader en enkelt bog
 */
async function downloadBook(bookUrl) {
    console.log(`\n📖 Downloader bog fra: ${bookUrl}\n`);

    try {
        // Udtræk kategori-navn fra URL
        const urlParts = bookUrl.match(/sacred-texts\.com\/([^/]+)/);
        const categoryName = urlParts ? urlParts[1].charAt(0).toUpperCase() + urlParts[1].slice(1) : 'Uncategorized';

        const { title, html } = await scrapeFullBook(bookUrl);
        const pdfPath = await bookToPdf(html, title, categoryName);

        console.log(`\n${'═'.repeat(60)}`);
        console.log('✅ FÆRDIG!');
        console.log('═'.repeat(60));
        console.log(`PDF gemt: ${pdfPath}`);

    } catch (error) {
        console.error(`\n❌ Fejl ved download: ${error.message}`);
    }
}

/**
 * Main function
 */
async function main() {
    const options = parseArgs();

    console.log('\n🌟 HonoraWebScraper - sacred-texts.com PDF downloader\n');

    switch (options.mode) {
        case 'help':
            showHelp();
            break;

        case 'list-categories':
            await listCategories();
            break;

        case 'category':
            if (!options.value) {
                console.error('❌ Mangler kategori-navn. Brug: --category "<navn>"');
                return;
            }
            await downloadCategory(options.value);
            break;

        case 'book':
            if (!options.value) {
                console.error('❌ Mangler bog-URL. Brug: --book "<url>"');
                return;
            }
            await downloadBook(options.value);
            break;

        default:
            showHelp();
    }
}

// Kør programmet
main().catch(error => {
    console.error('💥 Uventet fejl:', error);
    process.exit(1);
});
