import express from 'express';
import cors from 'cors';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { getAllCategories, getBooksInCategory, getChapterCount } from './categoryCrawler.js';
import { scrapeFullBook, sanitizeFilename } from './bookScraper.js';
import { bookToPdf } from './pdfGenerator.js';
import { config } from '../config.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const port = 3001;
const LOG_FILE = path.join(__dirname, '../logs.json');

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, '../public')));

// Persistent Log Management
function loadPersistentLogs() {
    if (fs.existsSync(LOG_FILE)) {
        try {
            return JSON.parse(fs.readFileSync(LOG_FILE, 'utf8'));
        } catch (e) {
            console.error('Kunne ikke læse logs.json:', e);
            return [];
        }
    }
    return [];
}

function savePersistentLog(logEntry) {
    const logs = loadPersistentLogs();
    logs.push(logEntry);
    // Bevar kun de sidste 200 logs for at undgå at filen bliver for stor
    const limitedLogs = logs.slice(-200);
    fs.writeFileSync(LOG_FILE, JSON.stringify(limitedLogs, null, 2));
}

// Store clients for SSE
let clients = [];

// SSE Endpoint for progress and logs
app.get('/api/events', (req, res) => {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    const clientId = Date.now();
    const newClient = {
        id: clientId,
        res
    };

    clients.push(newClient);

    req.on('close', () => {
        clients = clients.filter(c => c.id !== clientId);
    });
});

function broadcast(event, data) {
    clients.forEach(c => {
        c.res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    });
}

function sendLog(message, type = 'info') {
    const logEntry = { message, type, timestamp: new Date().toISOString() };
    savePersistentLog(logEntry);
    broadcast('log', logEntry);
}

function sendProgress(current, total, title, bookTitle = '') {
    broadcast('progress', { current, total, title, bookTitle, percent: Math.round((current / total) * 100) });
}

// Check if a book PDF already exists
function checkFileExists(title, categoryName) {
    const safeTitle = sanitizeFilename(title);
    const safeCategory = sanitizeFilename(categoryName || 'Uncategorized');
    const folderPath = path.resolve(config.outputDir, safeCategory);

    if (!fs.existsSync(folderPath)) return false;

    try {
        const files = fs.readdirSync(folderPath);
        // Tjek for præcis match først
        if (files.includes(`${safeTitle}.pdf`)) return true;

        // Tjek om nogen fil starter med titlen (f.eks. "Theosophy_Index...")
        // Vi tjekker om den starter med safeTitle efterfulgt af enten underscore, mellemrum eller direkte .pdf
        const escapedTitle = safeTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const pattern = new RegExp(`^${escapedTitle}([_ ]|\\.pdf)`, 'i');
        return files.some(f => pattern.test(f));
    } catch (e) {
        return false;
    }
}

// API Endpoints
app.get('/api/categories', async (req, res) => {
    try {
        const categories = await getAllCategories();
        res.json(categories);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.get('/api/books', async (req, res) => {
    const { url, categoryName } = req.query;
    if (!url) return res.status(400).json({ error: 'URL is required' });

    try {
        const books = await getBooksInCategory(url);
        // Tilføj status for om bogen allerede er hentet
        const booksWithStatus = books.map(book => ({
            ...book,
            downloaded: checkFileExists(book.title, categoryName || 'Uncategorized')
        }));
        res.json(booksWithStatus);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// SSE endpoint for lazy loading chapter counts
app.get('/api/books/counts', async (req, res) => {
    const { urls } = req.query; // Comma-separated list of book URLs
    if (!urls) return res.status(400).json({ error: 'URLs required' });

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    const urlList = urls.split(',').map(u => decodeURIComponent(u));

    for (const bookUrl of urlList) {
        try {
            const count = await getChapterCount(bookUrl);
            res.write(`data: ${JSON.stringify({ url: bookUrl, chapters: count })}\n\n`);
        } catch (e) {
            res.write(`data: ${JSON.stringify({ url: bookUrl, chapters: 0 })}\n\n`);
        }
    }

    res.write('event: done\ndata: {}\n\n');
    res.end();
});

app.get('/api/history', (req, res) => {
    res.json(loadPersistentLogs());
});

app.post('/api/download/book', async (req, res) => {
    const { url, categoryName, title: requestedTitle } = req.body;
    if (!url) return res.status(400).json({ error: 'URL is required' });

    res.json({ message: 'Download startet' });

    try {
        const bookTitle = requestedTitle || 'Ukendt bog';
        sendLog(`Starter download af bog: ${bookTitle}`);
        const { title: scrapedTitle, html, jsonData } = await scrapeFullBook(url, (current, total, chapterTitle) => {
            sendProgress(current, total, chapterTitle, bookTitle);
        });

        const finalTitle = requestedTitle || scrapedTitle;

        // Save PDF
        sendLog(`Genererer PDF for: ${finalTitle}`);
        const pdfPath = await bookToPdf(html, finalTitle, categoryName || 'Uncategorized');

        // Save JSON file for pipeline
        const safeTitle = sanitizeFilename(finalTitle);
        const safeCategory = sanitizeFilename(categoryName || 'Uncategorized');
        const jsonDir = path.resolve(config.outputDir, safeCategory);
        if (!fs.existsSync(jsonDir)) {
            fs.mkdirSync(jsonDir, { recursive: true });
        }
        const jsonPath = path.join(jsonDir, `${safeTitle}.json`);
        fs.writeFileSync(jsonPath, JSON.stringify(jsonData, null, 2), 'utf8');
        console.log(`  ✅ JSON gemt: ${jsonPath}`);

        sendLog(`Færdig! PDF gemt i ${pdfPath}, JSON gemt i ${jsonPath}`, 'success');
        broadcast('complete', { title: finalTitle, pdfPath, jsonPath });
    } catch (error) {
        sendLog(`Fejl ved download: ${error.message}`, 'error');
    }
});

app.post('/api/download/category', async (req, res) => {
    const { url, name } = req.body;
    if (!url || !name) return res.status(400).json({ error: 'URL and name are required' });

    res.json({ message: 'Category download started' });

    try {
        sendLog(`Henter bogliste for kategori: ${name}`);
        const books = await getBooksInCategory(url);
        sendLog(`Fandt ${books.length} bøger. Starter download-kø...`);

        for (let i = 0; i < books.length; i++) {
            const book = books[i];

            // Tjek om bogen allerede findes
            if (checkFileExists(book.title, name)) {
                sendLog(`Springer over "${book.title}" - findes allerede.`, 'info');
                continue;
            }

            sendLog(`Downloader ${i + 1}/${books.length}: ${book.title}`);

            try {
                const { html } = await scrapeFullBook(book.url, (current, total, chapterTitle) => {
                    sendProgress(current, total, `[${i + 1}/${books.length}] ${chapterTitle}`, book.title);
                });

                const pdfPath = await bookToPdf(html, book.title, name);
                sendLog(`Gemt: ${book.title}`, 'success');
                broadcast('complete', { title: book.title });
            } catch (error) {
                sendLog(`Fejl ved "${book.title}": ${error.message}`, 'error');
            }
        }

        sendLog(`Kategori "${name}" er færdig!`, 'success');
        broadcast('complete-all', { category: name });
    } catch (error) {
        sendLog(`Fejl ved kategori download: ${error.message}`, 'error');
    }
});

app.listen(port, () => {
    console.log(`Server kører på http://localhost:${port}`);
});
