import puppeteer from 'puppeteer';

async function test() {
    console.log('Starting Puppeteer test using System Chrome...');
    const browser = await puppeteer.launch({
        headless: 'new',
        executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
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
        await page.setContent('<h1>Hello World</h1><p>This is a test PDF using system Chrome.</p>');
        await page.pdf({ path: 'test.pdf', format: 'A4' });
        console.log('Success! test.pdf created.');
    } catch (err) {
        console.error('Failure:', err);
    } finally {
        await browser.close();
    }
}

test();
