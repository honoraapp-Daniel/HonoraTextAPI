/**
 * Honora Mapping Editor - Frontend Logic
 * Handles tree view, drag-drop, node editing, and mapping persistence
 */

// State - exposed on window for debugging and cross-function access
window.currentBookData = null;     // Original book JSON data
window.currentNodes = [];          // Working copy of book_nodes
window.selectedNodeKey = null;     // Currently selected node's order_key
window.hasChanges = false;         // Track unsaved changes
window.currentFilePath = null;     // Path to current JSON file

// DOM Elements
const fileSelector = document.getElementById('file-selector');
const editorPanel = document.getElementById('editor-panel');
const recentFiles = document.getElementById('recent-files');
const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');

const bookTitle = document.getElementById('book-title');
const bookAuthor = document.getElementById('book-author');
const bookYear = document.getElementById('book-year');
const nodeCount = document.getElementById('node-count');
const treeView = document.getElementById('tree-view');

const noSelection = document.getElementById('no-selection');
const nodeDetails = document.getElementById('node-details');
const statusIndicator = document.getElementById('status-indicator');

// Detail inputs
const detailOrderKey = document.getElementById('detail-order-key');
const detailTitle = document.getElementById('detail-title');
const detailSourceTitle = document.getElementById('detail-source-title');
const detailNodeType = document.getElementById('detail-node-type');
const chapterNumberGroup = document.getElementById('chapter-number-group');
const detailChapterNumber = document.getElementById('detail-chapter-number');
const detailExcludeFrontend = document.getElementById('detail-exclude-frontend');
const detailExcludeAudio = document.getElementById('detail-exclude-audio');
const detailHasContent = document.getElementById('detail-has-content');

// Node type icons
const NODE_ICONS = {
    chapter: '📄',
    preface: '📝',
    introduction: '📝',
    foreword: '📝',
    prologue: '📝',
    epilogue: '📝',
    appendix: '📎',
    glossary: '📖',
    bibliography: '📚',
    index: '🔍',
    notes: '📋',
    treatise: '📜',
    book: '📕',
    part: '📂',
    volume: '📗',
    section: '§',
    default: '📄'
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadRecentFiles();
    setupEventListeners();
    setupDragAndDrop();

    // Check URL params for direct file open
    const params = new URLSearchParams(window.location.search);
    const filePath = params.get('file');
    if (filePath) {
        loadBookFromPath(filePath);
    }
});

// ============================================
// File Loading
// ============================================

async function loadRecentFiles() {
    try {
        const res = await fetch('/api/mapping/files');
        const files = await res.json();

        if (!files || files.length === 0) {
            recentFiles.innerHTML = '<p style="color: var(--text-muted);">Ingen bøger fundet. Download en bog først.</p>';
            return;
        }

        recentFiles.innerHTML = '';
        files.forEach(file => {
            const item = document.createElement('div');
            item.className = 'file-item' + (file.hasMapping ? ' has-mapping' : '');
            item.innerHTML = `
                <span class="file-icon">📚</span>
                <span class="file-name">${file.title || file.name}</span>
                ${file.hasMapping ? '<span class="mapping-badge">Mapping</span>' : ''}
                <span class="file-meta">${file.category}</span>
            `;
            item.onclick = () => loadBookFromPath(file.path);
            recentFiles.appendChild(item);
        });
    } catch (err) {
        console.error('Error loading recent files:', err);
        recentFiles.innerHTML = '<p style="color: var(--text-muted);">Kunne ikke hente filer.</p>';
    }
}

async function loadBookFromPath(filePath) {
    try {
        showToast('Indlæser bog...', 'info');

        const res = await fetch('/api/mapping/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filePath })
        });

        if (!res.ok) throw new Error('Kunne ikke indlæse fil');

        const data = await res.json();
        openEditor(data, filePath);

    } catch (err) {
        console.error('Error loading book:', err);
        showToast('Fejl ved indlæsning: ' + err.message, 'error');
    }
}

function loadBookFromFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const data = JSON.parse(e.target.result);
            openEditor(data, null);
        } catch (err) {
            showToast('Ugyldig JSON fil', 'error');
        }
    };
    reader.readAsText(file);
}

function openEditor(data, filePath) {
    currentBookData = data;
    currentFilePath = filePath;

    // Use existing mapping if available, otherwise use book_nodes
    if (data.mapping && data.mapping.nodes) {
        currentNodes = JSON.parse(JSON.stringify(data.mapping.nodes));
    } else if (data.book_nodes) {
        currentNodes = JSON.parse(JSON.stringify(data.book_nodes));
    } else {
        // Legacy: convert chapters to nodes
        currentNodes = convertLegacyToNodes(data);
    }

    // Update UI
    bookTitle.textContent = data.title || 'Ukendt Bog';
    bookAuthor.textContent = data.author || 'Ukendt Forfatter';
    bookYear.textContent = data.year || '-';
    nodeCount.textContent = `${currentNodes.length} noder`;

    // Show editor
    fileSelector.classList.add('hidden');
    editorPanel.classList.remove('hidden');

    // Render tree
    renderTree();

    // Clear selection
    selectNode(null);

    hasChanges = false;
    updateStatus();

    showToast('Bog indlæst!', 'success');
}

function convertLegacyToNodes(data) {
    // Convert old chapters format to book_nodes
    const nodes = [];
    if (data.chapters) {
        data.chapters.forEach((ch, i) => {
            nodes.push({
                order_key: String(i + 1).padStart(4, '0'),
                node_type: ch.content_type || 'chapter',
                display_title: ch.title,
                source_title: ch.title,
                has_content: true,
                parent_order_key: null,
                chapter_index: ch.index,
                content: ch.content
            });
        });
    }
    return nodes;
}

// ============================================
// Tree Rendering
// ============================================

function renderTree() {
    // Build tree structure from flat list
    const tree = buildTree(currentNodes);

    treeView.innerHTML = '';
    tree.forEach(node => {
        treeView.appendChild(renderTreeNode(node));
    });
}

function buildTree(nodes) {
    // Sort by order_key
    const sorted = [...nodes].sort((a, b) =>
        a.order_key.localeCompare(b.order_key)
    );

    // Build parent-child relationships
    const nodeMap = new Map();
    sorted.forEach(n => nodeMap.set(n.order_key, { ...n, children: [] }));

    const roots = [];
    sorted.forEach(n => {
        const node = nodeMap.get(n.order_key);
        if (n.parent_order_key && nodeMap.has(n.parent_order_key)) {
            nodeMap.get(n.parent_order_key).children.push(node);
        } else {
            roots.push(node);
        }
    });

    return roots;
}

function renderTreeNode(node, depth = 0) {
    const hasChildren = node.children && node.children.length > 0;
    const isExcluded = node.exclude_from_frontend || node.exclude_from_audio;
    const isSelected = node.order_key === selectedNodeKey;

    const container = document.createElement('div');
    container.className = 'tree-node';
    container.dataset.orderKey = node.order_key;

    const row = document.createElement('div');
    row.className = 'tree-node-row' +
        (isExcluded ? ' excluded' : '') +
        (isSelected ? ' selected' : '');
    row.draggable = true;

    // Toggle arrow
    const toggle = document.createElement('span');
    toggle.className = 'tree-toggle' +
        (hasChildren ? ' expanded' : ' no-children');
    toggle.textContent = '▶';
    toggle.onclick = (e) => {
        e.stopPropagation();
        toggleNode(container);
    };
    row.appendChild(toggle);

    // Icon
    const icon = document.createElement('span');
    icon.className = 'tree-icon';
    icon.textContent = NODE_ICONS[node.node_type] || NODE_ICONS.default;
    row.appendChild(icon);

    // Order key
    const orderKey = document.createElement('span');
    orderKey.className = 'tree-order-key';
    orderKey.textContent = node.order_key;
    row.appendChild(orderKey);

    // Title
    const title = document.createElement('span');
    title.className = 'tree-title';
    title.textContent = node.display_title;
    row.appendChild(title);

    // Type badge
    const typeBadge = document.createElement('span');
    typeBadge.className = 'tree-type-badge ' + node.node_type;
    typeBadge.textContent = node.node_type;
    row.appendChild(typeBadge);

    // Exclude badge
    if (isExcluded) {
        const excludeBadge = document.createElement('span');
        excludeBadge.className = 'tree-exclude-badge';
        excludeBadge.textContent = node.exclude_from_frontend && node.exclude_from_audio ? 'Skjult' :
            node.exclude_from_frontend ? '👁' : '🔇';
        row.appendChild(excludeBadge);
    }

    row.onclick = () => selectNode(node.order_key);

    // Drag events
    row.ondragstart = (e) => handleDragStart(e, node);
    row.ondragover = (e) => handleDragOver(e, node);
    row.ondragleave = (e) => handleDragLeave(e);
    row.ondrop = (e) => handleDrop(e, node);
    row.ondragend = (e) => handleDragEnd(e);

    container.appendChild(row);

    // Children
    if (hasChildren) {
        const childContainer = document.createElement('div');
        childContainer.className = 'tree-node-children';
        node.children.forEach(child => {
            childContainer.appendChild(renderTreeNode(child, depth + 1));
        });
        container.appendChild(childContainer);
    }

    return container;
}

function toggleNode(container) {
    const toggle = container.querySelector('.tree-toggle');
    const children = container.querySelector('.tree-node-children');

    if (children) {
        children.classList.toggle('collapsed');
        toggle.classList.toggle('expanded');
    }
}

// ============================================
// Node Selection & Details
// ============================================

function selectNode(orderKey) {
    selectedNodeKey = orderKey;

    // Update visual selection
    document.querySelectorAll('.tree-node-row').forEach(row => {
        const container = row.parentElement;
        row.classList.toggle('selected', container.dataset.orderKey === orderKey);
    });

    if (!orderKey) {
        noSelection.classList.remove('hidden');
        nodeDetails.classList.add('hidden');
        return;
    }

    const node = currentNodes.find(n => n.order_key === orderKey);
    if (!node) return;

    noSelection.classList.add('hidden');
    nodeDetails.classList.remove('hidden');

    // Populate details
    detailOrderKey.value = node.order_key;
    detailTitle.value = node.display_title;
    detailSourceTitle.value = node.source_title || '';
    detailNodeType.value = node.node_type;
    detailExcludeFrontend.checked = !!node.exclude_from_frontend;
    detailExcludeAudio.checked = !!node.exclude_from_audio;
    detailHasContent.checked = node.has_content !== false;

    // Show chapter number if applicable
    if (node.node_type === 'chapter') {
        chapterNumberGroup.classList.remove('hidden');
        // Extract chapter number from title
        const match = node.display_title.match(/Chapter\s+(\d+)/i);
        detailChapterNumber.value = match ? match[1] : '';
    } else {
        chapterNumberGroup.classList.add('hidden');
    }
}

function updateSelectedNode() {
    if (!selectedNodeKey) return;

    const nodeIndex = currentNodes.findIndex(n => n.order_key === selectedNodeKey);
    if (nodeIndex === -1) return;

    const node = currentNodes[nodeIndex];
    const oldType = node.node_type;
    const newType = detailNodeType.value;

    // Update node
    node.display_title = detailTitle.value;
    node.node_type = newType;
    node.exclude_from_frontend = detailExcludeFrontend.checked;
    node.exclude_from_audio = detailExcludeAudio.checked;
    node.has_content = detailHasContent.checked;

    // Handle chapter number change
    if (newType === 'chapter') {
        chapterNumberGroup.classList.remove('hidden');
        const chapterNum = detailChapterNumber.value || getNextChapterNumber();

        // Update title if type changed to chapter
        if (oldType !== 'chapter' || !node.display_title.match(/^Chapter\s+\d+/i)) {
            const titlePart = node.display_title.replace(/^Chapter\s+\d+\s*[-–:]\s*/i, '').trim();
            node.display_title = `Chapter ${chapterNum}${titlePart ? ' - ' + titlePart : ''}`;
            detailTitle.value = node.display_title;
        }
    } else {
        chapterNumberGroup.classList.add('hidden');
    }

    markChanged();
    renderTree();

    // Re-select to update UI
    setTimeout(() => {
        document.querySelector(`.tree-node[data-order-key="${selectedNodeKey}"] .tree-node-row`)?.classList.add('selected');
    }, 10);
}

function getNextChapterNumber() {
    let maxNum = 0;
    currentNodes.forEach(n => {
        if (n.node_type === 'chapter') {
            const match = n.display_title.match(/Chapter\s+(\d+)/i);
            if (match) {
                maxNum = Math.max(maxNum, parseInt(match[1]));
            }
        }
    });
    return maxNum + 1;
}

// ============================================
// Node Operations
// ============================================

function moveNodeUp() {
    if (!selectedNodeKey) return;
    moveNode(selectedNodeKey, -1);
}

function moveNodeDown() {
    if (!selectedNodeKey) return;
    moveNode(selectedNodeKey, 1);
}

function moveNode(orderKey, direction) {
    const node = currentNodes.find(n => n.order_key === orderKey);
    if (!node) return;

    // Get siblings (same parent)
    const siblings = currentNodes.filter(n => n.parent_order_key === node.parent_order_key)
        .sort((a, b) => a.order_key.localeCompare(b.order_key));

    const currentIndex = siblings.findIndex(n => n.order_key === orderKey);
    const newIndex = currentIndex + direction;

    if (newIndex < 0 || newIndex >= siblings.length) return;

    // Swap order_keys
    const otherNode = siblings[newIndex];
    const tempKey = node.order_key;
    node.order_key = otherNode.order_key;
    otherNode.order_key = tempKey;

    // Update children's parent references
    updateChildrenParentKeys(tempKey, node.order_key);
    updateChildrenParentKeys(otherNode.order_key, tempKey);

    markChanged();
    renderTree();
    selectNode(node.order_key);
}

function updateChildrenParentKeys(oldParentKey, newParentKey) {
    currentNodes.forEach(n => {
        if (n.parent_order_key === oldParentKey) {
            n.parent_order_key = newParentKey;
        }
    });
}

function indentNode() {
    if (!selectedNodeKey) return;

    const node = currentNodes.find(n => n.order_key === selectedNodeKey);
    if (!node) return;

    // Get siblings (same parent)
    const siblings = currentNodes.filter(n => n.parent_order_key === node.parent_order_key)
        .sort((a, b) => a.order_key.localeCompare(b.order_key));

    const currentIndex = siblings.findIndex(n => n.order_key === selectedNodeKey);

    // Need a previous sibling to become new parent
    if (currentIndex <= 0) {
        showToast('Kan ikke indrykke - ingen forrige søskende', 'warning');
        return;
    }

    const newParent = siblings[currentIndex - 1];

    // Update node's parent
    node.parent_order_key = newParent.order_key;

    // Regenerate order keys
    regenerateOrderKeys();

    markChanged();
    renderTree();

    // Find new order key and select
    const updatedNode = currentNodes.find(n => n.source_title === node.source_title);
    if (updatedNode) selectNode(updatedNode.order_key);
}

function outdentNode() {
    if (!selectedNodeKey) return;

    const node = currentNodes.find(n => n.order_key === selectedNodeKey);
    if (!node || !node.parent_order_key) {
        showToast('Kan ikke udrykke - allerede på rod-niveau', 'warning');
        return;
    }

    const parent = currentNodes.find(n => n.order_key === node.parent_order_key);
    if (!parent) return;

    // Move node to parent's level
    node.parent_order_key = parent.parent_order_key;

    // Regenerate order keys
    regenerateOrderKeys();

    markChanged();
    renderTree();

    // Find new order key and select
    const updatedNode = currentNodes.find(n => n.source_title === node.source_title);
    if (updatedNode) selectNode(updatedNode.order_key);
}

function deleteNode() {
    if (!selectedNodeKey) return;

    if (!confirm('Er du sikker på at du vil fjerne denne node og alle dens børn?')) return;

    // Remove node and all children
    const toRemove = new Set([selectedNodeKey]);

    // Find all descendants
    let foundMore = true;
    while (foundMore) {
        foundMore = false;
        currentNodes.forEach(n => {
            if (n.parent_order_key && toRemove.has(n.parent_order_key) && !toRemove.has(n.order_key)) {
                toRemove.add(n.order_key);
                foundMore = true;
            }
        });
    }

    // Remove
    currentNodes = currentNodes.filter(n => !toRemove.has(n.order_key));

    // Regenerate order keys
    regenerateOrderKeys();

    markChanged();
    renderTree();
    selectNode(null);

    showToast('Node fjernet', 'success');
}

function regenerateOrderKeys() {
    // Build tree, then reassign order keys
    const tree = buildTree(currentNodes);

    function assignKeys(nodes, parentKey = '') {
        nodes.forEach((node, index) => {
            const newKey = parentKey
                ? `${parentKey}.${String(index + 1).padStart(4, '0')}`
                : String(index + 1).padStart(4, '0');

            // Find in currentNodes and update
            const original = currentNodes.find(n =>
                n.order_key === node.order_key ||
                (n.source_title === node.source_title && n.display_title === node.display_title)
            );

            if (original) {
                original.order_key = newKey;
                original.parent_order_key = parentKey || null;
            }

            if (node.children && node.children.length > 0) {
                assignKeys(node.children, newKey);
            }
        });
    }

    assignKeys(tree);
}

// ============================================
// Drag and Drop
// ============================================

let draggedNode = null;

function handleDragStart(e, node) {
    draggedNode = node;
    e.target.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', node.order_key);
}

function handleDragOver(e, targetNode) {
    e.preventDefault();
    if (!draggedNode || draggedNode.order_key === targetNode.order_key) return;

    e.target.closest('.tree-node-row').classList.add('drag-over');
    e.dataTransfer.dropEffect = 'move';
}

function handleDragLeave(e) {
    e.target.closest('.tree-node-row')?.classList.remove('drag-over');
}

function handleDrop(e, targetNode) {
    e.preventDefault();
    e.target.closest('.tree-node-row')?.classList.remove('drag-over');

    if (!draggedNode || draggedNode.order_key === targetNode.order_key) return;

    // Move dragged node to be a sibling after target (or child if shift held)
    const srcNode = currentNodes.find(n => n.order_key === draggedNode.order_key);
    if (!srcNode) return;

    if (e.shiftKey) {
        // Make it a child of target
        srcNode.parent_order_key = targetNode.order_key;
    } else {
        // Make it a sibling after target
        srcNode.parent_order_key = targetNode.parent_order_key;
    }

    regenerateOrderKeys();
    markChanged();
    renderTree();

    // Re-select the moved node
    const updatedNode = currentNodes.find(n => n.source_title === srcNode.source_title);
    if (updatedNode) selectNode(updatedNode.order_key);
}

function handleDragEnd(e) {
    e.target.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    draggedNode = null;
}

// ============================================
// Saving & Loading
// ============================================

async function saveMapping() {
    if (!currentFilePath) {
        showToast('Ingen filsti - kan kun gemme for server-bøger', 'error');
        return;
    }

    try {
        const mapping = {
            version: 1,
            createdAt: new Date().toISOString(),
            nodes: currentNodes
        };

        const res = await fetch('/api/mapping/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filePath: currentFilePath,
                mapping
            })
        });

        if (!res.ok) throw new Error('Kunne ikke gemme');

        hasChanges = false;
        updateStatus('saved');
        showToast('Mapping gemt!', 'success');

    } catch (err) {
        console.error('Save error:', err);
        showToast('Fejl ved gemning: ' + err.message, 'error');
    }
}

function resetMapping() {
    if (!confirm('Nulstil til original automatisk mapping? Alle manuelle ændringer slettes.')) return;

    if (currentBookData.book_nodes) {
        currentNodes = JSON.parse(JSON.stringify(currentBookData.book_nodes));
    } else {
        currentNodes = convertLegacyToNodes(currentBookData);
    }

    markChanged();
    renderTree();
    selectNode(null);
    showToast('Nulstillet til original', 'success');
}

function closeBook() {
    if (hasChanges && !confirm('Du har ugemte ændringer. Luk alligevel?')) return;

    currentBookData = null;
    currentNodes = [];
    currentFilePath = null;
    selectedNodeKey = null;
    hasChanges = false;

    editorPanel.classList.add('hidden');
    fileSelector.classList.remove('hidden');

    updateStatus();
    loadRecentFiles();
}

// ============================================
// Preview
// ============================================

function showPreview() {
    const previewModal = document.getElementById('preview-modal');
    const previewJson = document.getElementById('preview-json');

    const output = {
        title: currentBookData.title,
        author: currentBookData.author,
        year: currentBookData.year,
        book_nodes: currentNodes
    };

    previewJson.textContent = JSON.stringify(output, null, 2);
    previewModal.classList.remove('hidden');
}

function closePreview() {
    document.getElementById('preview-modal').classList.add('hidden');
}

// ============================================
// UI Helpers
// ============================================

function markChanged() {
    hasChanges = true;
    updateStatus();
    nodeCount.textContent = `${currentNodes.length} noder`;
}

function updateStatus(type = null) {
    if (type === 'saved') {
        statusIndicator.textContent = 'Gemt!';
        statusIndicator.className = 'status-badge saved';
        setTimeout(() => updateStatus(), 2000);
    } else if (hasChanges) {
        statusIndicator.textContent = 'Ikke gemt';
        statusIndicator.className = 'status-badge has-changes';
    } else {
        statusIndicator.textContent = 'Ingen ændringer';
        statusIndicator.className = 'status-badge';
    }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => toast.remove(), 3000);
}

function expandAll() {
    document.querySelectorAll('.tree-node-children').forEach(el => {
        el.classList.remove('collapsed');
    });
    document.querySelectorAll('.tree-toggle').forEach(el => {
        if (!el.classList.contains('no-children')) {
            el.classList.add('expanded');
        }
    });
}

function collapseAll() {
    document.querySelectorAll('.tree-node-children').forEach(el => {
        el.classList.add('collapsed');
    });
    document.querySelectorAll('.tree-toggle').forEach(el => {
        el.classList.remove('expanded');
    });
}

function searchNodes(query) {
    const lowerQuery = query.toLowerCase();

    document.querySelectorAll('.tree-node').forEach(node => {
        const title = node.querySelector('.tree-title')?.textContent.toLowerCase() || '';
        const orderKey = node.dataset.orderKey.toLowerCase();

        if (!query || title.includes(lowerQuery) || orderKey.includes(lowerQuery)) {
            node.style.display = '';
        } else {
            node.style.display = 'none';
        }
    });
}

// ============================================
// Event Listeners
// ============================================

function setupEventListeners() {
    // File upload
    uploadArea.onclick = () => fileInput.click();
    fileInput.onchange = (e) => {
        if (e.target.files.length > 0) {
            loadBookFromFile(e.target.files[0]);
        }
    };

    // Drag & drop upload
    uploadArea.ondragover = (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    };
    uploadArea.ondragleave = () => uploadArea.classList.remove('dragover');
    uploadArea.ondrop = (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            loadBookFromFile(e.dataTransfer.files[0]);
        }
    };

    // Detail changes
    detailTitle.oninput = updateSelectedNode;
    detailNodeType.onchange = updateSelectedNode;
    detailChapterNumber.onchange = () => {
        // Update chapter number in title
        const node = currentNodes.find(n => n.order_key === selectedNodeKey);
        if (node && node.node_type === 'chapter') {
            const num = detailChapterNumber.value || '0';
            const titlePart = node.display_title.replace(/^Chapter\s+\d+\s*[-–:]\s*/i, '').trim();
            node.display_title = `Chapter ${num}${titlePart ? ' - ' + titlePart : ''}`;
            detailTitle.value = node.display_title;
            markChanged();
            renderTree();
        }
    };
    detailExcludeFrontend.onchange = updateSelectedNode;
    detailExcludeAudio.onchange = updateSelectedNode;
    detailHasContent.onchange = updateSelectedNode;

    // Actions
    document.getElementById('btn-move-up').onclick = moveNodeUp;
    document.getElementById('btn-move-down').onclick = moveNodeDown;
    document.getElementById('btn-indent').onclick = indentNode;
    document.getElementById('btn-outdent').onclick = outdentNode;
    document.getElementById('btn-delete-node').onclick = deleteNode;

    // Toolbar
    document.getElementById('btn-expand-all').onclick = expandAll;
    document.getElementById('btn-collapse-all').onclick = collapseAll;
    document.getElementById('search-nodes').oninput = (e) => searchNodes(e.target.value);

    // Bottom toolbar
    document.getElementById('btn-reset').onclick = resetMapping;
    document.getElementById('btn-preview').onclick = showPreview;
    document.getElementById('btn-save').onclick = saveMapping;
    document.getElementById('btn-close-book').onclick = closeBook;

    // Modal
    document.querySelector('.modal-close').onclick = closePreview;
    document.querySelector('.modal-backdrop').onclick = closePreview;

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl+S to save
        if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            saveMapping();
        }

        // Arrow keys for navigation when node selected
        if (selectedNodeKey && !e.target.matches('input, select, textarea')) {
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (e.altKey) moveNodeUp();
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (e.altKey) moveNodeDown();
            } else if (e.key === 'ArrowRight' && e.altKey) {
                e.preventDefault();
                indentNode();
            } else if (e.key === 'ArrowLeft' && e.altKey) {
                e.preventDefault();
                outdentNode();
            } else if (e.key === 'Delete') {
                deleteNode();
            }
        }
    });
}

function setupDragAndDrop() {
    // Global drag end cleanup
    document.addEventListener('dragend', () => {
        document.querySelectorAll('.dragging, .drag-over').forEach(el => {
            el.classList.remove('dragging', 'drag-over');
        });
    });
}
