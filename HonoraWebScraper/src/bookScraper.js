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
const PREFATORY_TITLES = [
  'introduction',
  'preface',
  'foreword',
  'prologue',
  'preliminary remarks',
  "editor's preface",
  "editor's introduction",
  'introductory note',
  'introductory notes',
  'introductory essays',
  'background',
  'context',
  'scope and purpose',
  'preliminary analysis',
  'opening',
  'setting the stage',
  'why this book',
  'before you begin',
  'a note to the reader',
  'note',
  'invocation',
  'opening discourse',
  'on the nature of this work',
  'introduction to the mysteries',
  'preliminary discourse',
  "author's note",
  "translator's note",
  'dedication',
  'acknowledgements',
  'acknowledgments',
  'prefatory note',
  'to the reader',
  'logical structure',
  'the hermetic books',
  'the hermetic system'
];

// Appendix/back matter patterns
const APPENDIX_TITLES = [
  'appendix',
  'glossary',
  'index',
  'bibliography',
  'notes',
  'endnotes',
  'conclusion',
  'epilogue',
  'afterword',
  'postscript',
  'supplementary',
  'addendum',
  'addenda'
];

// Treatise/Section header patterns - these indicate a sub-book within a collection
const TREATISE_PATTERNS = [
  /^the stone of the philosophers$/i,
  /^the virgin of the world$/i,
  /^a treatise on/i,
  /^the definitions of/i,
  /^fragments of/i,
  /^various .* fragments$/i,
  /^the book of/i,
  /^the bosom book/i,
  /^preparations of/i,
  /^the secret of/i,
  /^aurum potabile/i,
  /^the oil of/i,
  /^exit from the old/i,
  /^'?aureus,?'?\s*or\s+the\s+golden/i
];

// "Book" as chapter - patterns for texts that use "Book I" instead of "Chapter I"
const BOOK_AS_CHAPTER_PATTERNS = [
  /^(?:the\s+)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth)\s+book/i,
  /^(?:the\s+)?(?:[IVXLCDM]+|[0-9]+)(?:st|nd|rd|th)?\s+book/i,
  /^book\s+(?:[IVXLCDM]+|[0-9]+|one|two|three|four|five|six|seven|eight|nine|ten)/i,
  /^hermes\s+trismegistus,?\s+his\s+/i  // "Hermes Trismegistus, His First Book"
];

/**
 * Determines the content type of a chapter/section
 * @param {string} title - The title to check
 * @returns {'prefatory'|'chapter'|'book'|'appendix'|'treatise'}
 */
function getContentType(title) {
  if (!title) return 'chapter';
  const normalizedTitle = title.toLowerCase().trim();

  // Check if it's prefatory material
  if (PREFATORY_TITLES.some(p => normalizedTitle === p || normalizedTitle.includes(p))) {
    return 'prefatory';
  }

  // Check if it's appendix/back matter
  if (APPENDIX_TITLES.some(a => normalizedTitle === a || normalizedTitle.startsWith(a))) {
    return 'appendix';
  }

  // Check if it's a treatise/section header
  if (TREATISE_PATTERNS.some(pattern => pattern.test(title))) {
    return 'treatise';
  }

  // Check if it's "Book X" format (used instead of "Chapter X")
  if (BOOK_AS_CHAPTER_PATTERNS.some(pattern => pattern.test(title))) {
    return 'book';
  }

  return 'chapter';
}

/**
 * Checks if a title is an introduction-like chapter (legacy function)
 * @param {string} title - The chapter title to check
 * @returns {boolean}
 */
function isIntroductionChapter(title) {
  return getContentType(title) === 'prefatory';
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
 * Detekterer også "Parts", "Treatises" og content types
 * PRESERVES EXACT ORDER from the index page
 * @param {string} bookIndexUrl - URL til bogens index.htm
 * @returns {Promise<{chapters: Array, parts: Array, treatises: Array}>}
 */
export async function getBookChapters(bookIndexUrl) {
  const response = await fetchUrl(bookIndexUrl);

  const $ = cheerio.load(response.data);
  const chapters = [];
  const parts = [];
  const treatises = [];
  const baseDir = bookIndexUrl.substring(0, bookIndexUrl.lastIndexOf('/'));

  // Pages to SKIP (navigation, TOC, title pages, errata)
  const skipPatterns = [
    /^start\s*reading$/i,
    /^page\s*index$/i,
    /^title\s*page$/i,
    /^table\s*of\s*contents$/i,
    /^the\s*contents$/i,  // "The Contents" - a TOC page
    /^contents$/i,
    /^index$/i,
    /^errata$/i,
    /^«\s*previous/i,     // Navigation links
    /previous:\s*errata/i, // "« Previous: Errata"
    /^next$/i,
    /^previous$/i,
    /^prev$/i,
    /^home$/i,
  ];

  // Part detection patterns
  const partPatterns = [
    /^Part\s+([IVXLCDM]+)\s*[:.\-–]?\s*(.*)$/i,
    /^Part\s+(\d+)\s*[:.\-–]?\s*(.*)$/i,
  ];

  // Track current context and order
  let currentPartIndex = 0;
  let currentPartTitle = null;
  let currentTreatiseIndex = 0;
  let currentTreatiseTitle = null;
  let globalOrder = 0;  // Track order of EVERYTHING

  // Store positions for treatise headers
  const treatisePositions = [];
  const pageHtml = $.html();

  // First: Find ALL section headers (treatises) and their positions
  $('body').find('h2, h3, center, p').each((_, el) => {
    const $el = $(el);
    const text = $el.text().trim();

    // Check if this looks like a section title (NOT a link, NOT a chapter)
    if (text && text.length > 10 && text.length < 100 && !$el.find('a').length) {
      // Check for section header patterns
      const isSectionHeader =
        text === 'The Stone of the Philosophers' ||
        /^[A-Z][a-z]+(\s+[A-Za-z]+){2,}$/.test(text);  // Capitalized multi-word title

      if (isSectionHeader && getContentType(text) === 'treatise') {
        const position = pageHtml.indexOf(text);
        treatisePositions.push({
          title: text,
          position: position
        });
        console.log(`  📖 Found section header: "${text}" at position ${position}`);
      }
    }
  });

  // Process ALL links in order
  $('a').each((_, el) => {
    const $el = $(el);
    const href = $el.attr('href');
    let text = $el.text().trim();

    if (!href) return;

    // Skip external links
    if (href.startsWith('http') && !href.includes('sacred-texts.com')) return;
    if (href === 'index.htm' || href === './index.htm') return;
    if (href.startsWith('#')) return;
    if (href.includes('..')) return;
    if (href.endsWith('.txt') || href.endsWith('.gz')) return;

    // Skip navigation/TOC pages
    const shouldSkip = skipPatterns.some(pattern => pattern.test(text));
    if (shouldSkip) {
      console.log(`  ⏭️ Skipping: "${text}"`);
      return;
    }

    // Skip likely navigation files
    const filename = href.toLowerCase();
    if (filename.match(/00\.htm$/) || filename.match(/01\.htm$/)) {
      if (!text.match(/chapter/i) && !text.match(/^[IVXLC]+\./) && !text.match(/preface/i)) {
        console.log(`  ⏭️ Skipping navigation file: ${href}`);
        return;
      }
    }

    // Valid chapter link
    if (href.match(/^[a-z0-9_-]+\.htm$/i)) {
      const fullUrl = `${baseDir}/${href}`;

      if (!chapters.find(c => c.url === fullUrl)) {
        text = text.replace(/page\s+\d+/gi, '').trim();

        // Find position of this link in the page
        const linkHtml = $.html(el);
        const linkPosition = pageHtml.indexOf(linkHtml);

        // Determine which treatise this link belongs to
        let parentTreatise = null;
        let parentTreatiseIndex = null;

        for (const t of treatisePositions) {
          // Link is AFTER this treatise header
          if (t.position < linkPosition && t.position >= 0) {
            // Check if there's another treatise BETWEEN this one and the link
            const hasCloserTreatise = treatisePositions.some(t2 =>
              t2.position > t.position && t2.position < linkPosition
            );
            if (!hasCloserTreatise) {
              parentTreatise = t.title;
              parentTreatiseIndex = treatisePositions.indexOf(t) + 1;
            }
          }
        }

        // Determine content type - keep original title for chapters
        const contentType = getContentType(text);

        chapters.push({
          title: text,  // Keep ORIGINAL title (with "Chapter I" etc.)
          url: fullUrl,
          content_type: contentType,
          part_index: null,  // Will be set if there are parts
          part: null,
          treatise_index: parentTreatiseIndex,
          treatise: parentTreatise,
          order: globalOrder++
        });
      }
    }
  });

  // Build treatises array from positions
  for (let i = 0; i < treatisePositions.length; i++) {
    treatises.push({
      index: i + 1,
      title: treatisePositions[i].title
    });
  }

  // Sort everything by order
  chapters.sort((a, b) => a.order - b.order);

  const partsInfo = parts.length > 0 ? ` in ${parts.length} parts` : '';
  const treatisesInfo = treatises.length > 0 ? ` with ${treatises.length} sections` : '';
  console.log(`📚 Found ${chapters.length} chapters${partsInfo}${treatisesInfo}`);

  // Log the structure
  console.log('📋 Chapter structure:');
  for (const ch of chapters) {
    const parent = ch.treatise ? `  (in "${ch.treatise}")` : '';
    console.log(`  ${ch.order + 1}. ${ch.title}${parent}`);
  }

  return { chapters, parts, treatises };
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
  let bookParts = [];      // Parts detected from index page
  let bookTreatises = [];  // Treatises/sub-works detected from index page
  try {
    const result = await getBookChapters(bookUrl);
    chapters = result.chapters || [];
    bookParts = result.parts || [];
    bookTreatises = result.treatises || [];
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

  const partsInfo = bookParts.length > 0 ? ` (${bookParts.length} parts)` : '';
  const treatisesInfo = bookTreatises.length > 0 ? ` (${bookTreatises.length} treatises)` : '';
  console.log(`📚 Fandt ${chapters.length} kapitler${partsInfo}${treatisesInfo} i "${bookTitle}"`);

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

    // Determine the formatted title based on content_type
    const contentType = chapter.content_type || 'chapter';
    const isFirstChapter = (chapterIndex === 1);

    let formattedTitle;
    if (contentType === 'prefatory' || contentType === 'treatise' || contentType === 'appendix') {
      // For prefatory material, treatises, and appendices: use original title without "Chapter X -"
      // Just clean up the title without adding chapter prefix
      formattedTitle = chapter.title
        .replace(/^Chapter\s+(\d+|[IVXLCDM]+)[:.\\s-]*/i, '')  // Remove existing "Chapter X:" prefix
        .replace(/page\s+\d+/gi, '')  // Remove page refs
        .trim() || chapter.title;
    } else {
      // For regular chapters: use cleanChapterTitle with "Chapter X -" format
      formattedTitle = cleanChapterTitle(chapter.title, chapterIndex, isFirstChapter);
    }

    console.log(`  📖 Henter ${contentType} ${chapterIndex}/${chapters.length}: ${formattedTitle}...`);

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

      // Add to JSON chapters (with normalized whitespace, part, treatise, and content type info)
      const jsonChapter = {
        index: chapterIndex,
        order: chapter.order,  // Preserve original DOM order
        title: formattedTitle,
        content: normalizeWhitespace(plainText),
        content_type: chapter.content_type || 'chapter'
      };

      // Add part info if chapter belongs to a part
      if (chapter.part_index) {
        jsonChapter.part_index = chapter.part_index;
        jsonChapter.part = chapter.part;
      }

      // Add treatise info if chapter belongs to a treatise (anthology-style books)
      if (chapter.treatise_index) {
        jsonChapter.treatise_index = chapter.treatise_index;
        jsonChapter.treatise = chapter.treatise;
      }

      jsonChapters.push(jsonChapter);

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

  // ============================================
  // BUILD book_nodes TREE STRUCTURE (NEW FORMAT)
  // ============================================

  /**
   * Generates order_key for a node.
   * @param {number} index - 1-based index
   * @param {string} parentKey - Parent's order_key (empty for root)
   * @returns {string} Order key like "0001" or "0001.0002"
   */
  function generateOrderKey(index, parentKey = '') {
    const segment = String(index).padStart(4, '0');
    return parentKey ? `${parentKey}.${segment}` : segment;
  }

  // Build book_nodes array - RESPECTING ORIGINAL ORDER FROM PAGE
  const bookNodes = [];

  // First, sort all chapters by their `order` field (from DOM position)
  const sortedChapters = [...jsonChapters].sort((a, b) => {
    const orderA = a.order ?? a.index;
    const orderB = b.order ?? b.index;
    return orderA - orderB;
  });

  // Track which treatises we've seen and their order_keys
  const treatiseNodeMap = new Map(); // treatise.title -> { orderKey, insertedAt }
  const partNodeMap = new Map();

  // Track children for each parent
  const childCounters = new Map();
  let rootIndex = 0;

  // First pass: identify treatise positions based on the FIRST chapter that references them
  for (const ch of sortedChapters) {
    if (ch.treatise && !treatiseNodeMap.has(ch.treatise)) {
      // This chapter is UNDER a treatise, and we haven't seen this treatise yet
      // The treatise should be inserted RIGHT BEFORE this chapter at root level
      treatiseNodeMap.set(ch.treatise, {
        title: ch.treatise,
        insertedAt: ch.order ?? ch.index,
        orderKey: null  // Will be assigned later
      });
    }
  }

  // Second pass: build nodes in order
  // We need to interleave treatises with chapters based on their position

  // Create a merged list of events (chapters + treatise insertions)
  const events = [];

  for (const ch of sortedChapters) {
    const order = ch.order ?? ch.index;

    // Check if we need to insert a treatise before this chapter
    for (const [title, info] of treatiseNodeMap.entries()) {
      if (info.insertedAt === order && !info.orderKey) {
        // Insert treatise node first
        events.push({
          type: 'treatise',
          title: title,
          order: order - 0.5  // Slightly before the chapter
        });
      }
    }

    // Add the chapter
    events.push({
      type: 'chapter',
      chapter: ch,
      order: order
    });
  }

  // Sort events by order
  events.sort((a, b) => a.order - b.order);

  // Now process events and assign order_keys
  for (const event of events) {
    if (event.type === 'treatise') {
      // Root-level treatise container
      rootIndex++;
      const orderKey = generateOrderKey(rootIndex);

      treatiseNodeMap.get(event.title).orderKey = orderKey;

      bookNodes.push({
        order_key: orderKey,
        node_type: 'treatise',
        display_title: event.title,
        source_title: event.title,
        has_content: false,  // Container
        parent_order_key: null
      });

    } else if (event.type === 'chapter') {
      const ch = event.chapter;
      const contentType = ch.content_type || 'chapter';

      // Determine parent
      // IMPORTANT: If this chapter IS itself a treatise, it should be at ROOT level
      let parentKey = null;
      if (contentType === 'treatise') {
        // Treatise chapters are always at root level, never children
        parentKey = null;
      } else if (ch.treatise && treatiseNodeMap.has(ch.treatise)) {
        parentKey = treatiseNodeMap.get(ch.treatise).orderKey;
      } else if (ch.part && partNodeMap.has(ch.part)) {
        parentKey = partNodeMap.get(ch.part).orderKey;
      }

      // Generate order_key
      let orderKey;
      if (parentKey) {
        const count = (childCounters.get(parentKey) || 0) + 1;
        childCounters.set(parentKey, count);
        orderKey = generateOrderKey(count, parentKey);
      } else {
        rootIndex++;
        orderKey = generateOrderKey(rootIndex);
      }

      // Determine node_type from content_type
      let nodeType = 'chapter';
      switch (contentType) {
        case 'prefatory': nodeType = 'preface'; break;
        case 'appendix': nodeType = 'appendix'; break;
        case 'book': nodeType = 'book'; break;
        case 'treatise': nodeType = 'treatise'; break;
        default: nodeType = 'chapter';
      }

      // Clean the display title (remove "Chapter X -" prefix for non-chapters)
      let displayTitle = ch.title;
      if (nodeType !== 'chapter') {
        displayTitle = ch.title.replace(/^Chapter\s+\d+\s*[-–:]\s*/i, '').trim();
      }

      bookNodes.push({
        order_key: orderKey,
        node_type: nodeType,
        display_title: displayTitle,
        source_title: ch.title,
        has_content: true,
        parent_order_key: parentKey,
        // Keep original chapter data for backwards compatibility
        chapter_index: ch.index,
        content: ch.content
      });
    }
  }

  // Sort nodes by order_key for final output
  bookNodes.sort((a, b) => a.order_key.localeCompare(b.order_key));

  // Build JSON data structure with BOTH old and new formats
  const jsonData = {
    title: bookTitle,
    author: bookAuthor,
    year: bookYear,
    publisher: bookPublisher,

    // NEW: book_nodes tree structure
    book_nodes: bookNodes,

    // LEGACY: Keep old format for backwards compatibility
    partCount: bookParts.length,
    parts: bookParts,
    treatiseCount: bookTreatises.length,
    treatises: bookTreatises,
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
