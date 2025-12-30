// Category Crawler - Henter kategorier og bøger fra sacred-texts.com

import axios from 'axios';
import * as cheerio from 'cheerio';
import { config } from '../config.js';

/**
 * Henter alle kategorier fra hovedsiden
 * @returns {Promise<Array<{name: string, url: string}>>}
 */
export async function getAllCategories() {
    const response = await axios.get(`${config.baseUrl}/index.htm`, {
        headers: { 'User-Agent': config.userAgent }
    });

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
                categories.push({
                    name: text,
                    url: fullUrl
                });
            } catch (e) {
                // Ignorer ugyldige URLs
            }
        }
        // Også matcher /neu/xxx/index.htm (sub-kategorier som Celtic)
        else if (href && href.match(/neu\/[a-z]+\/index\.htm$/i)) {
            try {
                const fullUrl = new URL(href, config.baseUrl).href;
                categories.push({
                    name: text,
                    url: fullUrl
                });
            } catch (e) {
                // Ignorer ugyldige URLs
            }
        }
    });

    // Fjern duplikater baseret på URL
    const uniqueCategories = [...new Map(categories.map(c => [c.url, c])).values()];

    return uniqueCategories;
}

/**
 * Henter alle bøger i en kategori
 * @param {string} categoryUrl - URL til kategori-index
 * @returns {Promise<Array<{title: string, url: string}>>}
 */
export async function getBooksInCategory(categoryUrl) {
    const response = await axios.get(categoryUrl, {
        headers: { 'User-Agent': config.userAgent }
    });

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

/**
 * Udtrækker kategori-navn fra URL
 * @param {string} url 
 * @returns {string}
 */
export function getCategoryNameFromUrl(url) {
    const match = url.match(/\/([a-z]+)\/index\.htm$/i);
    return match ? match[1].charAt(0).toUpperCase() + match[1].slice(1) : 'Unknown';
}
