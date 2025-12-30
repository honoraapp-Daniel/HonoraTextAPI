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
 * Konverterer tal til engelske ord (1-30)
 */
const numberWords = [
  '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
  'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen', 'Twenty',
  'Twenty-One', 'Twenty-Two', 'Twenty-Three', 'Twenty-Four', 'Twenty-Five', 'Twenty-Six', 'Twenty-Seven', 'Twenty-Eight', 'Twenty-Nine', 'Thirty'
];

function numberToWord(num) {
  if (num >= 1 && num <= 30) {
    return numberWords[num];
  }
  return num.toString();
}

/**
 * Konverterer romertal til arabiske tal
 */
function romanToNumber(roman) {
  const romanNumerals = {
    'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000
  };

  let result = 0;
  const upper = roman.toUpperCase();

  for (let i = 0; i < upper.length; i++) {
    const current = romanNumerals[upper[i]] || 0;
    const next = romanNumerals[upper[i + 1]] || 0;

    if (current < next) {
      result -= current;
    } else {
      result += current;
    }
  }

  return result;
}

/**
 * Renser og formaterer kapitel-titel
 * Input: "Chapter I. Salaam" eller "Chapter 1: The Beginning"
 * Output: "Chapter One - Salaam" eller "Chapter One - The Beginning"
 */
function cleanChapterTitle(rawTitle, index) {
  let title = rawTitle.trim();

  // Fjern "page X" referencer
  title = title.replace(/page\s+\d+/gi, '').trim();

  // Fjern "Chapter X:" eller "Chapter X." prefix (vi tilføjer vores egen)
  title = title.replace(/^Chapter\s+(\d+|[IVXLCDM]+)[:\.\s-]*/i, '').trim();

  // Hvis titlen nu er tom eller bare et romertal/tal, brug index
  if (!title || title.match(/^[IVXLCDM]+$/i) || title.match(/^\d+$/)) {
    title = '';
  }

  // Byg den rene titel: "Chapter 1 - Title" eller bare "Chapter 1"
  const chapterNumber = index;
  if (title) {
    return `Chapter ${chapterNumber} - ${title}`;
  } else {
    return `Chapter ${chapterNumber}`;
  }
}

/**
 * Fjerner duplikerede kapitel-headers fra indhold
 * Fjerner ting som "Chapter I", "SALAAM" headers der matcher kapitlet
 */
function cleanChapterContent(content, chapterTitle) {
  let cleaned = content;

  // Fjern "Chapter X" headers (romertal eller tal)
  cleaned = cleaned.replace(/<h[1-6][^>]*>\s*Chapter\s+[IVXLCDM]+\s*<\/h[1-6]>/gi, '');
  cleaned = cleaned.replace(/<h[1-6][^>]*>\s*Chapter\s+\d+\s*<\/h[1-6]>/gi, '');

  // Fjern standalone kapitel-titler der matcher (f.eks. <h2>SALAAM</h2>)
  // Ekstraher kapitel-navnet fra den rensede titel
  const titleMatch = chapterTitle.match(/Chapter\s+\d+\s*-\s*(.+)/i);
  if (titleMatch) {
    const subTitle = titleMatch[1].trim();
    // Fjern header der matcher sub-titlen (case-insensitive)
    const escapedTitle = subTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const headerPattern = new RegExp(`<h[1-6][^>]*>\\s*${escapedTitle}\\s*</h[1-6]>`, 'gi');
    cleaned = cleaned.replace(headerPattern, '');
  }

  // Fjern tomme headers
  cleaned = cleaned.replace(/<h[1-6][^>]*>\s*<\/h[1-6]>/gi, '');

  // Fjern multiple line breaks
  cleaned = cleaned.replace(/(<br\s*\/?>\s*){3,}/gi, '<br><br>');

  return cleaned;
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
    /^errata$/i,
    /^next$/i,
    /^previous$/i,
    /^prev$/i,
    /^home$/i,
    /^«\s*previous/i,           // « Previous: X
    /^next\s*:/i,                // Next: X
    /^next\s*»/i,                // Next: X »
    /»\s*$/,                     // Ends with »
    /^«/,                        // Starts with «
    /^\s*$/                      // Empty titles
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

  // Fjern book attribution linje (den grønne tekst med forfatter/titel)
  // Typisk i format: "Title, by Author, [Year]"
  $('font[color="GREEN"]').remove();
  $('font[color="green"]').remove();

  // Fjern også evt. center-element med attribution
  $('center').each((_, el) => {
    const text = $(el).text();
    // Fjern hvis det ligner attribution (indeholder "by" og år i brackets)
    if (text.match(/,\s*by\s+.+,\s*\[\d{4}\]/i)) {
      $(el).remove();
    }
  });

  // Fjern sidetal som "p. 5" eller "p.5"
  $('font[size="1"]').each((_, el) => {
    const text = $(el).text().trim();
    if (text.match(/^p\.?\s*\d+$/i)) {
      $(el).remove();
    }
  });
  $('small').each((_, el) => {
    const text = $(el).text().trim();
    if (text.match(/^p\.?\s*\d+$/i)) {
      $(el).remove();
    }
  });

  // Hent body content
  let content = $('body').html() || '';

  // Rens content for at fjerne tomme elementer
  content = content.replace(/<p>\s*<\/p>/g, '');
  content = content.replace(/<br\s*\/?>/gi, '<br>');

  // Fjern "Next: X" og "Previous: X" navigation tekst
  content = content
    .replace(/Next:\s*[^<]+/gi, '')
    .replace(/Previous:\s*[^<]+/gi, '');

  // Fjern sidetal som "1 / 80" eller "p. 5"
  content = content.replace(/\d+\s*\/\s*\d+/g, '');
  content = content.replace(/<[^>]*>\s*p\.?\s*\d+\s*<\/[^>]*>/gi, '');

  // Fjern scanning metadata
  content = content.replace(/Scanned,?\s*proofed.*?sacred-texts\.com[^<]*/gi, '');

  // Fjern ", at sacred-texts.com" referencer
  content = content.replace(/,?\s*at\s+sacred-texts\.com/gi, '');

  // Fjern "page X" fra ToC-lignende sektioner
  content = content.replace(/\bpage\s+\d+\b/gi, '');

  // Fjern book attribution fra content (backup cleanup)
  // Match: "Title, by Author Name, [Year]" pattern
  content = content.replace(/<[^>]*>[^<]*,\s*by\s+[^<]+,\s*\[\d{4}\][^<]*<\/[^>]*>/gi, '');

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
    .replace(/\s*Index\s*\|\s*Internet\s*Sacred\s*Text\s*Archive/gi, '')
    .replace(/\s*Index\s*\|\s*Sacred\s*Texts\s*Archive/gi, '')
    .replace(/\s*\|\s*Sacred\s*Texts/gi, '')
    .replace(/\s*\|\s*Internet\s*Sacred\s*Text\s*Archive/gi, '')
    .replace(/\s*Index$/i, '')
    .trim();

  // Hent kapitler først så vi kan hente attribution fra første kapitel
  const chapters = await getBookChapters(bookUrl);

  if (chapters.length === 0) {
    throw new Error(`Ingen kapitler fundet for: ${bookUrl}`);
  }

  console.log(`📚 Fandt ${chapters.length} kapitler i "${bookTitle}"`);

  // Ekstraher forfatter og år fra første kapitels side (mere pålidelig end index)
  let bookAuthor = 'Unknown Author';
  let bookYear = '';
  let bookPublisher = 'Internet Sacred Texts Archive';

  try {
    // Hent første kapitel for at finde attribution
    const firstChapterUrl = chapters[0].url;
    console.log(`  📋 Henter metadata fra: ${firstChapterUrl}`);

    const firstChapterResponse = await axios.get(firstChapterUrl, {
      headers: { 'User-Agent': config.userAgent }
    });
    const $first = cheerio.load(firstChapterResponse.data);

    // Find grøn font med attribution (mest pålidelig)
    let attributionText = '';

    // Funktion til at tjekke om tekst er en billedtekst (og ikke bog-attribution)
    const isImageCaption = (text) => {
      // Billedtekster indeholder typisk disse ord
      const captionPatterns = [
        /\(detail\)/i,
        /\(public domain/i,
        /painting/i,
        /illustration/i,
        /\bimage\b/i,
        /\bphoto\b/i,
        /\bpicture\b/i,
        /\bportrait\b/i,
        /\bartwork\b/i,
        /\bdrawing\b/i,
        /\bengraving\b/i,
        /\bfresco\b/i,
        /\bmanuscript\b/i,
        /Day and the Dawn/i,       // Specifikt The Kybalion billede
        /Herbert Draper/i,          // Specifikt The Kybalion kunstner
      ];
      return captionPatterns.some(p => p.test(text));
    };

    // Funktion til at tjekke om tekst ligner bog-attribution
    const isBookAttribution = (text) => {
      // Skal have "by" og årstal
      if (!text.match(/,?\s*by\s+.+,?\s*\[\d{4}\]/i)) return false;
      // Skal IKKE være billedtekst
      if (isImageCaption(text)) return false;
      return true;
    };

    // Metode 1: Grøn font - find ALLE og vælg den rigtige
    const greenTexts = [];
    $first('font[color="GREEN"], font[color="green"]').each((_, el) => {
      const text = $first(el).text().trim();
      if (text.match(/,?\s*by\s+.+,?\s*\[\d{4}\]/i)) {
        greenTexts.push(text);
      }
    });

    // Vælg den første der IKKE er billedtekst
    for (const text of greenTexts) {
      if (isBookAttribution(text)) {
        attributionText = text;
        break;
      }
    }

    // Metode 2: Kig i center elementer
    if (!attributionText) {
      $first('center').each((_, el) => {
        const text = $first(el).text().trim();
        if (isBookAttribution(text)) {
          attributionText = text;
          return false;
        }
      });
    }

    // Metode 3: Kig efter bogens titel i body tekst med "by" mønster
    if (!attributionText) {
      const bodyText = $first('body').text();
      // Match bogens titel efterfulgt af ", by Author, [Year]"
      const cleanTitle = bookTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); // Escape regex
      const titlePattern = new RegExp(`${cleanTitle}[^\\[]*by\\s+([^\\[]+)\\[(\\d{4})\\]`, 'i');
      const titleMatch = bodyText.match(titlePattern);
      if (titleMatch) {
        attributionText = `${bookTitle}, by ${titleMatch[1]}[${titleMatch[2]}]`;
      }
    }

    console.log(`  📋 Attribution: "${attributionText.substring(0, 80)}${attributionText.length > 80 ? '...' : ''}"`);

    if (attributionText) {
      // Parse attribution: "Title, by Author Name, [Year]" eller "Title, by Author, pseud. Real Name, [Year]"
      const fullMatch = attributionText.match(/by\s+(.+?),?\s*\[(\d{4})\]/i);
      if (fullMatch) {
        bookAuthor = fullMatch[1].trim().replace(/,\s*$/, '');
        bookYear = fullMatch[2];
      }
    }

    console.log(`  👤 Author: ${bookAuthor}`);
    console.log(`  📅 Year: ${bookYear || 'Unknown'}`);

  } catch (err) {
    console.log(`  ⚠️ Kunne ikke hente metadata: ${err.message}`);
  }

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
    .book-meta {
      text-align: center;
      color: #666;
      margin-top: 10px;
    }
    .book-author {
      font-size: 1.2em;
      font-style: italic;
    }
    .book-year {
      font-size: 1em;
      margin-top: 5px;
    }
    .book-publisher {
      font-size: 0.9em;
      margin-top: 10px;
      color: #888;
    }
  </style>
</head>
<body>
  <div class="book-title">
    <h1>${escapeHtml(bookTitle)}</h1>
    <div class="book-meta">
      <div class="book-author">${escapeHtml(bookAuthor)}</div>
      ${bookYear ? `<div class="book-year">${escapeHtml(bookYear)}</div>` : ''}
      <div class="book-publisher">${escapeHtml(bookPublisher)}</div>
    </div>
  </div>
`;

  // Build Table of Contents
  let tocHtml = '<div class="table-of-contents"><h2>Table of Contents</h2><ul>';
  for (let i = 0; i < chapters.length; i++) {
    const formattedTitle = cleanChapterTitle(chapters[i].title, i + 1);
    tocHtml += `<li>${escapeHtml(formattedTitle)}</li>`;
  }
  tocHtml += '</ul></div>';
  fullHtml += tocHtml;

  // Hent hvert kapitel
  for (let i = 0; i < chapters.length; i++) {
    const chapter = chapters[i];
    const chapterIndex = i + 1;

    if (progressCallback) {
      progressCallback(chapterIndex, chapters.length, chapter.title);
    }

    // Opret ren kapitel-titel: "Chapter One - Salaam"
    const formattedTitle = cleanChapterTitle(chapter.title, chapterIndex);
    console.log(`  📖 Henter kapitel ${chapterIndex}/${chapters.length}: ${formattedTitle}...`);

    try {
      let { content } = await fetchChapterContent(chapter.url);

      // Fjern duplikerede kapitel-headers fra indholdet
      content = cleanChapterContent(content, formattedTitle);

      fullHtml += `
  <div class="chapter" data-chapter-index="${chapterIndex}">
    <!-- HONORA_CHAPTER_START: ${chapterIndex} | ${escapeHtml(formattedTitle)} -->
    <h2 class="honora-chapter-title">${escapeHtml(formattedTitle)}</h2>
    ${content}
    <!-- HONORA_CHAPTER_END: ${chapterIndex} -->
  </div>
`;

      // Rate limiting
      await delay(config.requestDelay);

    } catch (error) {
      console.error(`  ⚠️ Fejl ved hentning af ${chapter.url}: ${error.message}`);
      fullHtml += `
  <div class="chapter" data-chapter-index="${chapterIndex}">
    <!-- HONORA_CHAPTER_START: ${chapterIndex} | ${escapeHtml(formattedTitle)} -->
    <h2 class="honora-chapter-title">${escapeHtml(formattedTitle)}</h2>
    <p><em>Kunne ikke hente dette kapitel.</em></p>
    <!-- HONORA_CHAPTER_END: ${chapterIndex} -->
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
