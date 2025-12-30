// Book Scraper - Henter kapitler og indhold fra bøger

import axios from 'axios';
import * as cheerio from 'cheerio';
import { config } from '../config.js';

/**
 * Venter et antal millisekunder (rate limiting)
 */
function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Henter alle kapitel-links fra en bogs index-side
 * @param {string} bookIndexUrl - URL til bogens index.htm
 * @returns {Promise<Array<{title: string, url: string}>>}
 */
export async function getBookChapters(bookIndexUrl) {
  const response = await axios.get(bookIndexUrl, {
    headers: { 'User-Agent': config.userAgent }
  });

  const $ = cheerio.load(response.data);
  const chapters = [];
  const baseDir = bookIndexUrl.substring(0, bookIndexUrl.lastIndexOf('/'));

  // Navigation pages to skip (common on sacred-texts.com)
  const navigationPatterns = [
    /^start\s*reading$/i,
    /^page\s*index$/i,
    /^title\s*page$/i,
    /^table\s*of\s*contents$/i,
    /^contents$/i,
    /^index$/i,
    /^introduction$/i,  // Usually just ToC, not content
    /^errata$/i,
    /^next$/i,
    /^previous$/i,
    /^prev$/i,
    /^home$/i,
    /^\s*$/ // Empty titles
  ];

  // Find alle kapitel-links
  $('a').each((_, el) => {
    const href = $(el).attr('href');
    let text = $(el).text().trim();

    if (!href) return;

    // Skip navigation links, external links, og index selv
    if (href.startsWith('http') && !href.includes('sacred-texts.com')) return;
    if (href === 'index.htm' || href === './index.htm') return;
    if (href.startsWith('#')) return;
    if (href.includes('..')) return; // Skip parent directory links
    if (href.endsWith('.txt') || href.endsWith('.gz')) return; // Skip text files

    // Skip navigation pages based on link text
    const isNavigation = navigationPatterns.some(pattern => pattern.test(text));
    if (isNavigation) {
      console.log(`  ⏭️ Skipping navigation page: "${text}"`);
      return;
    }

    // Skip if filename suggests navigation (sof00.htm, sof01.htm typically are nav)
    const filename = href.toLowerCase();
    if (filename.match(/00\.htm$/) || filename.match(/01\.htm$/)) {
      // Check if it's actually a chapter by looking at the link text
      if (!text.match(/chapter/i) && !text.match(/^[IVXLC]+\./)) {
        console.log(`  ⏭️ Skipping likely navigation file: ${href} ("${text}")`);
        return;
      }
    }

    // Match .htm filer i samme mappe
    if (href.match(/^[a-z0-9_-]+\.htm$/i)) {
      const fullUrl = `${baseDir}/${href}`;

      // Undgå duplikater
      if (!chapters.find(c => c.url === fullUrl)) {
        // Clean up title - remove page numbers
        text = text.replace(/page\s+\d+/gi, '').trim();

        chapters.push({
          title: text || href.replace('.htm', ''),
          url: fullUrl
        });
      }
    }
  });

  console.log(`📚 Found ${chapters.length} actual chapters (filtered out navigation)`);
  return chapters;
}

/**
 * Henter og renser indhold fra en kapitel-side
 * @param {string} chapterUrl - URL til kapitlet
 * @returns {Promise<{title: string, content: string}>}
 */
export async function fetchChapterContent(chapterUrl) {
  const response = await axios.get(chapterUrl, {
    headers: { 'User-Agent': config.userAgent }
  });

  const $ = cheerio.load(response.data);

  // Fjern navigation og andre uønskede elementer
  $('script').remove();
  $('style').remove();
  $('noscript').remove();
  $('iframe').remove();
  $('nav').remove();
  $('header').remove();
  $('footer').remove();

  // Fjern "Next", "Previous", "Index" navigation links
  $('a').each((_, el) => {
    const text = $(el).text().toLowerCase().trim();
    if (['next', 'previous', 'prev', 'index', 'contents', 'title page'].includes(text)) {
      $(el).parent().remove();
    }
  });

  // Fjern HR elementer der typisk bruges som separatorer
  $('hr').first().remove();
  $('hr').last().remove();

  // Hent titel fra h1, h2 eller title
  let title = $('h1').first().text().trim() ||
    $('h2').first().text().trim() ||
    $('title').text().trim() ||
    'Untitled';

  // Hent body content
  let content = $('body').html() || '';

  // Rens content for at fjerne tomme elementer
  content = content.replace(/<p>\s*<\/p>/g, '');
  content = content.replace(/<br\s*\/?>\s*<br\s*\/?>/g, '<br>');

  // Fjern "Next: X" og "Previous: X" navigation tekst
  content = content
    .replace(/Next:\s*[^<]+/gi, '')
    .replace(/Previous:\s*[^<]+/gi, '');

  // Fjern sidetal som "1 / 80"
  content = content.replace(/\d+\s*\/\s*\d+/g, '');

  // Fjern scanning metadata
  content = content.replace(/Scanned,?\s*proofed.*?sacred-texts\.com[^<]*/gi, '');

  // Fjern ", at sacred-texts.com" referencer
  content = content.replace(/,?\s*at\s+sacred-texts\.com/gi, '');

  // Fjern "page X" fra ToC-lignende sektioner
  content = content.replace(/\bpage\s+\d+\b/gi, '');

  return {
    title,
    content
  };
}

/**
 * Scraper en hel bog og returnerer samlet HTML
 * @param {string} bookUrl - URL til bogens index.htm
 * @param {Function} progressCallback - Callback for progress updates
 * @returns {Promise<{title: string, html: string}>}
 */
export async function scrapeFullBook(bookUrl, progressCallback = null) {
  // Hent bog-titel fra index-siden
  const indexResponse = await axios.get(bookUrl, {
    headers: { 'User-Agent': config.userAgent }
  });
  const $index = cheerio.load(indexResponse.data);
  let bookTitle = $index('title').text().trim() ||
    $index('h1').first().text().trim() ||
    'Unknown Book';

  // Rens bogtitel for site-metadata
  bookTitle = bookTitle
    .replace(/\s*Index\s*\|\s*Sacred\s*Texts\s*Archive/gi, '')
    .replace(/\s*\|\s*Sacred\s*Texts/gi, '')
    .replace(/\s*Index$/i, '')
    .trim();

  // Hent kapitler
  const chapters = await getBookChapters(bookUrl);

  if (chapters.length === 0) {
    throw new Error(`Ingen kapitler fundet for: ${bookUrl}`);
  }

  console.log(`📚 Fandt ${chapters.length} kapitler i "${bookTitle}"`);

  // Byg HTML dokument
  let fullHtml = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>${escapeHtml(bookTitle)}</title>
  <style>
    body {
      font-family: Georgia, 'Times New Roman', serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 20px;
      line-height: 1.6;
      color: #333;
    }
    h1, h2, h3 {
      color: #1a1a1a;
      margin-top: 2em;
    }
    .book-title {
      text-align: center;
      border-bottom: 2px solid #333;
      padding-bottom: 20px;
      margin-bottom: 40px;
    }
    .chapter {
      page-break-before: always;
      margin-top: 40px;
    }
    .chapter:first-of-type {
      page-break-before: avoid;
    }
    blockquote {
      margin-left: 40px;
      font-style: italic;
      color: #555;
    }
    .page-number {
      color: #888;
      font-size: 0.8em;
    }
    .honora-chapter-title {
      font-size: 1.5em;
      border-bottom: 1px solid #ccc;
      padding-bottom: 10px;
      margin-bottom: 20px;
    }
    .table-of-contents {
      margin-bottom: 40px;
      padding: 20px;
      background: #f9f9f9;
      border: 1px solid #ddd;
    }
    .table-of-contents ul {
      list-style-type: none;
      padding-left: 0;
    }
    .table-of-contents li {
      padding: 5px 0;
    }
  </style>
</head>
<body>
  <div class="book-title">
    <h1>${escapeHtml(bookTitle)}</h1>
  </div>
`;

  // Build Table of Contents
  let tocHtml = '<div class="table-of-contents"><h2>Table of Contents</h2><ul>';
  for (let i = 0; i < chapters.length; i++) {
    // Rens kapitel-titel for "page X" referencer
    const cleanTitle = chapters[i].title.replace(/page\s+\d+/gi, '').trim();
    tocHtml += `<li>Chapter ${i + 1}: ${escapeHtml(cleanTitle)}</li>`;
  }
  tocHtml += '</ul></div>';
  fullHtml += tocHtml;

  // Hent hvert kapitel
  for (let i = 0; i < chapters.length; i++) {
    const chapter = chapters[i];

    if (progressCallback) {
      progressCallback(i + 1, chapters.length, chapter.title);
    }

    console.log(`  📖 Henter kapitel ${i + 1}/${chapters.length}: ${chapter.title.substring(0, 50)}...`);

    try {
      const { content } = await fetchChapterContent(chapter.url);

      // Rens kapitel-titel
      const cleanChapterTitle = chapter.title.replace(/page\s+\d+/gi, '').trim();

      fullHtml += `
  <div class="chapter" data-chapter-index="${i + 1}">
    <!-- HONORA_CHAPTER_START: ${i + 1} | ${escapeHtml(cleanChapterTitle)} -->
    <h2 class="honora-chapter-title">Chapter ${i + 1}: ${escapeHtml(cleanChapterTitle)}</h2>
    ${content}
    <!-- HONORA_CHAPTER_END: ${i + 1} -->
  </div>
`;

      // Rate limiting
      await delay(config.requestDelay);

    } catch (error) {
      console.error(`  ⚠️ Fejl ved hentning af ${chapter.url}: ${error.message}`);
      // Rens kapitel-titel
      const cleanChapterTitle = chapter.title.replace(/page\s+\d+/gi, '').trim();
      fullHtml += `
  <div class="chapter" data-chapter-index="${i + 1}">
    <!-- HONORA_CHAPTER_START: ${i + 1} | ${escapeHtml(cleanChapterTitle)} -->
    <h2 class="honora-chapter-title">Chapter ${i + 1}: ${escapeHtml(cleanChapterTitle)}</h2>
    <p><em>Kunne ikke hente dette kapitel.</em></p>
    <!-- HONORA_CHAPTER_END: ${i + 1} -->
  </div>
`;
    }
  }

  fullHtml += `
</body>
</html>`;

  return {
    title: bookTitle,
    html: fullHtml
  };
}

/**
 * Escaper HTML special characters
 */
function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Genererer et sikkert filnavn fra en titel
 */
export function sanitizeFilename(title) {
  return title
    .replace(/[<>:"/\\|?*]/g, '') // Fjern ugyldige tegn
    .replace(/\s+/g, '_')         // Erstat mellemrum med underscore
    .replace(/_+/g, '_')          // Fjern multiple underscores
    .replace(/^_|_$/g, '')        // Fjern leading/trailing underscores
    .substring(0, 100);           // Begræns længde
}
