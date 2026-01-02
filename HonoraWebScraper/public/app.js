// Honora Web Scraper - Frontend Logic

let currentCategory = null;
let currentBooks = []; // Store books for filtering
let eventSource = null;

// DOM Elements
const categoryGrid = document.getElementById('category-grid');
const booksGrid = document.getElementById('books-grid');
const booksSection = document.getElementById('books-section');
const categoryTitle = document.getElementById('category-title');
const downloadAllBtn = document.getElementById('download-all-btn');
const downloadNewBtn = document.getElementById('download-new-btn');
const searchInput = document.getElementById('search-input');
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

    // Search Listener
    searchInput.addEventListener('input', (e) => {
        filterBooks(e.target.value);
    });
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
        // Find card and show spinner (use bookTitle if available, fallback to title)
        updateCardProgress(data.bookTitle || data.title, true);
    });

    eventSource.addEventListener('complete', (e) => {
        const data = JSON.parse(e.data);
        addLog(`Download færdig: ${data.title}`, 'success');
        hideProgress();
        updateCardProgress(data.title, false);
        markAsDownloaded(data.title);
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

        if (!categories || !Array.isArray(categories)) {
            console.error('Categories response:', categories);
            addLog('Fejl: Kunne ikke hente kategorier (server fejl)', 'error');
            return;
        }

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
    searchInput.value = ''; // Reset search

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

        // Validate response is array
        if (!books || !Array.isArray(books)) {
            console.error('Books response:', books);
            addLog('Fejl: Kunne ikke hente bøger (server fejl)', 'error');
            booksGrid.innerHTML = '<p style="color:#ff6b6b;">Fejl ved hentning af bøger</p>';
            return;
        }

        currentBooks = books;
        renderBooks(currentBooks);

        downloadAllBtn.onclick = () => downloadCategory(cat, false);
        downloadNewBtn.onclick = () => downloadCategory(cat, true);
    } catch (err) {
        addLog('Kunne ikke hente bøger: ' + err.message, 'error');
        booksGrid.innerHTML = '<p style="color:#ff6b6b;">Netværksfejl</p>';
    }

    function renderBooks(books) {
        booksGrid.innerHTML = '';
        if (!books || books.length === 0) {
            booksGrid.innerHTML = '<p style="color:var(--text-muted);">Ingen bøger fundet.</p>';
            return;
        }

        books.forEach(book => {
            const card = document.createElement('div');
            card.className = 'item-card' + (book.downloaded ? ' downloaded' : '');
            card.dataset.title = book.title;

            const downloadLabel = book.downloaded ? 'Hent igen' : 'Download PDF';

            card.innerHTML = `
            <div style="font-size: 0.9rem; margin-bottom: 0.5rem; font-weight:600;">${book.title}</div>
            <div class="card-status" style="display:none; margin: 10px 0;">
                <div class="loader" style="width:16px; height:16px; border-width:2px; margin:0 auto;"></div>
                <span style="font-size:0.7rem; color:var(--text-muted);">Downloader...</span>
            </div>
            <button class="btn btn-primary btn-sm" style="margin-top:10px;">${downloadLabel}</button>
        `;
            card.querySelector('button').onclick = (e) => {
                e.stopPropagation();
                downloadBook(book);
            };
            booksGrid.appendChild(card);
        });
    }

    function filterBooks(query) {
        const lowerQ = query.toLowerCase();
        const filtered = currentBooks.filter(b => b.title.toLowerCase().includes(lowerQ));
        renderBooks(filtered);
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
        // Optimistic UI update
        updateCardProgress(book.title, true);

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
            updateCardProgress(book.title, false);
        }
    }

    async function downloadCategory(cat, newOnly = false) {
        const text = newOnly ? 'nye bøger' : 'alle bøger';
        if (!confirm(`Vil du downloade ${text} i ${cat.name}? Dette kan tage tid.`)) return;

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

    function updateCardProgress(title, isLoading) {
        const cards = document.querySelectorAll('.item-card');
        cards.forEach(card => {
            if (card.dataset.title === title) {
                const status = card.querySelector('.card-status');
                const btn = card.querySelector('button');
                if (status) status.style.display = isLoading ? 'block' : 'none';
                if (btn) btn.style.display = isLoading ? 'none' : 'inline-block';
            }
        });
    }

    function markAsDownloaded(title) {
        const cards = document.querySelectorAll('.item-card');
        cards.forEach(card => {
            if (card.dataset.title === title) {
                card.classList.add('downloaded');
                const btn = card.querySelector('button');
                if (btn) btn.textContent = 'Hent igen';
            }
        });
    }
