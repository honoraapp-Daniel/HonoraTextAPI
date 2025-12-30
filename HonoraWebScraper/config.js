// Configuration for Sacred Texts Web Scraper

export const config = {
    // Base URL for sacred-texts.com
    baseUrl: 'https://sacred-texts.com',

    // Output directory for PDFs
    outputDir: './output',

    // Rate limiting - delay between requests (ms)
    // Respects the server by not hammering it with requests
    requestDelay: 800,

    // Retry configuration
    maxRetries: 3,
    retryDelay: 2000,

    // PDF settings
    pdf: {
        format: 'A4',
        margin: {
            top: '20mm',
            right: '15mm',
            bottom: '20mm',
            left: '15mm'
        },
        printBackground: true
    },

    // User agent to identify ourselves politely
    userAgent: 'HonoraWebScraper/1.0 (Educational book archiving tool)'
};
