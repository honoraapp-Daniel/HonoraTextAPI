// Honora Web Scraper - Frontend Logic

let currentCategory = null;
let eventSource = null;

// DOM Elements
const categoryGrid = document.getElementById('category-grid');
const booksGrid = document.getElementById('books-grid');
const booksSection = document.getElementById('books-section');
const categoryTitle = document.getElementById('category-title');
const downloadAllBtn = document.getElementById('download-all-btn');
const logContainer = document.getElementById('log-container');
const catLoader = document.getElementById('cat-loader');

const activeDownload = document.getElementById('active-download');
const idleStatus = document.getElementById('idle-status');
const progressText = document.getElementById('progress-text');
const progressFill = document.getElementById('progress-fill');
const progressPercent = document.getElementById('progress-percent');
const progressCount = document.getElementById('progress-count');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadCategories();
    setupSSE();
    loadHistory();
});

// Setup Server-Sent Events
function setupSSE() {
    eventSource = new EventSource('/api/events');

    eventSource.addEventListener('log', (e) => {
        const data = JSON.parse(e.data);
        addLog(data.message, data.type, data.timestamp);
    });

    eventSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        showProgress(data);
    });

    eventSource.addEventListener('complete', (e) => {
        const data = JSON.parse(e.data);
        addLog(`Download færdig: ${data.title}`, 'success');
        hideProgress();
        // Refresh books to show downloaded status
        if (currentCategory) selectCategory(currentCategory);
    });

    eventSource.addEventListener('complete-all', (e) => {
        const data = JSON.parse(e.data);
        addLog(`Kategori download færdig: ${data.category}`, 'success');
        hideProgress();
        // Refresh books to show downloaded status
        if (currentCategory) selectCategory(currentCategory);
    });

    eventSource.onerror = () => {
        console.error('SSE Error - attempting to reconnect');
    };
}

// API Calls
async function loadCategories() {
    catLoader.style.display = 'block';
    try {
        const res = await fetch('/api/categories');
        const categories = await res.json();

        categoryGrid.innerHTML = '';
        categories.forEach(cat => {
            const card = document.createElement('div');
            card.className = 'item-card';
            card.textContent = cat.name;
            card.onclick = () => selectCategory(cat);
            categoryGrid.appendChild(card);
        });
    } catch (err) {
        addLog('Kunne ikke hente kategorier: ' + err.message, 'error');
    } finally {
        catLoader.style.display = 'none';
    }
}

async function selectCategory(cat) {
    currentCategory = cat;

    // Highlight active card
    document.querySelectorAll('#category-grid .item-card').forEach(card => {
        card.classList.toggle('active', card.textContent === cat.name);
    });

    categoryTitle.textContent = `Bøger i ${cat.name}`;
    booksSection.style.display = 'block';
    booksGrid.innerHTML = '<div class="loader"></div>';

    try {
        const res = await fetch(`/api/books?url=${encodeURIComponent(cat.url)}&categoryName=${encodeURIComponent(cat.name)}`);
        const books = await res.json();

        booksGrid.innerHTML = '';
        books.forEach(book => {
            const card = document.createElement('div');
            card.className = 'item-card' + (book.downloaded ? ' downloaded' : '');
            card.innerHTML = `
                <div style="font-size: 0.9rem; margin-bottom: 0.5rem">${book.title}</div>
                <button class="btn btn-primary btn-sm">${book.downloaded ? 'Hent igen' : 'Download PDF'}</button>
            `;
            card.querySelector('button').onclick = (e) => {
                e.stopPropagation();
                downloadBook(book);
            };
            booksGrid.appendChild(card);
        });

        downloadAllBtn.onclick = () => downloadCategory(cat);
    } catch (err) {
        addLog('Kunne ikke hente bøger: ' + err.message, 'error');
    }
}

async function loadHistory() {
    try {
        const res = await fetch('/api/history');
        const history = await res.json();

        logContainer.innerHTML = '';
        if (history.length === 0) {
            addLog('Ingen tidligere historik fundet.');
        } else {
            history.forEach(log => {
                addLog(log.message, log.type, log.timestamp);
            });
        }
    } catch (err) {
        console.error('Kunne ikke hente historik:', err);
    }
}

async function downloadBook(book) {
    try {
        const res = await fetch('/api/download/book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: book.url,
                categoryName: currentCategory ? currentCategory.name : 'Uncategorized',
                title: book.title
            })
        });
        const data = await res.json();
        addLog(data.message);
    } catch (err) {
        addLog('Download fejl: ' + err.message, 'error');
    }
}

async function downloadCategory(cat) {
    if (!confirm(`Vil du downloade alle bøger i ${cat.name}? Dette kan tage tid.`)) return;

    try {
        const res = await fetch('/api/download/category', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: cat.url, name: cat.name })
        });
        const data = await res.json();
        addLog(data.message);
    } catch (err) {
        addLog('Kategori download fejl: ' + err.message, 'error');
    }
}

// UI Helpers
function addLog(message, type = 'info', timestamp = new Date().toISOString()) {
    const entry = document.createElement('div');
    entry.className = `log-entry log-${type}`;
    const timeStr = new Date(timestamp).toLocaleTimeString();
    entry.innerHTML = `<span class="log-time">[${timeStr}]</span> ${message}`;
    logContainer.appendChild(entry);
    logContainer.scrollTop = logContainer.scrollHeight;
}

function showProgress(data) {
    activeDownload.style.display = 'block';
    idleStatus.style.display = 'none';

    progressText.textContent = data.title;
    progressFill.style.width = `${data.percent}%`;
    progressPercent.textContent = `${data.percent}%`;
    progressCount.textContent = `${data.current}/${data.total}`;
}

function hideProgress() {
    setTimeout(() => {
        activeDownload.style.display = 'none';
        idleStatus.style.display = 'block';
        progressFill.style.width = '0%';
    }, 3000);
}
