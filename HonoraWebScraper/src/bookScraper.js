// Book Scraper - Henter kapitler og indhold fra bøger

import axios from 'axios';
import * as cheerio from 'cheerio';
import { config } from '../config.js';

const MAX_RETRIES = 3;
const RETRY_DELAY_BASE = 2000;
const REQUEST_DELAY = 1000;

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Normalize excessive whitespace and newlines in text.
 * - Replaces multiple consecutive newlines (with or without spaces) to max 2 newlines
 * - Cleans up patterns like "\n  \n \n" to just "\n\n"
 */
function normalizeWhitespace(text) {
  if (!text) return text;

  // Replace multiple newlines (with optional whitespace between) with max 2
  text = text.replace(/(\n\s*){3,}/g, '\n\n');

  // Clean up newlines with only spaces between them
  text = text.replace(/\n[ \t]+\n/g, '\n\n');

  // Trim leading/trailing whitespace
  return text.trim();
}

/**
 * Henter en URL med robust retry-logik for 429 errors
 */
async function fetchUrl(url) {
  let lastError;
  // Brug config.maxRetries hvis tilgængelig, ellers default
  const retries = config.maxRetries || MAX_RETRIES;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      // Kun vent ved retries, ikke første forsøg
      if (attempt > 0) {
        const backoff = (config.retryDelay || RETRY_DELAY_BASE) * Math.pow(2, attempt - 1);
        console.log(`    ⏳ Venter ${backoff}ms før retry ${attempt}/${retries} for ${url}...`);
        await delay(backoff);
      }

      return await axios.get(url, {
        headers: { 'User-Agent': config.userAgent },
        timeout: 30000
      });
    } catch (error) {
      lastError = error;
      // Hvis 429 (Too Many Requests) -> vent længere
      if (error.response && error.response.status === 429) {
        console.warn(`    ⚠️ Rate limit (429) på ${url}. Venter 10 sekunder...`);
        await delay(10000 + (attempt * 2000));
        continue;
      }
      // Netværksfejl -> prøv igen
      if (error.code === 'ECONNRESET' || error.code === 'ETIMEDOUT' || !error.response) {
        console.warn(`    ⚠️ Netværksfejl (${error.code}) på ${url}. Prøver igen...`);
        continue;
      }
      throw error;
    }
  }
  throw lastError;
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

// List of introduction-like chapter titles that should be labeled as "Chapter 0"
// These are prefatory material, not the actual first chapter of content
const INTRODUCTION_TITLES = [
  'introduction',
  'preface',
  'foreword',
  'prologue',
  'preliminary remarks',
  "editor's preface",
  "editor's introduction",
  'introductory note',
  'introductory notes',
  'background',
  'context',
  'scope and purpose',
  'preliminary analysis',
  'opening',
  'setting the stage',
  'why this book',
  'before you begin',
  'a note to the reader',
  'invocation',
  'opening discourse',
  'on the nature of this work',
  'introduction to the mysteries',
  'preliminary discourse',
  'author\'s note',
  'translator\'s note',
  'dedication',
  'acknowledgements',
  'acknowledgments'
];

/**
 * Checks if a title is an introduction-like chapter
 * @param {string} title - The chapter title to check
 * @returns {boolean}
 */
function isIntroductionChapter(title) {
  if (!title) return false;
  const normalizedTitle = title.toLowerCase().trim();
  return INTRODUCTION_TITLES.some(intro => normalizedTitle === intro || normalizedTitle.includes(intro));
}

/**
 * Renser og formaterer kapitel-titel
 * Input: "Chapter I. Salaam" eller "Chapter 1: The Beginning"
 * Output: "Chapter One - Salaam" eller "Chapter One - The Beginning"
 * 
 * Special case: If this is the FIRST chapter (index=1) and title matches
 * an introduction-like pattern, label it as "Chapter 0 - X"
 */
function cleanChapterTitle(rawTitle, index, isFirstChapter = false) {
  let title = rawTitle.trim();

  // Fjern "page X" referencer
  title = title.replace(/page\s+\d+/gi, '').trim();

  // Fjern "Chapter X:" eller "Chapter X." prefix (vi tilføjer vores egen)
  title = title.replace(/^Chapter\s+(\d+|[IVXLCDM]+)[:.\s-]*/i, '').trim();

  // Hvis titlen nu er tom eller bare et romertal/tal, brug index
  if (!title || title.match(/^[IVXLCDM]+$/i) || title.match(/^\d+$/)) {
    title = '';
  }

  // Forsøg at læse kapitelnummer fra rå titlen (behold tal, konverter ord/romertal)
  const wordMap = {
    one: 1, two: 2, three: 3, four: 4, five: 5,
    six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
    eleven: 11, twelve: 12, thirteen: 13, fourteen: 14,
    fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18,
    nineteen: 19, twenty: 20, thirty: 30, forty: 40, fifty: 50
  };

  let chapterNumber = index;
  const prefixMatch = rawTitle.match(/^Chapter\s+([IVXLCDM]+|\d+|[A-Za-z]+)[\s:.\-–]*(.*)$/i);
  if (prefixMatch) {
    const token = prefixMatch[1].trim();
    const remainder = prefixMatch[2].trim();
    if (/^\d+$/.test(token)) {
      chapterNumber = parseInt(token, 10);
    } else if (wordMap[token.toLowerCase()]) {
      chapterNumber = wordMap[token.toLowerCase()];
    } else {
      const romanVal = romanToNumber(token);
      if (romanVal > 0) chapterNumber = romanVal;
    }
    if (remainder) {
      title = remainder;
    }
  }

  // SPECIAL: If this is the first chapter and title is introduction-like, use Chapter 0
  if (isFirstChapter && title && isIntroductionChapter(title)) {
    console.log(`  📌 Detected introduction chapter: "${title}" → Chapter 0`);
    return `Chapter 0 - ${title}`;
  }

  // Byg den rene titel: "Chapter <tal> - Title" eller bare "Chapter <tal>"
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
  const titleMatch = chapterTitle.match(/Chapter\s+(?:\d+|[IVXLCDM]+|[A-Za-z]+)\s*-\s*(.+)/i);
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
  const response = await fetchUrl(bookIndexUrl);

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
  const response = await fetchUrl(chapterUrl);

  const $ = cheerio.load(response.data);

  // Fjern navigation og andre uønskede elementer
  $('script').remove();
  $('style').remove();
  $('noscript').remove();
  $('iframe').remove();
  $('nav').remove();
  $('header').remove();
  $('footer').remove();

  // Fjern footnotes sektion
  // Footnotes er typisk i et element med "Footnotes" overskrift
  $('h2, h3, h4, p, div').each((_, el) => {
    const text = $(el).text().trim().toLowerCase();
    if (text === 'footnotes' || text === 'footnote') {
      // Fjern dette element og alle efterfølgende siblings
      $(el).nextAll().remove();
      $(el).remove();
    }
  });

  // Fjern footnote referencer (patterns som 5:1, 9:1, 20:1 etc.)
  $('a').each((_, el) => {
    const text = $(el).text().trim();
    // Matcher footnote patterns som "5:1", "22:1" etc.
    if (text.match(/^\d+:\d+$/)) {
      $(el).remove();
    }
  });

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

  // Create plain text version for JSON output
  // Strip HTML tags and normalize whitespace
  let plainText = content
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  return {
    title,
    content,
    plainText
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
  const indexResponse = await fetchUrl(bookUrl);
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
  let chapters = [];
  try {
    chapters = await getBookChapters(bookUrl);
  } catch (e) {
    console.log(`  ℹ️ Kunne ikke hente chapters: ${e.message}`);
  }

  if (chapters.length === 0) {
    console.log(`  ℹ️ Ingen 'links' til kapitler fundet. Forsøger at læse siden som single-page bog: ${bookUrl}`);
    try {
      const singlePageRes = await fetchUrl(bookUrl);
      if (singlePageRes.status === 200) {
        const $sp = cheerio.load(singlePageRes.data);
        const bodyHtml = $sp('body').html() || '';

        // Try to split by CHAPTER headers
        const chapterPattern = /(<(?:h[1-6]|b|strong|center)[^>]*>.*?CHAPTER\s+[IVXLCDM\d]+[^<]*<\/(?:h[1-6]|b|strong|center)>)/gi;
        const parts = bodyHtml.split(chapterPattern);

        if (parts.length > 1) {
          // Found chapter headers - create virtual chapters
          console.log(`  📖 Fundet ${Math.floor(parts.length / 2)} kapitler i single-page format`);

          let chapterNum = 0;
          for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            if (part.match(/CHAPTER\s+[IVXLCDM\d]+/i)) {
              // This is a chapter header
              const titleMatch = part.match(/CHAPTER\s+([IVXLCDM\d]+)\.?\s*(.*?)(?:<|$)/i);
              const chapterTitle = titleMatch
                ? `Chapter ${titleMatch[1]}${titleMatch[2] ? ' - ' + titleMatch[2].trim() : ''}`
                : `Chapter ${++chapterNum}`;

              // Next part is the content (if exists)
              const content = parts[i + 1] || '';
              chapters.push({
                title: chapterTitle,
                url: bookUrl,
                content: part + content,
                isSinglePage: true
              });
              i++; // Skip content part, already processed
            }
          }
        }

        // If still no chapters, treat as single chapter
        if (chapters.length === 0) {
          chapters.push({
            title: bookTitle || 'Full Text',
            url: bookUrl,
            isSinglePage: true
          });
        }
      } else {
        throw new Error(`Ingen kapitler fundet for: ${bookUrl}`);
      }
    } catch (err) {
      throw new Error(`Ingen kapitler fundet og kunne ikke læse siden: ${err.message}`);
    }
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

    const firstChapterResponse = await fetchUrl(firstChapterUrl);
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
    const isFirstChapter = (i === 0);
    const formattedTitle = cleanChapterTitle(chapters[i].title, i + 1, isFirstChapter);
    tocHtml += `<li>${escapeHtml(formattedTitle)}</li>`;
  }
  tocHtml += '</ul></div>';
  fullHtml += tocHtml;

  // Collect JSON data for each chapter
  const jsonChapters = [];

  // Hent hvert kapitel
  for (let i = 0; i < chapters.length; i++) {
    const chapter = chapters[i];
    const chapterIndex = i + 1;

    if (progressCallback) {
      progressCallback(chapterIndex, chapters.length, chapter.title);
    }

    // Opret ren kapitel-titel: "Chapter One - Salaam"
    const isFirstChapter = (chapterIndex === 1);
    const formattedTitle = cleanChapterTitle(chapter.title, chapterIndex, isFirstChapter);
    console.log(`  📖 Henter kapitel ${chapterIndex}/${chapters.length}: ${formattedTitle}...`);

    try {
      let { content, plainText } = await fetchChapterContent(chapter.url);

      // Fjern duplikerede kapitel-headers fra indholdet
      content = cleanChapterContent(content, formattedTitle);

      // Clean plainText - remove chapter headers and duplicate titles
      plainText = plainText
        // Remove "Chapter X" patterns at the start
        .replace(/^Chapter\s+[\dIVXLCDM]+[:\.\s\-–]*/im, '')
        // Remove formatted title if it appears at the start
        .replace(new RegExp('^' + formattedTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*', 'im'), '')
        .trim();

      // Also detect and remove content-start headers that match the chapter title
      // Extract just the title part (e.g., "Introduction" from "Chapter 1 - Introduction")
      const titleMatch = formattedTitle.match(/(?:Chapter\s+\w+\s*[-–]\s*)(.+)/i);
      if (titleMatch) {
        const titlePart = titleMatch[1].trim();
        // Remove the title part if it appears at the start of content (case insensitive)
        // Handle variations: "INTRODUCTION", "Introduction", "The Introduction", etc.
        const titlePattern = new RegExp('^\\s*(?:THE\\s+)?' + titlePart.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\n', 'im');
        plainText = plainText.replace(titlePattern, '').trim();
      }

      // Also remove any all-caps header at the very start that's a single word or short phrase
      // This catches things like "INTRODUCTION", "SALAAM", "THE ALL", etc.
      plainText = plainText.replace(/^[A-Z][A-Z\s'']+\s*\n/, '').trim();

      fullHtml += `
  <div class="chapter" data-chapter-index="${chapterIndex}">
    <!-- HONORA_CHAPTER_START: ${chapterIndex} | ${escapeHtml(formattedTitle)} -->
    <h2 class="honora-chapter-title">${escapeHtml(formattedTitle)}</h2>
    ${content}
    <!-- HONORA_CHAPTER_END: ${chapterIndex} -->
  </div>
`;

      // Add to JSON chapters (with normalized whitespace)
      jsonChapters.push({
        index: chapterIndex,
        title: formattedTitle,
        content: normalizeWhitespace(plainText)
      });

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
      // Add placeholder to JSON
      jsonChapters.push({
        index: chapterIndex,
        title: formattedTitle,
        content: "[Failed to fetch chapter content]"
      });
    }
  }

  fullHtml += `
</body>
</html>`;

  // Build JSON data structure
  const jsonData = {
    title: bookTitle,
    author: bookAuthor,
    year: bookYear,
    publisher: bookPublisher,
    chapterCount: jsonChapters.length,
    chapters: jsonChapters,
    scrapedAt: new Date().toISOString(),
    sourceUrl: bookUrl
  };

  return {
    title: bookTitle,
    html: fullHtml,
    jsonData
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
