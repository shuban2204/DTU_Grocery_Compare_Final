let quantity = 1;
const $ = (selector) => document.querySelector(selector);
const money = (value) => value == null ? '—' : `₹${Number(value).toFixed(2).replace(/\.00$/, '')}`;
const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));

function updateQuantity(next) { quantity = Math.max(1, Math.min(10, next)); $('#quantity').textContent = quantity; }
function checkedAt(iso) { return iso ? `checked ${new Date(iso).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}` : ''; }
function providerStates(providers) {
  $('#provider-status').innerHTML = Object.entries(providers).map(([name, state]) => {
    let label;
    if (state.data_source === 'manual_snapshot') {
      label = state.captured_at ? `SNAPSHOT · captured ${new Date(state.captured_at).toLocaleString()} · live automated retrieval unavailable` : 'SNAPSHOT UNAVAILABLE · live automated retrieval unavailable';
    } else if (state.data_source === 'cached_live') {
      label = `CACHED LIVE · ${checkedAt(state.fetched_at)}`;
    } else if (state.data_source === 'live' || state.data_source === 'live_api') {
      label = `LIVE · ${checkedAt(state.fetched_at)}`;
    } else {
      label = 'TEMPORARILY UNAVAILABLE';
    }
    return `<span class="status ${escapeHtml(state.status)}"><strong>${escapeHtml(name === 'blinkit' ? 'Blinkit' : 'Instamart')}:</strong> ${label}</span>`;
  }).join('');
}
function platform(name, listing, comparable) {
  const unit = listing.unit_price ? `${money(listing.unit_price.amount)} ${escapeHtml(listing.unit_price.suffix)}` : 'Unit price unavailable';
  return `<div class="platform"><strong>${name}</strong><div class="muted">${escapeHtml(listing.title)}</div><div class="muted">${escapeHtml(listing.size_text || 'Size unavailable')} · ${listing.availability === 'unavailable' ? 'Unavailable' : money(listing.price)}</div><div class="price">${comparable ? unit : `Qty ${quantity}: ${money(listing.quantity_total)}`}</div></div>`;
}
function formatReasons(reasons = []) {
  const map = {
    'different size or pack structure': 'Different pack size or packaging',
    'one or both sizes unknown; treated as comparable': 'Pack size unspecified on one or both listings',
    'same product family': 'Same product family',
    'strong title similarity': 'Similar product title',
    'same parsed size and pack structure': 'Same pack size and structure',
  };
  const filtered = reasons
    .filter((r) => r !== 'same product family' || reasons.length === 1)
    .map((r) => map[r] || (r.charAt(0).toUpperCase() + r.slice(1)));
  return filtered.join(' · ');
}

function matchCard(match) {
  const comparable = match.relationship === 'comparable';
  const pricing = match.pricing || {};
  let winner = '';
  if (pricing.winner === 'tie') winner = comparable ? 'Same normalized unit price.' : 'Same visible item subtotal.';
  if (pricing.winner === 'blinkit') winner = comparable ? 'Blinkit has the lower normalized unit price.' : `Blinkit is cheaper by ${money(pricing.savings)}.`;
  if (pricing.winner === 'instamart') winner = comparable ? 'Instamart has the lower normalized unit price.' : `Instamart is cheaper by ${money(pricing.savings)}.`;
  const reasonLine = (comparable && match.reasons && match.reasons.length)
    ? `<div class="match-reasons muted">${escapeHtml(formatReasons(match.reasons))}</div>`
    : '';
  return `<article class="match"><span class="badge ${comparable ? 'comparable' : ''}">${comparable ? 'Comparable product' : 'Exact match'}</span>${reasonLine}<h2>${escapeHtml(match.blinkit.title)}</h2><div class="columns">${platform('Blinkit', match.blinkit, comparable)}${platform('Instamart', match.instamart, comparable)}</div>${winner ? `<p class="winner">${winner}</p>` : ''}</article>`;
}
function other(name, listings) {
  if (!listings.length) return '';
  return `<details><summary>Other ${name} results (${listings.length})</summary>${listings.map((item) => `<div class="other"><strong>${escapeHtml(item.title)}</strong><br><span class="muted">${escapeHtml(item.size_text || 'Size unavailable')} · ${money(item.price)}</span></div>`).join('')}</details>`;
}
async function run(refresh = false) {
  const form = $('#search-form'); const query = $('#query').value.trim();
  if (query.length < 2) return;
  form.querySelectorAll('button').forEach((button) => button.disabled = true);
  $('#message').textContent = 'Comparing visible listings…';
  try {
    const params = new URLSearchParams({q: query, quantity: String(quantity), refresh: String(refresh)});
    const response = await fetch(`/api/search?${params}`);
    if (!response.ok) throw new Error('Search request failed');
    const data = await response.json();
    providerStates(data.providers);
    $('#results').innerHTML = data.matches.length ? data.matches.map(matchCard).join('') : '';
    $('#other-results').innerHTML = other('Blinkit', data.unmatched.blinkit) + other('Instamart', data.unmatched.instamart);
    const failed = Object.values(data.providers).filter((item) => !['ok', 'stale'].includes(item.status));
    $('#message').textContent = data.matches.length ? data.scope_note : (failed.length === 2 ? 'Could not fetch live listings right now. Please retry.' : 'No conservative cross-platform matches found; other results are shown below.');
    $('#refresh').hidden = false;
  } catch (error) { $('#message').textContent = 'Could not fetch live listings right now. Please retry.'; }
  finally { form.querySelectorAll('button').forEach((button) => button.disabled = false); }
}
$('#decrease').addEventListener('click', () => updateQuantity(quantity - 1));
$('#increase').addEventListener('click', () => updateQuantity(quantity + 1));
$('#search-form').addEventListener('submit', (event) => { event.preventDefault(); run(false); });
$('#refresh').addEventListener('click', () => run(true));
