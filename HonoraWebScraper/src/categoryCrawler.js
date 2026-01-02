// Category Crawler - Henter kategorier og bøger fra sacred-texts.com

import axios from 'axios';
import * as cheerio from 'cheerio';
import fs from 'fs';
import { config } from '../config.js';

const MAX_RETRIES = 2;
const RETRY_DELAY = 500;

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Henter en URL med simpel retry-logik (HURTIGT - ingen lange ventetider)
 */
async function fetchUrl(url) {
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
        try {
            if (attempt > 0) {
                await delay(RETRY_DELAY);
            }
            return await axios.get(url, {
                headers: { 'User-Agent': config.userAgent },
                timeout: 10000
            });
        } catch (error) {
            // Last attempt - throw error
            if (attempt === MAX_RETRIES) {
                throw error;
            }
            // Network error - retry quickly
            if (error.code === 'ECONNRESET' || error.code === 'ETIMEDOUT' || !error.response) {
                continue;
            }
            // 429 or other HTTP error - just throw, don't wait forever
            throw error;
        }
    }
}

/**
 * Henter alle kategorier fra hovedsiden
 * @returns {Promise<Array<{name: string, url: string}>>}
 */
export async function getAllCategories() {
    try {
        const response = await fetchUrl(`${config.baseUrl}/index.htm`);
        const $ = cheerio.load(response.data);
        const categories = [];

        // Find alle links der peger på /xxx/index.htm (kategori-links)
        $('a').each((_, el) => {
            const href = $(el).attr('href');
            const text = $(el).text().trim();

            // Match kategori-URLs (f.eks. /bud/index.htm, /afr/index.htm, ./afr/index.htm)
            if (href && href.match(/[a-z0-9]+\/index\.htm$/i)) {
                try {
                    const fullUrl = new URL(href, config.baseUrl).href;
                    categories.push({ name: text, url: fullUrl });
                } catch (e) { }
            }
            // Også matcher /neu/xxx/index.htm (sub-kategorier som Celtic)
            else if (href && href.match(/neu\/[a-z]+\/index\.htm$/i)) {
                try {
                    const fullUrl = new URL(href, config.baseUrl).href;
                    categories.push({ name: text, url: fullUrl });
                } catch (e) { }
            }
        });

        const uniqueCategories = [...new Map(categories.map(c => [c.url, c])).values()];
        return uniqueCategories;

    } catch (err) {
        console.error("CRITICAL ERROR: Failed to fetch categories:", err.message);
        // Return empty array instead of throwing to prevent frontend crash
        return [];
    }
}

/**
 * Henter alle bøger i en kategori
 * @param {string} categoryUrl - URL til kategori-index
 * @returns {Promise<Array<{title: string, url: string}>>}
 */
export async function getBooksInCategory(categoryUrl) {
    const response = await fetchUrl(categoryUrl);

    const $ = cheerio.load(response.data);
    const books = [];

    // Find alle links der peger på bog-index sider
    $('a').each((_, el) => {
        const href = $(el).attr('href');
        const text = $(el).text().trim();

        if (!href || !text) return;

        // Match relative links til bog-mapper (f.eks. saft/index.htm, bb/index.htm)
        if (href.match(/^[a-z0-9_-]+\/index\.htm$/i)) {
            try {
                const fullUrl = new URL(href, categoryUrl).href;

                // Tjek om bogen faktisk er i en undermappe af kategorien
                const categoryUrlObj = new URL(categoryUrl);
                const bookUrlObj = new URL(fullUrl);

                // Fjern index.htm fra paths
                const categoryPath = categoryUrlObj.pathname.substring(0, categoryUrlObj.pathname.lastIndexOf('/') + 1);
                const bookPath = bookUrlObj.pathname;

                if (bookPath.startsWith(categoryPath) && bookPath !== categoryUrlObj.pathname) {
                    books.push({
                        title: text,
                        url: fullUrl
                    });
                }
            } catch (e) { }
        }
    });

    // Fjern duplikater
    const uniqueBooks = [...new Map(books.map(b => [b.url, b])).values()];
    return uniqueBooks;
}

// Chapter count cache
const CACHE_FILE = new URL('../chapter-cache.json', import.meta.url).pathname;

function loadCache() {
    try {
        if (fs.existsSync(CACHE_FILE)) {
            return JSON.parse(fs.readFileSync(CACHE_FILE, 'utf8'));
        }
    } catch (e) { }
    return {};
}

function saveCache(cache) {
    try {
        fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2));
    } catch (e) { }
}

/**
 * Henter antal kapitler for en given bog (med cache)
 * @param {string} bookUrl 
 * @returns {Promise<number>}
 */
export async function getChapterCount(bookUrl) {
    // Check cache first
    const cache = loadCache();
    if (cache[bookUrl] !== undefined) {
        return cache[bookUrl];
    }

    try {
        const response = await fetchUrl(bookUrl);
        const $ = cheerio.load(response.data);

        // Tæl links der ser ud som kapitler
        let count = 0;
        $('a').each((_, el) => {
            const href = $(el).attr('href');
            if (!href) return;
            // Ignorer navigation/standard links
            if (href.startsWith('mailto:') || href.startsWith('http') || href === 'index.htm' || href.startsWith('../')) return;

            // Hvis det er en .htm fil, tæl som kapitel
            if (href.endsWith('.htm')) {
                count++;
            }
        });

        // Single-page book detection: look for inline chapter headers
        if (count === 0) {
            const bodyText = $('body').text();
            const chapterMatches = bodyText.match(/CHAPTER\s+[IVXLCDM]+|CHAPTER\s+\d+/gi);
            if (chapterMatches) {
                count = chapterMatches.length;
            } else {
                count = 1; // Single page = 1 chapter
            }
        }

        // Save to cache
        cache[bookUrl] = count;
        saveCache(cache);

        return count;
    } catch (e) {
        return 0;
    }
}

/**
 * Udtrækker kategori-navn fra URL
 * @param {string} url 
 * @returns {string}
 */
export function getCategoryNameFromUrl(url) {
    const match = url.match(/\/([a-z]+)\/index\.htm$/i);
    return match ? match[1].charAt(0).toUpperCase() + match[1].slice(1) : 'Unknown';
}
