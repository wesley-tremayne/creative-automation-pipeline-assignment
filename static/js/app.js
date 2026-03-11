'use strict';

/* exported
   handleLogoUpload, formatJson, runPipeline, toggleConfig, switchConfigTab,
   syncColorDisplay, loadConfigProfile, saveConfig, saveConfigAs, resetConfig,
   addWordEntry, addSuperlative, filterRatio, configOpen
*/

// ── State ───────────────────────────────────────────────────────────────────────
/** @type {Array<{asset: Object, product: Object}>} All generated assets from last pipeline run */
let allAssets = [];
/** @type {'form'|'json'} Current input mode */
let currentMode = 'form';
/** @type {number} Running count of product cards added */
let productCount = 0;
/** @type {string|null} Uploaded logo filename returned by the API */
let logoFilename = null;
/** @type {'none'|'upload'|'generate'} Current logo mode */
let logoMode = 'none';

// ── Initialization ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);

/**
 * Initialize the application — add first product, load campaigns and API status.
 * @returns {Promise<void>}
 */
async function init() {
  addProduct();
  await loadCampaigns();
  checkApiStatus();
  loadBriefConfigProfiles();
}

// ── API Functions ────────────────────────────────────────────────────────────────

/**
 * Load available config profiles and populate brand/content select elements.
 * @returns {Promise<void>}
 */
async function loadBriefConfigProfiles() {
  try {
    const res = await fetch('/api/config/profiles');
    if (!res.ok) {
      return;
    }
    const data = await res.json();
    const brandSelect = document.getElementById('f-brand-config');
    const contentSelect = document.getElementById('f-content-config');
    const brandCurrent = brandSelect.value;
    const contentCurrent = contentSelect.value;
    const brandProfiles = data.profiles['brand-guidelines'] || [];
    const contentProfiles = data.profiles['prohibited-words'] || [];
    brandSelect.innerHTML =
      '<option value="">Default</option>' +
      brandProfiles
        .map((n) => `<option value="${n}" ${n === brandCurrent ? 'selected' : ''}>${n}</option>`)
        .join('');
    contentSelect.innerHTML =
      '<option value="">Default</option>' +
      contentProfiles
        .map((n) => `<option value="${n}" ${n === contentCurrent ? 'selected' : ''}>${n}</option>`)
        .join('');
  } catch (e) {
    console.warn('Failed to load config profiles:', e);
  }
}

/**
 * Check API health and update the status indicator in the header.
 * @returns {Promise<void>}
 */
async function checkApiStatus() {
  try {
    const r = await fetch('/api/campaigns');
    const el = document.getElementById('api-status');
    if (r.ok) {
      el.innerHTML =
        '<span class="w-2 h-2 rounded-full bg-green-400 inline-block"></span> <span class="text-green-400">API Ready</span>';
    }
  } catch (e) {
    console.warn('API status check failed:', e);
  }
}

// ── Mode Switching ───────────────────────────────────────────────────────────────

/**
 * Switch between Form and JSON input modes, syncing data in both directions.
 * @param {'form'|'json'} mode - The mode to switch to
 */
function switchMode(mode) {
  if (mode === currentMode) {
    return;
  }

  if (currentMode === 'form' && mode === 'json') {
    syncFormToJson();
  } else if (currentMode === 'json' && mode === 'form') {
    syncJsonToForm();
  }

  currentMode = mode;
  document.getElementById('form-mode').classList.toggle('hidden', mode !== 'form');
  document.getElementById('json-mode').classList.toggle('hidden', mode !== 'json');
  document.getElementById('mode-form-btn').classList.toggle('active', mode === 'form');
  document.getElementById('mode-json-btn').classList.toggle('active', mode === 'json');
  document.getElementById('mode-form-btn').classList.toggle('text-slate-400', mode !== 'form');
  document.getElementById('mode-json-btn').classList.toggle('text-slate-400', mode !== 'json');
}

/**
 * Serialize the current form values to the JSON editor textarea.
 */
function syncFormToJson() {
  try {
    const brief = buildBriefFromForm();
    document.getElementById('brief-editor').value = JSON.stringify(brief, null, 2);
  } catch (e) {
    console.warn('Failed to sync form to JSON:', e);
  }
}

/**
 * Parse the JSON editor textarea and populate the form fields.
 */
function syncJsonToForm() {
  try {
    const text = document.getElementById('brief-editor').value.trim();
    if (!text) {
      return;
    }
    const data = JSON.parse(text);
    populateForm(data);
  } catch (e) {
    showUserError(
      'JSON is invalid and could not be loaded into the form. Please check your syntax.',
    );
    console.warn('Failed to sync JSON to form:', e);
  }
}

// ── Brief Building ───────────────────────────────────────────────────────────────

/**
 * Build a campaign brief object from the current form field values.
 * @returns {Object} Campaign brief ready to POST to the API
 */
function buildBriefFromForm() {
  const brief = {};
  const cid = document.getElementById('f-campaign-id').value.trim();
  if (cid) {
    brief.campaign_id = cid;
  }

  const brandName = document.getElementById('f-brand-name').value.trim();
  if (brandName) {
    brief.brand_name = brandName;
  }

  const region = document.getElementById('f-target-region').value.trim();
  if (region) {
    brief.target_region = region;
  }

  const market = document.getElementById('f-target-market').value.trim();
  if (market) {
    brief.target_market = market;
  }

  const audience = document.getElementById('f-target-audience').value.trim();
  if (audience) {
    brief.target_audience = audience;
  }

  const message = document.getElementById('f-campaign-message').value.trim();
  if (message) {
    brief.campaign_message = message;
  }

  const offer = document.getElementById('f-offer').value.trim();
  if (offer) {
    brief.offer = offer;
  }

  const cta = document.getElementById('f-cta').value.trim();
  if (cta) {
    brief.cta = cta;
  }

  const lang = document.getElementById('f-language').value;
  if (lang) {
    brief.language = lang;
  }

  const tone = document.getElementById('f-tone').value.trim();
  if (tone) {
    brief.tone = tone;
  }

  const website = document.getElementById('f-website').value.trim();
  if (website) {
    brief.website = website;
  }

  const brandConfig = document.getElementById('f-brand-config').value;
  if (brandConfig) {
    brief.brand_config = brandConfig;
  }

  const contentConfig = document.getElementById('f-content-config').value;
  if (contentConfig) {
    brief.content_config = contentConfig;
  }

  if (logoMode === 'generate') {
    brief.logo = 'generate';
  } else if (logoMode === 'upload' && logoFilename) {
    brief.logo = logoFilename;
  }

  brief.products = [];
  const cards = document.querySelectorAll('.product-card');
  cards.forEach((card) => {
    const product = {};
    const nameEl = card.querySelector('.p-name');
    const descEl = card.querySelector('.p-desc');
    const catEl = card.querySelector('.p-cat');
    const tagEl = card.querySelector('.p-tagline');
    const assetEl = card.querySelector('.p-asset');

    if (nameEl && nameEl.value.trim()) {
      product.name = nameEl.value.trim();
    }
    if (descEl && descEl.value.trim()) {
      product.description = descEl.value.trim();
    }
    if (catEl && catEl.value.trim()) {
      product.category = catEl.value.trim();
    }
    if (tagEl && tagEl.value.trim()) {
      product.tagline = tagEl.value.trim();
    }
    if (assetEl && assetEl.value.trim()) {
      product.existing_asset = assetEl.value.trim();
    }

    if (product.name || product.description || product.category) {
      brief.products.push(product);
    }
  });

  if (!brief.products.length) {
    delete brief.products;
  }

  return brief;
}

/**
 * Populate all form fields from a campaign brief data object.
 * @param {Object} data - Campaign brief data
 */
function populateForm(data) {
  document.getElementById('f-campaign-id').value = data.campaign_id || '';
  document.getElementById('f-brand-name').value = data.brand_name || 'Brand';
  document.getElementById('f-target-region').value = data.target_region || '';
  document.getElementById('f-target-market').value = data.target_market || '';
  document.getElementById('f-target-audience').value = data.target_audience || '';
  document.getElementById('f-campaign-message').value = data.campaign_message || '';
  document.getElementById('f-offer').value = data.offer || '';
  document.getElementById('f-cta').value = data.cta || 'Shop Now';
  document.getElementById('f-language').value = data.language || 'en';
  document.getElementById('f-tone').value = data.tone || 'professional, aspirational';
  document.getElementById('f-website').value = data.website || '';
  document.getElementById('f-brand-config').value = data.brand_config || '';
  document.getElementById('f-content-config').value = data.content_config || '';

  setLogoFromData(data.logo || null);

  // Clear all validation errors
  document.querySelectorAll('.field-error').forEach((el) => el.classList.remove('field-error'));
  document.querySelectorAll('.error-msg').forEach((el) => el.classList.add('hidden'));

  const container = document.getElementById('products-container');
  container.innerHTML = '';
  productCount = 0;

  if (data.products && data.products.length) {
    data.products.forEach((p) => addProduct(p));
  } else {
    addProduct();
  }
}

// ── Products ─────────────────────────────────────────────────────────────────────

/**
 * Add a new product card to the products container.
 * @param {Object} [data] - Optional existing product data to pre-fill
 */
function addProduct(data) {
  productCount++;
  const idx = productCount;
  const container = document.getElementById('products-container');
  const card = document.createElement('div');
  card.className = 'product-card glass rounded-lg p-4';

  const header = document.createElement('div');
  header.className = 'flex items-center justify-between mb-3';

  const label = document.createElement('span');
  label.className = 'text-xs font-semibold text-slate-400';
  label.textContent = `Product ${idx}`;

  const removeBtn = document.createElement('button');
  removeBtn.className = 'text-xs text-red-400 hover:text-red-300 transition';
  removeBtn.title = 'Remove product';
  removeBtn.setAttribute('aria-label', `Remove product ${idx}`);
  removeBtn.textContent = '✕ Remove';
  removeBtn.addEventListener('click', () => removeProduct(removeBtn));

  header.appendChild(label);
  header.appendChild(removeBtn);
  card.appendChild(header);

  const grid1 = document.createElement('div');
  grid1.className = 'grid grid-cols-2 gap-3 mb-2';
  grid1.innerHTML = `
    <div>
      <label class="form-label">Name <span class="required" aria-hidden="true">*</span></label>
      <input type="text" class="form-input p-name" placeholder="e.g. HydraBoost Serum"
        maxlength="200" value="${escAttr(data && data.name)}" aria-label="Product name" aria-required="true">
    </div>
    <div>
      <label class="form-label">Category <span class="required" aria-hidden="true">*</span></label>
      <input type="text" class="form-input p-cat" placeholder="e.g. Skincare"
        maxlength="100" value="${escAttr(data && data.category)}" aria-label="Product category" aria-required="true">
    </div>
  `;

  const descDiv = document.createElement('div');
  descDiv.className = 'mb-2';
  descDiv.innerHTML = `
    <label class="form-label">Description <span class="required" aria-hidden="true">*</span></label>
    <input type="text" class="form-input p-desc"
      placeholder="e.g. Advanced hydration serum with hyaluronic acid"
      maxlength="1000" value="${escAttr(data && data.description)}" aria-label="Product description" aria-required="true">
  `;

  const grid2 = document.createElement('div');
  grid2.className = 'grid grid-cols-2 gap-3';
  grid2.innerHTML = `
    <div>
      <label class="form-label">Tagline</label>
      <input type="text" class="form-input p-tagline" placeholder="Optional tagline"
        maxlength="200" value="${escAttr(data && data.tagline)}" aria-label="Product tagline">
    </div>
    <div>
      <label class="form-label">Existing Asset</label>
      <input type="text" class="form-input p-asset" placeholder="path/to/image.png"
        maxlength="255" value="${escAttr(data && data.existing_asset)}" aria-label="Existing asset path">
    </div>
  `;

  card.appendChild(grid1);
  card.appendChild(descDiv);
  card.appendChild(grid2);

  // Clear validation errors on input
  card.querySelectorAll('.form-input').forEach((input) => {
    input.addEventListener('input', () => clearFieldError(input));
  });

  container.appendChild(card);
  updateRemoveButtons();
}

/**
 * Remove a product card from the container.
 * @param {HTMLButtonElement} btn - The remove button that was clicked
 */
function removeProduct(btn) {
  const container = document.getElementById('products-container');
  if (container.children.length <= 1) {
    return;
  }
  btn.closest('.product-card').remove();
  renumberProducts();
  updateRemoveButtons();
}

/**
 * Update the "Product N" labels after a card is removed.
 */
function renumberProducts() {
  const cards = document.querySelectorAll('.product-card');
  cards.forEach((card, i) => {
    const labelEl = card.querySelector('span');
    if (labelEl) {
      labelEl.textContent = `Product ${i + 1}`;
    }
    const removeBtn = card.querySelector('button');
    if (removeBtn) {
      removeBtn.setAttribute('aria-label', `Remove product ${i + 1}`);
    }
  });
}

/**
 * Enable or disable the remove buttons based on how many product cards exist.
 */
function updateRemoveButtons() {
  const cards = document.querySelectorAll('.product-card');
  cards.forEach((card) => {
    const rmBtn = card.querySelector('button');
    if (!rmBtn) {
      return;
    }
    if (cards.length <= 1) {
      rmBtn.classList.add('opacity-30', 'pointer-events-none');
    } else {
      rmBtn.classList.remove('opacity-30', 'pointer-events-none');
    }
  });
}

/**
 * Escape a value for safe use in an HTML attribute.
 * @param {string|null|undefined} val - The value to escape
 * @returns {string} Escaped string safe for HTML attributes
 */
function escAttr(val) {
  if (!val) {
    return '';
  }
  return val
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ── Logo ─────────────────────────────────────────────────────────────────────────

/**
 * Set the logo mode and show/hide the relevant UI sections.
 * @param {'none'|'upload'|'generate'} mode - The selected logo mode
 */
function setLogoMode(mode) {
  logoMode = mode;
  document.getElementById('logo-upload-area').classList.toggle('hidden', mode !== 'upload');
  document.getElementById('logo-generate-info').classList.toggle('hidden', mode !== 'generate');
  if (mode === 'none' || mode === 'generate') {
    logoFilename = null;
    document.getElementById('logo-preview').classList.add('hidden');
  }
}

/**
 * Handle logo file selection — upload the file and show a preview.
 * @param {HTMLInputElement} input - The file input element
 * @returns {Promise<void>}
 */
async function handleLogoUpload(input) {
  const file = input.files[0];
  if (!file) {
    return;
  }
  const statusEl = document.getElementById('logo-upload-status');
  statusEl.classList.remove('hidden');
  statusEl.textContent = 'Uploading...';
  statusEl.className = 'text-xs text-slate-500 mt-1';

  if (file.size > 5 * 1024 * 1024) {
    statusEl.textContent = 'File too large (max 5MB)';
    statusEl.className = 'text-xs text-red-400 mt-1';
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  try {
    const r = await fetch('/api/upload/logo', { method: 'POST', body: formData });
    if (!r.ok) {
      const err = await r.json();
      statusEl.textContent = err.detail || 'Upload failed';
      statusEl.className = 'text-xs text-red-400 mt-1';
      return;
    }
    const data = await r.json();
    logoFilename = data.filename;
    statusEl.textContent = `Uploaded: ${data.filename}`;
    statusEl.className = 'text-xs text-green-400 mt-1';
    const previewEl = document.getElementById('logo-preview');
    const imgEl = document.getElementById('logo-preview-img');
    imgEl.src = URL.createObjectURL(file);
    previewEl.classList.remove('hidden');
  } catch (e) {
    statusEl.textContent = `Upload failed: ${e.message}`;
    statusEl.className = 'text-xs text-red-400 mt-1';
  }
}

/**
 * Set the logo UI state from a brief's logo field value.
 * @param {string|null} logoValue - 'generate', a filename, or null
 */
function setLogoFromData(logoValue) {
  if (!logoValue) {
    logoMode = 'none';
    logoFilename = null;
    const noneRadio = document.querySelector('input[name="logo-mode"][value="none"]');
    if (noneRadio) {
      noneRadio.checked = true;
    }
    setLogoMode('none');
  } else if (logoValue === 'generate') {
    logoMode = 'generate';
    logoFilename = null;
    const genRadio = document.querySelector('input[name="logo-mode"][value="generate"]');
    if (genRadio) {
      genRadio.checked = true;
    }
    setLogoMode('generate');
  } else {
    logoMode = 'upload';
    logoFilename = logoValue;
    const uploadRadio = document.querySelector('input[name="logo-mode"][value="upload"]');
    if (uploadRadio) {
      uploadRadio.checked = true;
    }
    setLogoMode('upload');
    const statusEl = document.getElementById('logo-upload-status');
    statusEl.classList.remove('hidden');
    statusEl.textContent = `Logo: ${logoValue}`;
    statusEl.className = 'text-xs text-green-400 mt-1';
    document.getElementById('logo-preview').classList.add('hidden');
  }
}

// ── Validation ───────────────────────────────────────────────────────────────────

/**
 * Clear the error state from a field and hide its error message.
 * @param {HTMLElement} el - The input element to clear
 */
function clearFieldError(el) {
  el.classList.remove('field-error');
  const errEl = el.parentElement.querySelector('.error-msg');
  if (errEl) {
    errEl.classList.add('hidden');
  }
}

/**
 * Mark a field as invalid and show an error message below it.
 * @param {HTMLElement} el - The input element with an error
 * @param {string} msg - The error message to display
 */
function showFieldError(el, msg) {
  el.classList.add('field-error');
  let errEl = el.parentElement.querySelector('.error-msg');
  if (!errEl) {
    errEl = document.createElement('div');
    errEl.className = 'error-msg';
    el.parentElement.appendChild(errEl);
  }
  errEl.textContent = msg;
  errEl.classList.remove('hidden');
}

/**
 * Validate all required form fields and product cards.
 * @returns {boolean} True if all fields are valid
 */
function validateForm() {
  let valid = true;

  /** @type {Array<{id: string, errId: string, label: string, maxLen: number}>} */
  const requiredFields = [
    { id: 'f-campaign-id', errId: 'err-campaign-id', label: 'Campaign ID', maxLen: 100 },
    { id: 'f-target-region', errId: 'err-target-region', label: 'Target Region', maxLen: 50 },
    {
      id: 'f-target-audience',
      errId: 'err-target-audience',
      label: 'Target Audience',
      maxLen: 500,
    },
    {
      id: 'f-campaign-message',
      errId: 'err-campaign-message',
      label: 'Campaign Message',
      maxLen: 500,
    },
  ];

  requiredFields.forEach((f) => {
    const el = document.getElementById(f.id);
    const errEl = document.getElementById(f.errId);
    const val = el.value.trim();
    if (!val) {
      el.classList.add('field-error');
      errEl.textContent = `${f.label} is required`;
      errEl.classList.remove('hidden');
      valid = false;
    } else if (val.length > f.maxLen) {
      el.classList.add('field-error');
      errEl.textContent = `${f.label} must be ${f.maxLen} characters or fewer`;
      errEl.classList.remove('hidden');
      valid = false;
    } else {
      el.classList.remove('field-error');
      errEl.classList.add('hidden');
    }
  });

  const cards = document.querySelectorAll('.product-card');
  const errProducts = document.getElementById('err-products');

  cards.forEach((card) => {
    const nameEl = card.querySelector('.p-name');
    const descEl = card.querySelector('.p-desc');
    const catEl = card.querySelector('.p-cat');

    [
      { el: nameEl, label: 'Name', maxLen: 200 },
      { el: descEl, label: 'Description', maxLen: 1000 },
      { el: catEl, label: 'Category', maxLen: 100 },
    ].forEach(({ el, label, maxLen }) => {
      if (!el || !el.value.trim()) {
        showFieldError(el, `${label} is required`);
        valid = false;
      } else if (el.value.trim().length > maxLen) {
        showFieldError(el, `${label} must be ${maxLen} characters or fewer`);
        valid = false;
      } else {
        clearFieldError(el);
      }
    });
  });

  if (!cards.length) {
    errProducts.textContent = 'At least one product is required';
    errProducts.classList.remove('hidden');
    valid = false;
  } else {
    errProducts.classList.add('hidden');
  }

  return valid;
}

// ── User Feedback ────────────────────────────────────────────────────────────────

/**
 * Display a transient error message in the pipeline log area.
 * @param {string} msg - The error message to display
 */
function showUserError(msg) {
  const logEl = document.getElementById('log-container');
  if (!logEl) {
    return;
  }
  const div = document.createElement('div');
  div.className = 'log-item text-red-400 flex items-start gap-2';
  div.textContent = `⚠ ${msg}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

// ── Campaigns History ────────────────────────────────────────────────────────────

/**
 * Fetch and render the list of previously run campaigns.
 * @returns {Promise<void>}
 */
async function loadCampaigns() {
  try {
    const r = await fetch('/api/campaigns');
    if (!r.ok) {
      throw new Error(`HTTP ${r.status}`);
    }
    const data = await r.json();
    const el = document.getElementById('campaigns-list');
    if (!data.campaigns.length) {
      el.innerHTML = `
        <div class="text-center py-8">
          <div class="text-3xl mb-2 opacity-30">📂</div>
          <div class="text-slate-500 text-sm">No campaigns generated yet</div>
          <div class="text-slate-600 text-xs mt-1">Run a pipeline to see your campaigns here</div>
        </div>`;
      return;
    }
    el.innerHTML = `<div class="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[400px] overflow-y-auto">${data.campaigns.map((c) => buildCampaignCard(c)).join('')}</div>`;

    // Attach event listeners after rendering
    el.querySelectorAll('[data-action="reuse"]').forEach((btn) => {
      btn.addEventListener('click', () => reuseCampaign(btn.dataset.id));
    });
    el.querySelectorAll('[data-action="delete"]').forEach((btn) => {
      btn.addEventListener('click', () => deleteCampaign(btn.dataset.id));
    });
  } catch (e) {
    console.warn('Failed to load campaigns:', e);
    const el = document.getElementById('campaigns-list');
    el.innerHTML = '<div class="text-slate-500 text-xs">Failed to load campaigns.</div>';
  }
}

/**
 * Build the HTML string for a single campaign card.
 * @param {Object} c - Campaign data object
 * @returns {string} HTML string for the campaign card
 */
function buildCampaignCard(c) {
  const safeId = escAttr(c.campaign_id);
  return `
    <div class="campaign-card glass rounded-xl p-5 border border-slate-700/50">
      <div class="flex items-start justify-between mb-3">
        <div>
          <div class="text-sm font-semibold text-slate-200">${formatCampaignName(c.campaign_id)}</div>
          <div class="text-xs text-slate-500 font-mono mt-0.5">${escAttr(c.campaign_id)}</div>
        </div>
        <div class="flex-shrink-0 w-8 h-8 rounded-lg bg-violet-600/20 flex items-center justify-center" aria-hidden="true">
          <span class="text-violet-400 text-sm">📊</span>
        </div>
      </div>
      ${c.brand_name ? `<div class="text-xs text-slate-400 mb-2">🏷 ${escAttr(c.brand_name)}</div>` : ''}
      <div class="flex items-center gap-3 text-xs text-slate-400 mb-4">
        <span class="flex items-center gap-1">
          <span class="text-violet-400" aria-hidden="true">🖼</span> ${c.asset_count} assets
        </span>
        ${c.product_count ? `<span class="flex items-center gap-1"><span class="text-blue-400" aria-hidden="true">📦</span> ${c.product_count} products</span>` : ''}
        ${c.created_at ? `<span class="flex items-center gap-1"><span class="text-slate-500" aria-hidden="true">📅</span> ${formatDate(c.created_at)}</span>` : ''}
      </div>
      <div class="flex gap-2 mb-2">
        ${
          c.has_report
            ? `<a href="/api/report/${safeId}" target="_blank" rel="noopener noreferrer"
              aria-label="Open report for ${escAttr(c.campaign_id)}"
              class="flex-1 text-center bg-violet-600/20 hover:bg-violet-600/40 text-violet-300 hover:text-violet-200 text-xs font-semibold py-2 px-3 rounded-lg border border-violet-700/50 hover:border-violet-600 transition">
              📄 Report
            </a>`
            : ''
        }
        <button data-action="reuse" data-id="${safeId}"
          aria-label="Reuse campaign ${escAttr(c.campaign_id)}"
          class="flex-1 text-center bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 hover:text-blue-200 text-xs font-semibold py-2 px-3 rounded-lg border border-blue-700/50 hover:border-blue-600 transition">
          ♻ Reuse
        </button>
        <button data-action="delete" data-id="${safeId}"
          aria-label="Delete campaign ${escAttr(c.campaign_id)}"
          class="text-center bg-red-600/10 hover:bg-red-600/30 text-red-400 hover:text-red-300 text-xs font-semibold py-2 px-3 rounded-lg border border-red-800/30 hover:border-red-600 transition">
          🗑
        </button>
      </div>
    </div>
  `;
}

/**
 * Format a campaign ID into a human-readable title.
 * @param {string} id - The campaign ID
 * @returns {string} Title-cased display name
 */
function formatCampaignName(id) {
  return id.replace(/[_-]/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
}

/**
 * Format an ISO date string into a short human-readable date.
 * @param {string} dateStr - ISO date string
 * @returns {string} Formatted date like "Mar 9"
 */
function formatDate(dateStr) {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return dateStr;
  }
}

// ── JSON Editor ──────────────────────────────────────────────────────────────────

/**
 * Pretty-print the JSON in the brief editor textarea.
 */
function formatJson() {
  try {
    const val = document.getElementById('brief-editor').value;
    document.getElementById('brief-editor').value = JSON.stringify(JSON.parse(val), null, 2);
  } catch (e) {
    alert(`Invalid JSON: ${e.message}`);
  }
}

// ── Pipeline Execution ───────────────────────────────────────────────────────────

/**
 * Validate the brief, then stream pipeline execution progress via SSE.
 * @returns {Promise<void>}
 */
async function runPipeline() {
  let brief;

  if (currentMode === 'form') {
    if (!validateForm()) {
      return;
    }
    brief = buildBriefFromForm();
    document.getElementById('brief-editor').value = JSON.stringify(brief, null, 2);
  } else {
    const briefText = document.getElementById('brief-editor').value.trim();
    if (!briefText) {
      alert('Please load or enter a campaign brief.');
      return;
    }
    try {
      brief = JSON.parse(briefText);
    } catch (e) {
      alert(`Invalid JSON in brief: ${e.message}`);
      return;
    }
  }

  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  document.getElementById('run-btn-text').textContent = 'Running…';
  document.getElementById('run-btn-icon').textContent = '⏳';
  document.getElementById('running-indicator').classList.remove('hidden');
  document.getElementById('results-section').classList.add('hidden');
  document.getElementById('summary-card').classList.add('hidden');
  const logEl = document.getElementById('log-container');
  logEl.innerHTML = '';
  allAssets = [];

  appendLog('▶ Starting pipeline…', 'text-violet-400');

  try {
    const response = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(brief),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      const text = decoder.decode(value);
      const lines = text.split('\n').filter((l) => l.startsWith('data: '));
      for (const line of lines) {
        try {
          const payload = JSON.parse(line.slice(6));
          if (payload.type === 'progress') {
            const displayMsg = payload.user_message || payload.message;
            const color = displayMsg.includes('✅')
              ? 'text-green-400'
              : displayMsg.includes('⚠')
                ? 'text-yellow-400'
                : displayMsg.includes('❌') || payload.error_code
                  ? 'text-red-400'
                  : displayMsg.includes('ℹ')
                    ? 'text-blue-400'
                    : 'text-slate-300';
            appendLog(displayMsg, color, payload.error_code || null);
          } else if (payload.type === 'result') {
            handleResult(payload.data);
          } else if (payload.type === 'error') {
            appendErrorBanner(payload.message || 'An unexpected pipeline error occurred.');
          }
        } catch (e) {
          console.warn('Failed to parse SSE payload:', e);
        }
      }
    }
  } catch (e) {
    appendLog(`❌ Network error: ${e.message}`, 'text-red-400');
  } finally {
    btn.disabled = false;
    document.getElementById('run-btn-text').textContent = 'Run Pipeline';
    document.getElementById('run-btn-icon').textContent = '🚀';
    document.getElementById('running-indicator').classList.add('hidden');
    loadCampaigns();
  }
}

/**
 * Append a message to the pipeline log.
 * @param {string} msg - Message text to display
 * @param {string} [color='text-slate-300'] - Tailwind text color class
 * @param {string|null} [errorCode=null] - Optional error reference code
 */
function appendLog(msg, color = 'text-slate-300', errorCode = null) {
  const logEl = document.getElementById('log-container');
  const div = document.createElement('div');
  div.className = `log-item ${color} flex items-start gap-2`;
  const textSpan = document.createElement('span');
  textSpan.textContent = msg;
  div.appendChild(textSpan);
  if (errorCode) {
    const badge = document.createElement('span');
    badge.className =
      'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-red-900/50 text-red-300 border border-red-800/50 whitespace-nowrap flex-shrink-0';
    badge.textContent = errorCode;
    badge.title = 'Error reference code — share with your admin for troubleshooting';
    div.appendChild(badge);
  }
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

/**
 * Append a prominent error banner to the pipeline log for fatal pipeline errors.
 * @param {string} message - Error message to display
 */
function appendErrorBanner(message) {
  const logEl = document.getElementById('log-container');
  const div = document.createElement('div');
  div.className =
    'log-item flex items-start gap-2 mt-1 p-2 rounded bg-red-950/60 border border-red-700/60';
  const icon = document.createElement('span');
  icon.textContent = '❌';
  icon.setAttribute('aria-hidden', 'true');
  icon.className = 'flex-shrink-0';
  const textSpan = document.createElement('span');
  textSpan.className = 'text-red-300 font-medium';
  textSpan.textContent = `Pipeline error: ${message}`;
  div.appendChild(icon);
  div.appendChild(textSpan);
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

// ── Results Rendering ────────────────────────────────────────────────────────────

/**
 * Process the pipeline result and render assets and summary.
 * @param {Object} result - PipelineResult data from the API
 */
function handleResult(result) {
  allAssets = [];
  const grid = document.getElementById('assets-grid');
  grid.innerHTML = '';

  for (const pr of result.product_results) {
    for (const asset of pr.assets) {
      allAssets.push({ asset, product: pr.product });
    }
  }

  renderAssets(allAssets);
  document.getElementById('results-section').classList.remove('hidden');

  const sc = document.getElementById('summary-card');
  sc.classList.remove('hidden');
  const compliant = allAssets.filter(
    (a) => !a.asset.brand_issues || !a.asset.brand_issues.length,
  ).length;
  document.getElementById('summary-content').innerHTML = buildSummaryHTML(result, compliant);
}

/**
 * Build the summary card HTML string.
 * @param {Object} result - PipelineResult data
 * @param {number} compliant - Number of brand-compliant assets
 * @returns {string} HTML string for the summary card body
 */
function buildSummaryHTML(result, compliant) {
  const metrics = result.image_metrics || {};
  const aiImages = metrics.dall_e_images || 0;
  const fallbackImages = metrics.fallback_images || 0;
  const costUsd = metrics.estimated_cost_usd || 0;
  const inputTokens = metrics.input_tokens || 0;
  const outputTokens = metrics.output_tokens || 0;
  const totalTokens = metrics.total_tokens || 0;
  const isFallbackOnly = aiImages === 0;

  const costDisplay = isFallbackOnly
    ? '$0.00 <span class="text-xs font-normal text-slate-500">(fallback mode)</span>'
    : `$${costUsd.toFixed(4)}`;

  const tokenSection = isFallbackOnly
    ? ''
    : `
      <div class="mt-2 pt-2 border-t border-slate-800 grid grid-cols-3 gap-2 text-center">
        <div>
          <div class="text-sm font-semibold text-slate-300">${totalTokens.toLocaleString()}</div>
          <div class="text-xs text-slate-500">Total Tokens</div>
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-400">${inputTokens.toLocaleString()}</div>
          <div class="text-xs text-slate-500">Input</div>
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-400">${outputTokens.toLocaleString()}</div>
          <div class="text-xs text-slate-500">Output</div>
        </div>
      </div>`;

  return `
    <div class="grid grid-cols-2 gap-3 text-center">
      <div class="bg-slate-900 rounded-lg p-3">
        <div class="text-xl font-bold text-violet-300">${result.total_assets}</div>
        <div class="text-xs text-slate-500">Total Assets</div>
      </div>
      <div class="bg-slate-900 rounded-lg p-3">
        <div class="text-xl font-bold text-green-400">${compliant}</div>
        <div class="text-xs text-slate-500">Brand Compliant</div>
      </div>
      <div class="bg-slate-900 rounded-lg p-3">
        <div class="text-xl font-bold text-blue-400">${result.duration_seconds}s</div>
        <div class="text-xs text-slate-500">Pipeline Time</div>
      </div>
      <div class="bg-slate-900 rounded-lg p-3">
        <div class="text-xl font-bold text-yellow-400">${result.product_results.length}</div>
        <div class="text-xs text-slate-500">Products</div>
      </div>
    </div>
    <div class="mt-3 bg-slate-900 rounded-lg p-3">
      <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Image Generation</div>
      <div class="grid grid-cols-3 gap-2 text-center">
        <div>
          <div class="text-lg font-bold text-amber-400">${costDisplay}</div>
          <div class="text-xs text-slate-500">Est. Cost</div>
        </div>
        <div>
          <div class="text-lg font-bold text-green-400">${aiImages}</div>
          <div class="text-xs text-slate-500">AI Images</div>
        </div>
        <div>
          <div class="text-lg font-bold text-slate-400">${fallbackImages}</div>
          <div class="text-xs text-slate-500">Fallback</div>
        </div>
      </div>
      ${tokenSection}
    </div>
    ${result.report_path ? `<a href="/api/report/${escAttr(result.campaign_id)}" target="_blank" rel="noopener noreferrer" class="mt-3 block text-center text-xs text-violet-400 hover:underline">📄 View Full HTML Report →</a>` : ''}
  `;
}

/**
 * Render asset cards into the gallery grid.
 * @param {Array<{asset: Object, product: Object}>} items - Assets to display
 */
function renderAssets(items) {
  const grid = document.getElementById('assets-grid');
  grid.innerHTML = items.map(({ asset, product }) => buildAssetCard(asset, product)).join('');
}

/**
 * Build the HTML string for a single asset card.
 * @param {Object} asset - Asset data
 * @param {Object} product - Product data
 * @returns {string} HTML string for the asset card
 */
function buildAssetCard(asset, product) {
  const brandOk = !asset.brand_issues || !asset.brand_issues.length;
  const contentOk = !asset.content_issues || !asset.content_issues.length;
  const pathSegment = asset.path.split('/outputs/')[1];
  const imgSrc = `/api/outputs/${encodeURIComponent((pathSegment || asset.path).replace(/\\/g, '/'))}`;
  const productName = escAttr(product.name);
  const filename = escAttr(asset.filename);
  const ratio = escAttr(asset.aspect_ratio);

  return `
    <div class="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden hover:border-violet-700 transition" data-ratio="${ratio}">
      <div class="relative bg-slate-950 flex items-center justify-center">
        <img src="${imgSrc}" class="asset-img w-full object-contain max-h-52"
          alt="${productName} creative — ${ratio} aspect ratio"
          loading="lazy"
          onerror="this.parentElement.innerHTML='<div class=\\'h-32 flex items-center justify-center text-slate-600 text-xs\\'>Preview unavailable</div>'">
        <span class="absolute top-2 left-2 bg-black/60 text-xs text-violet-300 px-2 py-0.5 rounded-full font-mono">${ratio}</span>
      </div>
      <div class="p-3">
        <div class="text-xs font-semibold text-slate-300 mb-0.5">${productName}</div>
        <div class="text-xs text-slate-500 mb-2 font-mono truncate">${filename}</div>
        <div class="flex flex-wrap gap-1" role="list" aria-label="Compliance status">
          <span role="listitem" class="text-xs px-2 py-0.5 rounded-full ${brandOk ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}">${brandOk ? '✓ Brand' : '✗ Brand'}</span>
          <span role="listitem" class="text-xs px-2 py-0.5 rounded-full ${contentOk ? 'bg-green-900/50 text-green-400' : 'bg-yellow-900/50 text-yellow-400'}">${contentOk ? '✓ Content' : '⚠ Content'}</span>
        </div>
      </div>
    </div>
  `;
}

// ── Campaign Actions ─────────────────────────────────────────────────────────────

/**
 * Load an existing campaign's brief and populate the form for re-use.
 * @param {string} campaignId - The campaign ID to load
 * @returns {Promise<void>}
 */
async function reuseCampaign(campaignId) {
  try {
    const r = await fetch(`/api/campaigns/${encodeURIComponent(campaignId)}/brief`);
    if (r.status === 404) {
      alert(
        'Brief not available for this campaign. It may have been created before brief saving was enabled.',
      );
      return;
    }
    if (!r.ok) {
      alert('Failed to load campaign brief.');
      return;
    }
    const data = await r.json();
    data.campaign_id = `${data.campaign_id}_v2`;
    populateForm(data);
    document.getElementById('brief-editor').value = JSON.stringify(data, null, 2);
    if (currentMode !== 'form') {
      switchMode('form');
    }
    const briefPanel = document.querySelector('.glass.rounded-xl.p-5.flex-1');
    if (briefPanel) {
      briefPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  } catch (e) {
    alert(`Failed to load campaign brief: ${e.message}`);
  }
}

/**
 * Delete a campaign and its generated assets after user confirmation.
 * @param {string} campaignId - The campaign ID to delete
 * @returns {Promise<void>}
 */
async function deleteCampaign(campaignId) {
  if (
    !confirm(
      `Delete campaign "${campaignId}"? This will permanently remove all generated assets and reports.`,
    )
  ) {
    return;
  }
  try {
    const r = await fetch(`/api/campaigns/${encodeURIComponent(campaignId)}`, {
      method: 'DELETE',
    });
    if (r.status === 204) {
      loadCampaigns();
    } else if (r.status === 404) {
      alert('Campaign not found — it may have already been deleted.');
      loadCampaigns();
    } else {
      alert('Failed to delete campaign.');
    }
  } catch (e) {
    alert(`Failed to delete campaign: ${e.message}`);
  }
}

// ── Configuration Panel ──────────────────────────────────────────────────────────
/** @type {boolean} Whether the config panel is expanded */
let configOpen = false;

/**
 * Toggle the configuration panel open/closed.
 */
function toggleConfig() {
  configOpen = !configOpen;
  document.getElementById('config-panel').classList.toggle('hidden', !configOpen);
  document.getElementById('config-toggle-icon').style.transform = configOpen
    ? 'rotate(180deg)'
    : '';
  if (configOpen) {
    loadConfig();
  }
}

/**
 * Switch between Brand Guidelines and Prohibited Words config tabs.
 * @param {'brand'|'words'} tab - The tab to activate
 */
function switchConfigTab(tab) {
  document.getElementById('cfg-brand').classList.toggle('hidden', tab !== 'brand');
  document.getElementById('cfg-words').classList.toggle('hidden', tab !== 'words');
  document.getElementById('cfg-tab-brand').classList.toggle('active', tab === 'brand');
  document.getElementById('cfg-tab-words').classList.toggle('active', tab === 'words');
  document.getElementById('cfg-tab-brand').classList.toggle('text-slate-400', tab !== 'brand');
  document.getElementById('cfg-tab-words').classList.toggle('text-slate-400', tab !== 'words');
}

/**
 * Convert an RGB array to a hex color string.
 * @param {number[]} rgb - [r, g, b] values (0–255)
 * @returns {string} Hex color string like "#a1b2c3"
 */
function rgbToHex(rgb) {
  return '#' + rgb.map((v) => v.toString(16).padStart(2, '0')).join('');
}

/**
 * Convert a hex color string to an RGB array.
 * @param {string} hex - Hex color string like "#a1b2c3"
 * @returns {number[]} [r, g, b] values (0–255)
 */
function hexToRgb(hex) {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

/**
 * Set a color input and its accompanying RGB display span.
 * @param {string} id - ID of the color input element
 * @param {string} rgbId - ID of the span showing RGB values
 * @param {number[]} rgb - [r, g, b] values
 */
function setColorField(id, rgbId, rgb) {
  document.getElementById(id).value = rgbToHex(rgb);
  document.getElementById(rgbId).textContent = `[${rgb.join(', ')}]`;
}

/**
 * Update the RGB display span when a color input changes.
 * @param {HTMLInputElement} input - The color input that changed
 * @param {string} rgbId - ID of the span to update
 */
function syncColorDisplay(input, rgbId) {
  const rgb = hexToRgb(input.value);
  document.getElementById(rgbId).textContent = `[${rgb.join(', ')}]`;
}

/**
 * Fetch and populate the configuration panel with current values.
 * @returns {Promise<void>}
 */
async function loadConfig() {
  try {
    const profileName = document.getElementById('cfg-profile-select').value;
    const bgUrl = profileName
      ? `/api/config/brand-guidelines/${profileName}`
      : '/api/config/brand-guidelines';
    const pwUrl = profileName
      ? `/api/config/prohibited-words/${profileName}`
      : '/api/config/prohibited-words';

    const [bgRes, pwRes, profRes] = await Promise.all([
      fetch(bgUrl),
      fetch(pwUrl),
      fetch('/api/config/profiles'),
    ]);

    if (bgRes.ok) {
      const bg = await bgRes.json();
      document.getElementById('cfg-brand-name').value = bg.brand_name || '';
      document.getElementById('cfg-font-family').value = bg.font_family || '';
      setColorField('cfg-primary-color', 'cfg-primary-rgb', bg.primary_color || [0, 0, 0]);
      setColorField('cfg-secondary-color', 'cfg-secondary-rgb', bg.secondary_color || [0, 0, 0]);
      setColorField('cfg-text-color', 'cfg-text-rgb', bg.text_color || [255, 255, 255]);
      setColorField('cfg-accent-color', 'cfg-accent-rgb', bg.accent_color || [0, 0, 0]);
      document.getElementById('cfg-logo-placement').value = bg.logo_placement || 'bottom-right';
      document.getElementById('cfg-safe-zone').value = bg.safe_zone_percent ?? 5;
      document.getElementById('cfg-notes').value = bg.notes || '';
    }

    if (pwRes.ok) {
      const pw = await pwRes.json();
      renderWordList('prohibited', pw.prohibited || []);
      renderWordList('disclaimer', pw.requires_disclaimer || []);
      renderSuperlatives(pw.superlatives || []);
    }

    if (profRes.ok) {
      const profData = await profRes.json();
      const select = document.getElementById('cfg-profile-select');
      const current = select.value;
      const allProfiles = new Set([
        ...(profData.profiles['brand-guidelines'] || []),
        ...(profData.profiles['prohibited-words'] || []),
      ]);
      select.innerHTML =
        '<option value="">Default</option>' +
        [...allProfiles]
          .sort()
          .map((n) => `<option value="${n}" ${n === current ? 'selected' : ''}>${n}</option>`)
          .join('');
    }
  } catch (e) {
    console.error('Failed to load config:', e);
    showUserError('Failed to load configuration. Please try again.');
  }
}

/**
 * Re-load config when the profile selector changes.
 */
function loadConfigProfile() {
  loadConfig();
}

/**
 * Build brand guidelines JSON from the config form.
 * @returns {Object} Brand guidelines data object
 */
function buildBrandGuidelinesJson() {
  return {
    brand_name: document.getElementById('cfg-brand-name').value.trim(),
    primary_color: hexToRgb(document.getElementById('cfg-primary-color').value),
    secondary_color: hexToRgb(document.getElementById('cfg-secondary-color').value),
    text_color: hexToRgb(document.getElementById('cfg-text-color').value),
    accent_color: hexToRgb(document.getElementById('cfg-accent-color').value),
    font_family: document.getElementById('cfg-font-family').value.trim(),
    logo_placement: document.getElementById('cfg-logo-placement').value,
    safe_zone_percent: parseInt(document.getElementById('cfg-safe-zone').value) || 5,
    notes: document.getElementById('cfg-notes').value.trim(),
  };
}

/**
 * Build prohibited words JSON from the config form.
 * @returns {Object} Prohibited words data object
 */
function buildProhibitedWordsJson() {
  const prohibited = [];
  document.querySelectorAll('#cfg-prohibited-list .word-entry').forEach((el) => {
    const word = el.querySelector('.we-word').value.trim();
    const reason = el.querySelector('.we-reason').value.trim();
    if (word) {
      prohibited.push({ word, reason });
    }
  });
  const requires_disclaimer = [];
  document.querySelectorAll('#cfg-disclaimer-list .word-entry').forEach((el) => {
    const word = el.querySelector('.we-word').value.trim();
    const reason = el.querySelector('.we-reason').value.trim();
    if (word) {
      requires_disclaimer.push({ word, reason });
    }
  });
  const superlatives = [];
  document.querySelectorAll('#cfg-superlatives-list .sup-tag').forEach((el) => {
    if (el.dataset.word) {
      superlatives.push(el.dataset.word);
    }
  });
  return { prohibited, requires_disclaimer, superlatives };
}

/**
 * Save the current config panel values to the default (or selected profile).
 * @returns {Promise<void>}
 */
async function saveConfig() {
  const profileName = document.getElementById('cfg-profile-select').value;
  const bgUrl = profileName
    ? `/api/config/brand-guidelines/${profileName}`
    : '/api/config/brand-guidelines';
  const pwUrl = profileName
    ? `/api/config/prohibited-words/${profileName}`
    : '/api/config/prohibited-words';
  try {
    const [bgRes, pwRes] = await Promise.all([
      fetch(bgUrl, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildBrandGuidelinesJson()),
      }),
      fetch(pwUrl, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildProhibitedWordsJson()),
      }),
    ]);
    if (!bgRes.ok) {
      const e = await bgRes.json();
      alert(`Brand guidelines error: ${e.detail || 'Save failed'}`);
      return;
    }
    if (!pwRes.ok) {
      const e = await pwRes.json();
      alert(`Prohibited words error: ${e.detail || 'Save failed'}`);
      return;
    }
    alert('Configuration saved!');
  } catch (e) {
    alert(`Save failed: ${e.message}`);
  }
}

/**
 * Prompt for a new profile name and save the current config under that name.
 * @returns {Promise<void>}
 */
async function saveConfigAs() {
  const name = prompt('Enter profile name (alphanumeric and underscores only):');
  if (!name) {
    return;
  }
  if (!/^[a-zA-Z0-9_]+$/.test(name)) {
    alert('Invalid name. Use only letters, numbers, and underscores.');
    return;
  }
  try {
    const [bgRes, pwRes] = await Promise.all([
      fetch(`/api/config/brand-guidelines/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildBrandGuidelinesJson()),
      }),
      fetch(`/api/config/prohibited-words/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildProhibitedWordsJson()),
      }),
    ]);
    if (!bgRes.ok) {
      const e = await bgRes.json();
      alert(`Brand guidelines error: ${e.detail || 'Save failed'}`);
      return;
    }
    if (!pwRes.ok) {
      const e = await pwRes.json();
      alert(`Prohibited words error: ${e.detail || 'Save failed'}`);
      return;
    }
    alert(`Profile "${name}" saved!`);
    loadConfig();
  } catch (e) {
    alert(`Save failed: ${e.message}`);
  }
}

/**
 * Reset config to defaults by clearing the profile selector and reloading.
 * @returns {Promise<void>}
 */
async function resetConfig() {
  if (
    !confirm('Reset configuration to shipped defaults? This will reload the default config files.')
  ) {
    return;
  }
  document.getElementById('cfg-profile-select').value = '';
  loadConfig();
}

// ── Word List Rendering ──────────────────────────────────────────────────────────

/**
 * Render a word list (prohibited or disclaimer) in the config panel.
 * @param {'prohibited'|'disclaimer'} type - Which list to render
 * @param {Array<{word: string, reason: string}>} items - Word entries to display
 */
function renderWordList(type, items) {
  const listId = type === 'prohibited' ? 'cfg-prohibited-list' : 'cfg-disclaimer-list';
  const container = document.getElementById(listId);
  container.innerHTML = '';
  items.forEach((item) => {
    container.appendChild(buildWordEntry(item.word, item.reason));
  });
}

/**
 * Build a word entry row element.
 * @param {string} [word=''] - The word value
 * @param {string} [reason=''] - The reason value
 * @returns {HTMLDivElement} Word entry row element
 */
function buildWordEntry(word = '', reason = '') {
  const div = document.createElement('div');
  div.className = 'word-entry flex items-center gap-2';

  const wordInput = document.createElement('input');
  wordInput.type = 'text';
  wordInput.className = 'form-input flex-1 we-word';
  wordInput.value = word;
  wordInput.placeholder = 'Word';
  wordInput.setAttribute('aria-label', 'Word');

  const reasonInput = document.createElement('input');
  reasonInput.type = 'text';
  reasonInput.className = 'form-input flex-1 we-reason';
  reasonInput.value = reason;
  reasonInput.placeholder = 'Reason';
  reasonInput.setAttribute('aria-label', 'Reason');

  const removeBtn = document.createElement('button');
  removeBtn.className = 'text-red-400 hover:text-red-300 text-xs px-1';
  removeBtn.textContent = '✕';
  removeBtn.setAttribute('aria-label', 'Remove word');
  removeBtn.addEventListener('click', () => div.remove());

  div.appendChild(wordInput);
  div.appendChild(reasonInput);
  div.appendChild(removeBtn);
  return div;
}

/**
 * Add a blank word entry to the specified list.
 * @param {'prohibited'|'disclaimer'} type - Which list to add to
 */
function addWordEntry(type) {
  const listId = type === 'prohibited' ? 'cfg-prohibited-list' : 'cfg-disclaimer-list';
  const container = document.getElementById(listId);
  container.appendChild(buildWordEntry());
}

/**
 * Render the superlatives tag list in the config panel.
 * @param {string[]} words - Superlative words to display
 */
function renderSuperlatives(words) {
  const container = document.getElementById('cfg-superlatives-list');
  container.innerHTML = '';
  words.forEach((w) => {
    container.appendChild(buildSuperlativeTag(w));
  });
}

/**
 * Build a superlative tag element.
 * @param {string} word - The superlative word
 * @returns {HTMLSpanElement} Superlative tag element
 */
function buildSuperlativeTag(word) {
  const span = document.createElement('span');
  span.className =
    'sup-tag inline-flex items-center gap-1 bg-slate-800 text-slate-300 text-xs px-2 py-1 rounded-full border border-slate-700';
  span.dataset.word = word;

  const text = document.createTextNode(word + ' ');
  const removeBtn = document.createElement('button');
  removeBtn.className = 'text-red-400 hover:text-red-300';
  removeBtn.textContent = '✕';
  removeBtn.setAttribute('aria-label', `Remove superlative: ${word}`);
  removeBtn.addEventListener('click', () => span.remove());

  span.appendChild(text);
  span.appendChild(removeBtn);
  return span;
}

/**
 * Prompt for a new superlative word and add it to the list.
 */
function addSuperlative() {
  const word = prompt('Enter superlative word:');
  if (!word || !word.trim()) {
    return;
  }
  const container = document.getElementById('cfg-superlatives-list');
  container.appendChild(buildSuperlativeTag(word.trim()));
}

// ── Asset Filtering ──────────────────────────────────────────────────────────────

/**
 * Filter the asset gallery by aspect ratio.
 * @param {string} ratio - The ratio to filter by, or 'all'
 * @param {HTMLButtonElement} btn - The tab button that was clicked
 */
function filterRatio(ratio, btn) {
  document.querySelectorAll('.tab-btn').forEach((b) => {
    b.classList.remove('active');
    b.classList.add('text-slate-400');
    b.style.borderColor = '';
  });
  btn.classList.add('active');
  const filtered =
    ratio === 'all' ? allAssets : allAssets.filter((a) => a.asset.aspect_ratio === ratio);
  renderAssets(filtered);
}

// ── Event Wiring ─────────────────────────────────────────────────────────────────

/**
 * Wire up all DOM event listeners once the document is ready.
 * Kept separate from init() so all element references are guaranteed to exist.
 */
document.addEventListener('DOMContentLoaded', function () {
  // Mode switching
  document.getElementById('mode-form-btn').addEventListener('click', function () {
    switchMode('form');
  });
  document.getElementById('mode-json-btn').addEventListener('click', function () {
    switchMode('json');
  });

  // Run pipeline
  document.getElementById('run-btn').addEventListener('click', runPipeline);

  // JSON format button
  document.getElementById('format-json-btn').addEventListener('click', formatJson);

  // Logo mode radios
  document.querySelectorAll('input[name="logo-mode"]').forEach(function (radio) {
    radio.addEventListener('change', function () {
      setLogoMode(radio.value);
    });
  });

  // Logo file upload
  document.getElementById('logo-file-input').addEventListener('change', function () {
    handleLogoUpload(this);
  });

  // Add product button
  document.getElementById('add-product-btn').addEventListener('click', function () {
    addProduct();
  });

  // Refresh campaigns
  document.getElementById('refresh-campaigns-btn').addEventListener('click', loadCampaigns);

  // Configuration toggle
  document.getElementById('config-toggle-btn').addEventListener('click', function () {
    toggleConfig();
    this.setAttribute('aria-expanded', String(configOpen));
  });

  // Config tabs
  document.getElementById('cfg-tab-brand').addEventListener('click', function () {
    switchConfigTab('brand');
  });
  document.getElementById('cfg-tab-words').addEventListener('click', function () {
    switchConfigTab('words');
  });

  // Config profile selector
  document.getElementById('cfg-profile-select').addEventListener('change', loadConfigProfile);

  // Config action buttons
  document.getElementById('cfg-save-btn').addEventListener('click', saveConfig);
  document.getElementById('cfg-save-as-btn').addEventListener('click', saveConfigAs);
  document.getElementById('cfg-reset-btn').addEventListener('click', resetConfig);

  // Word list buttons
  document.getElementById('add-prohibited-btn').addEventListener('click', function () {
    addWordEntry('prohibited');
  });
  document.getElementById('add-disclaimer-btn').addEventListener('click', function () {
    addWordEntry('disclaimer');
  });
  document.getElementById('add-superlative-btn').addEventListener('click', addSuperlative);

  // Color pickers
  document.getElementById('cfg-primary-color').addEventListener('change', function () {
    syncColorDisplay(this, 'cfg-primary-rgb');
  });
  document.getElementById('cfg-secondary-color').addEventListener('change', function () {
    syncColorDisplay(this, 'cfg-secondary-rgb');
  });
  document.getElementById('cfg-text-color').addEventListener('change', function () {
    syncColorDisplay(this, 'cfg-text-rgb');
  });
  document.getElementById('cfg-accent-color').addEventListener('change', function () {
    syncColorDisplay(this, 'cfg-accent-rgb');
  });

  // Ratio filter tabs
  document.querySelectorAll('.tab-btn[data-ratio]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      filterRatio(btn.dataset.ratio, btn);
    });
  });
});
