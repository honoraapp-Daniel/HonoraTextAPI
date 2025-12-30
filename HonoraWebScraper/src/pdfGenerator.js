// PDF Generator - Konverterer HTML til PDF via Puppeteer

import puppeteer from 'puppeteer';
import { config } from '../config.js';
import fs from 'fs/promises';
import path from 'path';
import { sanitizeFilename } from './bookScraper.js';

/**
 * Sikrer at output-mappen eksisterer
 * @param {string} dirPath 
 */
async function ensureDir(dirPath) {
    try {
        await fs.access(dirPath);
    } catch {
        await fs.mkdir(dirPath, { recursive: true });
    }
}

/**
 * Konverterer HTML til PDF
 * @param {string} htmlContent - HTML indhold
 * @param {string} outputPath - Sti til output PDF fil
 * @returns {Promise<string>} - Absolut sti til den oprettede PDF
 */
export async function htmlToPdf(htmlContent, outputPath) {
    // Sikr at output-mappen eksisterer
    const dir = path.dirname(outputPath);
    await ensureDir(dir);

    console.log(`  🖨️  Genererer PDF...`);

    // Start browser - brug systemets Chrome hvis muligt for bedre stabilitet
    const executablePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
    const browser = await puppeteer.launch({
        headless: 'new',
        executablePath,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--no-first-run',
            '--no-zygote'
        ]
    });

    try {
        const page = await browser.newPage();

        // Sæt HTML indhold
        await page.setContent(htmlContent, {
            waitUntil: 'networkidle0'
        });

        // Generer PDF
        await page.pdf({
            path: outputPath,
            format: config.pdf.format,
            margin: config.pdf.margin,
            printBackground: config.pdf.printBackground,
            displayHeaderFooter: true,
            headerTemplate: '<div></div>',
            footerTemplate: `
        <div style="font-size: 10px; text-align: center; width: 100%; color: #888;">
          <span class="pageNumber"></span> / <span class="totalPages"></span>
        </div>
      `
        });

        const absolutePath = path.resolve(outputPath);
        console.log(`  ✅ PDF gemt: ${absolutePath}`);

        return absolutePath;

    } finally {
        await browser.close();
    }
}

/**
 * Konverterer en bog til PDF
 * @param {string} bookHtml - HTML indhold af bogen
 * @param {string} bookTitle - Titel på bogen
 * @param {string} categoryName - Navn på kategorien (bruges til mappe-struktur)
 * @returns {Promise<string>} - Sti til den oprettede PDF
 */
export async function bookToPdf(bookHtml, bookTitle, categoryName = 'Uncategorized') {
    // Opret sikker filnavn
    const safeTitle = sanitizeFilename(bookTitle);
    const safeCategoryName = sanitizeFilename(categoryName);

    // Opret output sti
    const outputDir = path.join(config.outputDir, safeCategoryName);
    const outputPath = path.join(outputDir, `${safeTitle}.pdf`);

    return await htmlToPdf(bookHtml, outputPath);
}
