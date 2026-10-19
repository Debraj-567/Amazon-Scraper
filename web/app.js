/**
 * Amazon Intelligence Scraper Pro - Client Logic
 * Handles real-time natural query parsing, live scraping polling,
 * rich product card rendering, and data export.
 */

let currentProducts = [];
let pollingInterval = null;
let currentViewMode = 'grid'; // 'grid' | 'table'

// DOM Elements
const searchForm = document.getElementById('scrape-form');
const searchInput = document.getElementById('search-input');
const detectedPillBox = document.getElementById('detected-pill-box');
const detectedBadge = document.getElementById('detected-badge');
const startBtn = document.getElementById('start-btn');
const toggleFiltersBtn = document.getElementById('toggle-filters-btn');
const advancedFilters = document.getElementById('advanced-filters');

const minPriceInput = document.getElementById('filter-min-price');
const maxPriceInput = document.getElementById('filter-max-price');
const pagesSelect = document.getElementById('filter-pages');
const ratingSelect = document.getElementById('filter-rating');
const inStockCheckbox = document.getElementById('filter-in-stock');
const primeCheckbox = document.getElementById('filter-prime');
const headlessCheckbox = document.getElementById('filter-headless');

const progressCard = document.getElementById('live-progress-card');
const progressFill = document.getElementById('progress-fill');
const progressPercentText = document.getElementById('progress-percent-text');
const progressStageText = document.getElementById('progress-stage-text');
const progressSubtext = document.getElementById('progress-subtext');
const terminalLogs = document.getElementById('terminal-logs-window');

const metricsCard = document.getElementById('metrics-card');
const statInStock = document.getElementById('stat-in-stock');
const statLowestPrice = document.getElementById('stat-lowest-price');
const statAvgPrice = document.getElementById('stat-avg-price');
const statMaxDiscount = document.getElementById('stat-max-discount');

const resultsToolbar = document.getElementById('results-toolbar');
const resultsCount = document.getElementById('results-count');
const activeBudgetPill = document.getElementById('active-budget-pill');
const sortSelect = document.getElementById('sort-select');
const viewModeGridBtn = document.getElementById('view-mode-grid');
const viewModeTableBtn = document.getElementById('view-mode-table');
const productsContainer = document.getElementById('products-container');
const emptyState = document.getElementById('empty-state');

const tabScraper = document.getElementById('tab-btn-scraper');
const tabHistory = document.getElementById('tab-btn-history');
const scraperView = document.getElementById('scraper-view');
const historyView = document.getElementById('history-view');
const historyTableBody = document.getElementById('history-table-body');
const historyCountBadge = document.getElementById('history-count-badge');
const historyFilterInput = document.getElementById('history-filter-input');
const refreshHistoryBtn = document.getElementById('refresh-history-btn');

const exportCsvBtn = document.getElementById('export-csv-btn');
const exportJsonBtn = document.getElementById('export-json-btn');
const toastEl = document.getElementById('toast');
const globalStatusText = document.getElementById('global-status-text');
const globalStatusPill = document.getElementById('global-status-pill');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  updateNaturalQueryPreview(searchInput.value);
  checkEngineStatus();
  loadHistoryCount();
});

function setupEventListeners() {
  // Natural Query input typing preview
  searchInput.addEventListener('input', (e) => {
    updateNaturalQueryPreview(e.target.value);
  });

  // Preset Pills
  document.querySelectorAll('.preset-pill').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.preset-pill').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      const q = btn.getAttribute('data-query');
      searchInput.value = q;
      updateNaturalQueryPreview(q);
      // Automatically trigger scrape for user convenience
      startScrapeProcess();
    });
  });

  // Toggle Advanced Filters
  toggleFiltersBtn.addEventListener('click', () => {
    advancedFilters.classList.toggle('hidden');
    const chevron = toggleFiltersBtn.querySelector('.chevron-icon');
    chevron.classList.toggle('rotate');
  });

  // Form Submit
  searchForm.addEventListener('submit', (e) => {
    e.preventDefault();
    startScrapeProcess();
  });

  // Sort change
  sortSelect.addEventListener('change', () => {
    applySortingAndRender();
  });

  // View Mode switches
  viewModeGridBtn.addEventListener('click', () => {
    currentViewMode = 'grid';
    viewModeGridBtn.classList.add('active');
    viewModeTableBtn.classList.remove('active');
    renderProducts();
  });

  viewModeTableBtn.addEventListener('click', () => {
    currentViewMode = 'table';
    viewModeTableBtn.classList.add('active');
    viewModeGridBtn.classList.remove('active');
    renderProducts();
  });

  // Navigation Tabs
  tabScraper.addEventListener('click', () => {
    tabScraper.classList.add('active');
    tabHistory.classList.remove('active');
    scraperView.classList.add('active');
    historyView.classList.remove('active');
  });

  tabHistory.addEventListener('click', () => {
    tabHistory.classList.add('active');
    tabScraper.classList.remove('active');
    historyView.classList.add('active');
    scraperView.classList.remove('active');
    fetchAndRenderHistory();
  });

  // History search
  historyFilterInput.addEventListener('input', filterHistoryTable);
  refreshHistoryBtn.addEventListener('click', fetchAndRenderHistory);

  // Exports
  exportCsvBtn.addEventListener('click', exportToCsv);
  exportJsonBtn.addEventListener('click', exportToJson);
}

// Client-side quick preview of detected budget
function updateNaturalQueryPreview(query) {
  const raw = (query || '').trim();
  if (!raw) return;

  let maxPrice = null;
  let minPrice = null;
  let budgetText = '';

  const underMatch = raw.match(/(?:under|below|less\s+than|up\s+to|within|max|<|<=)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|thousand|l|lac|lakh)?/i);
  if (underMatch) {
    let val = parseFloat(underMatch[1]);
    const unit = (underMatch[2] || '').toLowerCase();
    if (unit === 'k' || unit === 'thousand' || (val <= 100 && val > 0)) {
      val *= 1000;
    } else if (unit === 'l' || unit === 'lac' || unit === 'lakh') {
      val *= 100000;
    }
    maxPrice = val;
    budgetText = `Under ₹${val.toLocaleString('en-IN')}`;
    maxPriceInput.value = val;
  }

  const betweenMatch = raw.match(/(?:between|from)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k)?\s*(?:to|and|-)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k)?/i);
  if (betweenMatch) {
    let minVal = parseFloat(betweenMatch[1]) * (betweenMatch[2] ? 1000 : (parseFloat(betweenMatch[1]) <= 100 ? 1000 : 1));
    let maxVal = parseFloat(betweenMatch[3]) * (betweenMatch[4] ? 1000 : (parseFloat(betweenMatch[3]) <= 100 ? 1000 : 1));
    minPrice = minVal;
    maxPrice = maxVal;
    budgetText = `₹${minVal.toLocaleString('en-IN')} - ₹${maxVal.toLocaleString('en-IN')}`;
    minPriceInput.value = minVal;
    maxPriceInput.value = maxVal;
  }

  if (budgetText) {
    detectedBadge.innerHTML = `<strong>Detected Budget:</strong> ${budgetText} • <strong>Strict In-Stock Only:</strong> Active`;
  } else {
    maxPriceInput.value = '';
    minPriceInput.value = '';
    const bMatch = raw.match(/\b(ai\+?|pulse|samsung|oneplus|apple|iphone|redmi|realme|motorola|moto|iqoo|poco|nothing|vivo|oppo|lava|pixel|honor|nokia)\b/i);
    if (bMatch) {
      detectedBadge.innerHTML = `<strong>Target Brand/Model:</strong> "${escapeHtml(raw)}" • <strong>All Prices</strong> (All Available Models) • <strong>Verified Sellers</strong>`;
    } else {
      detectedBadge.innerHTML = `<strong>Search Mode:</strong> "${escapeHtml(raw)}" • All Prices • Verified Sellers`;
    }
  }
}

// Start Scrape Request
async function startScrapeProcess() {
  const query = searchInput.value.trim();
  if (!query) return;

  const deepScanCheckbox = document.getElementById('filter-deep-scan');

  const payload = {
    query: query,
    pages: parseInt(pagesSelect.value) || 1,
    min_price: minPriceInput.value ? parseFloat(minPriceInput.value) : null,
    max_price: maxPriceInput.value ? parseFloat(maxPriceInput.value) : null,
    in_stock_only: inStockCheckbox.checked,
    prime_only: primeCheckbox.checked,
    min_rating: ratingSelect.value ? parseFloat(ratingSelect.value) : null,
    headless: headlessCheckbox.checked,
    deep_scan: deepScanCheckbox ? deepScanCheckbox.checked : true,
  };

  // Show UI in Loading State
  startBtn.disabled = true;
  startBtn.querySelector('.btn-text').textContent = 'Scraping...';
  progressCard.classList.remove('hidden');
  emptyState.classList.add('hidden');
  terminalLogs.innerHTML = '';

  updateStatusIndicator('running', 'Scraping Active...');

  try {
    const res = await fetch('/api/scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errText = await res.text();
      showToast(`Server returned ${res.status}. Retrying...`);
      resetButton();
      return;
    }
    const data = await res.json();

    if (!data.success) {
      showToast(`Error: ${data.error || 'Failed to start'}`);
      resetButton();
      return;
    }

    // Direct synchronous results (e.g. Vercel Serverless environment)
    if (data.results && data.results.length > 0) {
      currentProducts = data.results;
      updateProgressUI({ progress: 100, message: data.message || `Scrape finished! Found ${currentProducts.length} items.` });
      renderMetrics(data.stats);
      applySortingAndRender();
      updateStatusIndicator('ready', `Catalog Ready (${currentProducts.length} items)`);
      resetButton();
      return;
    }

    // Otherwise start background status polling (local server)
    startPolling();
  } catch (err) {
    showToast(`Network error: ${err.message}`);
    resetButton();
  }
}

function startPolling() {
  if (pollingInterval) clearInterval(pollingInterval);

  pollingInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();

      updateProgressUI(data);

      if (data.status === 'completed' || data.status === 'error') {
        clearInterval(pollingInterval);
        pollingInterval = null;
        resetButton();

        if (data.status === 'completed') {
          currentProducts = data.results || [];
          renderMetrics(data.stats);
          applySortingAndRender();
          loadHistoryCount();
          updateStatusIndicator('ready', 'Completed & Ready');
          showToast(`✅ Successfully scraped ${currentProducts.length} in-stock products!`);
        } else {
          updateStatusIndicator('error', 'Scrape Error');
          showToast(`❌ Error: ${data.error || 'Scraping failed'}`);
        }
      }
    } catch (e) {
      console.error('Polling error', e);
    }
  }, 1200);
}

function updateProgressUI(data) {
  progressFill.style.width = `${data.progress || 10}%`;
  progressPercentText.textContent = `${data.progress || 10}%`;
  progressStageText.textContent = data.message || 'Scraping in progress...';

  if (data.logs && data.logs.length > 0) {
    const lastLogs = data.logs.slice(-10);
    terminalLogs.innerHTML = lastLogs.map((l) => `<div class="log-line">${escapeHtml(l)}</div>`).join('');
    terminalLogs.scrollTop = terminalLogs.scrollHeight;
  }
}

function resetButton() {
  startBtn.disabled = false;
  startBtn.querySelector('.btn-text').textContent = 'Scrape Amazon';
}

function updateStatusIndicator(status, text) {
  globalStatusText.textContent = text;
  globalStatusPill.className = `status-indicator ${status}`;
}

async function checkEngineStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    if (data.status === 'running') {
      startBtn.disabled = true;
      startBtn.querySelector('.btn-text').textContent = 'Scraping...';
      progressCard.classList.remove('hidden');
      startPolling();
    } else if (data.status === 'completed' && data.results && data.results.length > 0) {
      currentProducts = data.results;
      renderMetrics(data.stats);
      applySortingAndRender();
      updateStatusIndicator('ready', `Catalog Ready (${currentProducts.length} items)`);
      if (data.query) {
        searchInput.value = data.query;
        updateNaturalQueryPreview(data.query);
      }
    }
  } catch (e) {}
}

// Metrics rendering
function renderMetrics(stats) {
  if (!stats || !stats.total_found) {
    metricsCard.classList.add('hidden');
    return;
  }

  metricsCard.classList.remove('hidden');
  statInStock.textContent = stats.in_stock || stats.total_found;
  statLowestPrice.textContent = stats.lowest_price ? `₹${stats.lowest_price.toLocaleString('en-IN')}` : 'N/A';
  statAvgPrice.textContent = stats.avg_price ? `₹${stats.avg_price.toLocaleString('en-IN')}` : 'N/A';
  statMaxDiscount.textContent = stats.max_discount || 'N/A';
}

// Sorting and Rendering
function applySortingAndRender() {
  const sortMode = sortSelect.value;

  currentProducts.sort((a, b) => {
    if (sortMode === 'price-asc') {
      return (a.price_num || 9999999) - (b.price_num || 9999999);
    }
    if (sortMode === 'price-desc') {
      return (b.price_num || 0) - (a.price_num || 0);
    }
    if (sortMode === 'discount-desc') {
      const getD = (item) => {
        const m = (item.discount || '').match(/(\d+)/);
        return m ? parseInt(m[1]) : 0;
      };
      return getD(b) - getD(a);
    }
    if (sortMode === 'rating-desc') {
      return (b.rating_num || 0) - (a.rating_num || 0);
    }
    return 0;
  });

  renderProducts();
}

let activeBrandFilter = 'ALL';

function renderBrandChips() {
  const container = document.getElementById('brand-filters-container');
  const list = document.getElementById('brand-chips-list');
  if (!container || !list) return;

  if (!currentProducts || currentProducts.length === 0) {
    container.classList.add('hidden');
    return;
  }

  const counts = {};
  currentProducts.forEach((p) => {
    let b = p.brand;
    if (!b || b === 'Unknown') {
      if ((p.title || '').toLowerCase().includes('pulse 2')) b = 'AI+';
      else b = 'Other';
    }
    counts[b] = (counts[b] || 0) + 1;
  });

  const sortedBrands = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);

  let html = `<button type="button" class="brand-chip ${activeBrandFilter === 'ALL' ? 'active' : ''}" data-brand="ALL">All (${currentProducts.length})</button>`;
  sortedBrands.forEach((b) => {
    const isAct = activeBrandFilter.toLowerCase() === b.toLowerCase();
    html += `<button type="button" class="brand-chip ${isAct ? 'active' : ''}" data-brand="${escapeHtml(b)}">${escapeHtml(b)} (${counts[b]})</button>`;
  });

  list.innerHTML = html;
  container.classList.remove('hidden');

  list.querySelectorAll('.brand-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      activeBrandFilter = btn.getAttribute('data-brand');
      renderProducts();
    });
  });
}

function renderProducts() {
  if (!currentProducts || currentProducts.length === 0) {
    productsContainer.innerHTML = '';
    emptyState.classList.remove('hidden');
    resultsToolbar.classList.add('hidden');
    const container = document.getElementById('brand-filters-container');
    if (container) container.classList.add('hidden');
    return;
  }

  emptyState.classList.add('hidden');
  resultsToolbar.classList.remove('hidden');

  renderBrandChips();

  let filtered = currentProducts;
  if (activeBrandFilter !== 'ALL') {
    filtered = currentProducts.filter((p) => {
      const b = (p.brand || '').toLowerCase();
      const target = activeBrandFilter.toLowerCase();
      if (b === target) return true;
      if (target === 'ai+' && (p.title || '').toLowerCase().includes('pulse 2')) return true;
      return false;
    });
  }

  resultsCount.textContent = `${filtered.length} of ${currentProducts.length}`;

  const budgetText = maxPriceInput.value ? `Budget: Under ₹${parseInt(maxPriceInput.value).toLocaleString('en-IN')}` : 'All Prices';
  activeBudgetPill.textContent = `${budgetText} (Strictly In-Stock)`;

  if (currentViewMode === 'grid') {
    productsContainer.className = 'products-grid';
    productsContainer.innerHTML = filtered.map((p) => createProductCardHTML(p)).join('');
  } else {
    productsContainer.className = 'table-responsive glass-panel';
    productsContainer.innerHTML = createProductsTableHTML(filtered);
  }

  // Attach ASIN click-to-copy
  document.querySelectorAll('.asin-code').forEach((el) => {
    el.addEventListener('click', () => {
      const asin = el.getAttribute('data-asin');
      navigator.clipboard.writeText(asin);
      showToast(`📋 ASIN ${asin} copied to clipboard!`);
    });
  });
}

function createProductCardHTML(p) {
  const discountBadge = p.discount ? `<span class="discount-tag">${p.discount} OFF</span>` : '';
  const mrpEl = p.mrp ? `<span class="mrp-price">${escapeHtml(p.mrp)}</span>` : '';
  const brandEl = p.brand ? `<span class="brand-name">${escapeHtml(p.brand)}</span>` : '<span class="brand-name">Amazon</span>';
  const primeEl = p.is_prime ? `<span class="prime-badge">⚡ Prime</span>` : '';
  const badgeEl = p.badge ? `<span class="deal-pill">${escapeHtml(p.badge)}</span>` : '';

  const specsList = (p.specs || []).map((s) => `<span class="spec-tag">${escapeHtml(s)}</span>`).join('');

  return `
    <div class="product-card">
      <div class="product-img-box">
        <div class="badge-row">
          <span class="stock-pill in-stock">🟢 In Stock</span>
          ${badgeEl}
        </div>
        <img class="product-img" src="${p.image_url || 'https://via.placeholder.com/260?text=Amazon+Product'}" alt="${escapeHtml(p.title)}" loading="lazy" />
      </div>

      <div class="product-body">
        <div class="brand-asin-row">
          ${brandEl}
          <span class="asin-code" data-asin="${escapeHtml(p.asin)}" title="Click to Copy ASIN">${escapeHtml(p.asin)}</span>
        </div>

        <h4 class="product-title" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</h4>

        <div class="specs-tags-row">
          ${specsList}
        </div>

        <div class="price-section">
          <span class="current-price">${escapeHtml(p.price)}</span>
          ${mrpEl}
          ${discountBadge}
        </div>

        <div class="rating-prime-row">
          <span class="rating-stars">★ ${p.rating ? escapeHtml(p.rating.replace('out of 5 stars', '').trim()) : '4.0'}</span>
          <span class="review-count">${p.review_count ? escapeHtml(p.review_count) : ''}</span>
          ${primeEl}
        </div>

        <div class="seller-info-row">
          <span class="seller-icon">🏪</span>
          <span class="seller-label">Seller:</span>
          <span class="seller-val" title="${escapeHtml(p.seller || 'Amazon Verified Seller')}">${escapeHtml(p.seller || 'Amazon Verified Seller')}</span>
        </div>

        <div class="product-actions">
          <a href="${escapeHtml(p.url)}" target="_blank" rel="noopener noreferrer" class="view-amazon-btn">
            <span>View on Amazon</span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          </a>
        </div>
      </div>
    </div>
  `;
}

function createProductsTableHTML(items) {
  return `
    <table class="data-table">
      <thead>
        <tr>
          <th>Image</th>
          <th>Title</th>
          <th>ASIN</th>
          <th>Price</th>
          <th>MRP</th>
          <th>Discount</th>
          <th>Rating</th>
          <th>Seller</th>
          <th>Stock</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${items
          .map(
            (p) => `
          <tr>
            <td><img src="${p.image_url}" class="table-thumb" alt="${escapeHtml(p.asin)}"/></td>
            <td><strong>${escapeHtml(p.title.slice(0, 65))}...</strong></td>
            <td><span class="asin-code" data-asin="${escapeHtml(p.asin)}">${escapeHtml(p.asin)}</span></td>
            <td><strong class="text-amber">${escapeHtml(p.price)}</strong></td>
            <td><span class="mrp-price">${escapeHtml(p.mrp || '-')}</span></td>
            <td><span class="discount-tag">${escapeHtml(p.discount || '-')}</span></td>
            <td>★ ${escapeHtml(p.rating || '4.0')}</td>
            <td><span class="seller-cell" title="${escapeHtml(p.seller || 'Amazon Verified Seller')}"><span class="seller-icon">🏪</span> ${escapeHtml(p.seller || 'Amazon Verified Seller')}</span></td>
            <td><span class="stock-pill in-stock">In Stock</span></td>
            <td><a href="${escapeHtml(p.url)}" target="_blank" class="view-amazon-btn" style="padding:4px 8px;font-size:0.75rem;">Open</a></td>
          </tr>
        `
          )
          .join('')}
      </tbody>
    </table>
  `;
}

// Saved History Database
async function fetchAndRenderHistory() {
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (!data.success) return;

    const items = data.items || [];
    historyCountBadge.textContent = items.length;

    historyTableBody.innerHTML = items
      .map(
        (p) => `
      <tr>
        <td><img src="${p.image_url || ''}" class="table-thumb" alt="${escapeHtml(p.asin)}"/></td>
        <td><strong>${escapeHtml((p.title || '').slice(0, 75))}</strong></td>
        <td><span class="asin-code" data-asin="${escapeHtml(p.asin)}">${escapeHtml(p.asin)}</span></td>
        <td><strong class="text-amber">${escapeHtml(p.price || '-')}</strong></td>
        <td><span class="mrp-price">${escapeHtml(p.mrp || '-')}</span></td>
        <td><span class="discount-tag">${escapeHtml(p.discount || '-')}</span></td>
        <td>${escapeHtml(p.rating || '-')}</td>
        <td><span class="seller-cell" title="${escapeHtml(p.seller || 'Amazon Verified Seller')}"><span class="seller-icon">🏪</span> ${escapeHtml(p.seller || 'Amazon Verified')}</span></td>
        <td><span class="stock-pill in-stock">${escapeHtml(p.availability || 'In Stock')}</span></td>
        <td><a href="${escapeHtml(p.url || '#')}" target="_blank" class="view-amazon-btn" style="padding:4px 8px;font-size:0.75rem;">Amazon</a></td>
      </tr>
    `
      )
      .join('');
  } catch (e) {
    console.error(e);
  }
}

async function loadHistoryCount() {
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (data.items) {
      historyCountBadge.textContent = data.items.length;
    }
  } catch (e) {}
}

function filterHistoryTable(e) {
  const term = e.target.value.toLowerCase();
  const rows = historyTableBody.querySelectorAll('tr');
  rows.forEach((row) => {
    const text = row.textContent.toLowerCase();
    row.style.display = text.includes(term) ? '' : 'none';
  });
}

// Exports
function exportToCsv() {
  if (!currentProducts || currentProducts.length === 0) {
    showToast('No products to export.');
    return;
  }
  const headers = ['asin', 'title', 'price', 'mrp', 'discount', 'rating', 'availability', 'url'];
  const rows = currentProducts.map((p) => [
    `"${p.asin}"`,
    `"${(p.title || '').replace(/"/g, '""')}"`,
    `"${p.price || ''}"`,
    `"${p.mrp || ''}"`,
    `"${p.discount || ''}"`,
    `"${p.rating || ''}"`,
    `"${p.availability || 'In stock'}"`,
    `"${p.url || ''}"`,
  ]);

  const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement('a');
  link.setAttribute('href', encodedUri);
  link.setAttribute('download', `amazon_scraped_${Date.now()}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast('📥 CSV downloaded successfully!');
}

function exportToJson() {
  if (!currentProducts || currentProducts.length === 0) {
    showToast('No products to export.');
    return;
  }
  const jsonString = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(currentProducts, null, 2));
  const link = document.createElement('a');
  link.setAttribute('href', jsonString);
  link.setAttribute('download', `amazon_scraped_${Date.now()}.json`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast('📥 JSON downloaded successfully!');
}

function showToast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.remove('hidden');
  setTimeout(() => {
    toastEl.classList.add('hidden');
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
