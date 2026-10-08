// Return ACH Test Engine - Interactive Frontend Dashboard
let appState = {
  currentReport: null,
  contractData: null,
  allResults: [],
  filteredResults: [],
  selectedResult: null,
  activeTab: 'results',
  statusFilter: 'all',
  categoryFilter: 'all',
  searchQuery: '',
};

document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  loadReportHistory();
});

function setupEventListeners() {
  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const targetTab = e.target.getAttribute('data-tab');
      switchTab(targetTab);
    });
  });

  // Action buttons
  document.getElementById('btn-discover').addEventListener('click', discoverApi);
  document.getElementById('btn-run').addEventListener('click', runTests);
  document.getElementById('btn-export-json').addEventListener('click', () => downloadReport('json'));
  document.getElementById('btn-export-md').addEventListener('click', () => downloadReport('md'));
  document.getElementById('btn-export-html').addEventListener('click', () => downloadReport('html'));

  // Filters
  document.getElementById('filter-status').addEventListener('change', (e) => {
    appState.statusFilter = e.target.value;
    applyFilters();
  });
  document.getElementById('filter-category').addEventListener('change', (e) => {
    appState.categoryFilter = e.target.value;
    applyFilters();
  });
  document.getElementById('search-input').addEventListener('input', (e) => {
    appState.searchQuery = e.target.value.toLowerCase();
    applyFilters();
  });

  // Modal close
  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.getElementById('modal-overlay').addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') closeModal();
  });
}

function switchTab(tabId) {
  appState.activeTab = tabId;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
  });
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.style.display = pane.id === `tab-${tabId}` ? 'block' : 'none';
  });

  if (tabId === 'history') {
    loadReportHistory();
  }
}

function getSelectedSuites() {
  const checkboxes = document.querySelectorAll('input[name="suite"]:checked');
  return Array.from(checkboxes).map(cb => cb.value);
}

// 1. API Discovery
async function discoverApi() {
  const targetUrl = document.getElementById('target-url').value.trim();
  const btn = document.getElementById('btn-discover');
  btn.disabled = true;
  btn.innerText = 'Inspecting...';

  try {
    const res = await fetch('/api/discover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_url: targetUrl })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.innerText = 'Discover API';

    if (!data.is_reachable) {
      alert(`Target unreachable: ${data.error_message}`);
      return;
    }

    appState.contractData = data.contract;
    renderContractTable(data.contract);
    switchTab('contracts');
  } catch (err) {
    btn.disabled = false;
    btn.innerText = 'Discover API';
    alert(`Discovery error: ${err.message}`);
  }
}

function renderContractTable(contract) {
  const tbody = document.getElementById('contracts-tbody');
  tbody.innerHTML = '';

  if (!contract || !contract.endpoints || contract.endpoints.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">No endpoints discovered.</td></tr>';
    return;
  }

  document.getElementById('contract-title').innerText = `${contract.title} v${contract.version}`;

  contract.endpoints.forEach(ep => {
    const tr = document.createElement('tr');
    const authText = ep.requires_auth ? '<span class="badge badge-error">X-User-Id</span>' : '<span style="color:var(--text-muted);">-</span>';
    const paramsText = ep.parameters.length > 0 ? `${ep.parameters.length} params` : '-';
    const fieldsText = ep.field_rules.length > 0 ? `${ep.field_rules.length} field rules` : (ep.request_schema ? 'JSON Body' : '-');

    tr.innerHTML = `
      <td><span class="badge badge-method">${ep.method}</span></td>
      <td><code>${escapeHtml(ep.path)}</code></td>
      <td>${authText}</td>
      <td>${paramsText}</td>
      <td>${fieldsText}</td>
    `;
    tbody.appendChild(tr);
  });
}

// 2. Run Tests
async function runTests() {
  const targetUrl = document.getElementById('target-url').value.trim();
  const mode = document.getElementById('execution-mode').value;
  const suites = getSelectedSuites();
  const concurrency = parseInt(document.getElementById('concurrency').value, 10);
  const timeout = parseFloat(document.getElementById('timeout').value);

  const btn = document.getElementById('btn-run');
  btn.disabled = true;
  btn.innerHTML = '<span class="pulse-dot"></span> Running Tests...';

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_url: targetUrl,
        execution_mode: mode,
        suites: suites,
        max_concurrency: concurrency,
        timeout_seconds: timeout
      })
    });

    const data = await res.json();
    btn.disabled = false;
    btn.innerHTML = '▶ Run Test Engine';

    if (data.report) {
      appState.currentReport = data.report;
      appState.allResults = data.report.results || [];
      renderReportSummary(data.report.summary);
      populateCategoryFilter(data.report.results);
      applyFilters();
      renderLiveLogs(data.report.results);
      renderConnectorsTab(mode);
      switchTab('results');
    }
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = '▶ Run Test Engine';
    alert(`Execution failed: ${err.message}`);
  }
}

function renderReportSummary(summary) {
  if (!summary) return;
  document.getElementById('kpi-total').innerText = summary.total_tests;
  document.getElementById('kpi-passed').innerText = summary.passed;
  document.getElementById('kpi-failed').innerText = summary.failed;
  document.getElementById('kpi-pass-rate').innerText = `${summary.pass_rate_pct}%`;
  document.getElementById('kpi-duration').innerText = `${Math.round(summary.total_duration_ms)} ms`;

  const banner = document.getElementById('status-banner');
  if (summary.has_failures) {
    banner.className = 'badge badge-fail';
    banner.innerText = 'FAILED';
  } else {
    banner.className = 'badge badge-pass';
    banner.innerText = 'PASSED';
  }
}

function populateCategoryFilter(results) {
  const select = document.getElementById('filter-category');
  const categories = new Set(results.map(r => r.category));
  select.innerHTML = '<option value="all">All Categories</option>';
  categories.forEach(cat => {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.innerText = cat.toUpperCase();
    select.appendChild(opt);
  });
}

function applyFilters() {
  let filtered = [...appState.allResults];

  if (appState.statusFilter !== 'all') {
    filtered = filtered.filter(r => r.status.toLowerCase() === appState.statusFilter);
  }

  if (appState.categoryFilter !== 'all') {
    filtered = filtered.filter(r => r.category === appState.categoryFilter);
  }

  if (appState.searchQuery) {
    filtered = filtered.filter(r =>
      r.test_id.toLowerCase().includes(appState.searchQuery) ||
      r.name.toLowerCase().includes(appState.searchQuery)
    );
  }

  appState.filteredResults = filtered;
  renderResultsTable(filtered);
}

function renderResultsTable(results) {
  const tbody = document.getElementById('results-tbody');
  tbody.innerHTML = '';

  if (results.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);">No matching test cases.</td></tr>';
    return;
  }

  results.forEach(r => {
    const tr = document.createElement('tr');
    const badgeClass = r.status === 'PASS' ? 'badge-pass' : (r.status === 'ERROR' ? 'badge-error' : 'badge-fail');

    tr.innerHTML = `
      <td><span class="badge ${badgeClass}">${r.status}</span></td>
      <td><code>${escapeHtml(r.test_id)}</code></td>
      <td>${escapeHtml(r.name)}</td>
      <td><span class="badge badge-method">${escapeHtml(r.category)}</span></td>
      <td>${r.http_status_code || '-'}</td>
      <td>${r.execution_time_ms.toFixed(1)}ms</td>
      <td><button class="btn btn-secondary btn-sm" onclick="openInspector('${r.test_id}')">Inspect</button></td>
    `;
    tbody.appendChild(tr);
  });
}

function openInspector(testId) {
  const item = appState.allResults.find(r => r.test_id === testId);
  if (!item) return;

  appState.selectedResult = item;
  document.getElementById('modal-title').innerText = `${item.name} (${item.test_id})`;

  const modalContent = document.getElementById('modal-content');
  const badgeClass = item.status === 'PASS' ? 'badge-pass' : (item.status === 'ERROR' ? 'badge-error' : 'badge-fail');

  let diffSection = '';
  if (item.diff_summary) {
    diffSection = `
      <div class="config-group">
        <label class="config-label" style="color:var(--color-fail);">Validation Differences & Diagnostics</label>
        <pre class="code-block" style="color:var(--color-fail);">${escapeHtml(item.diff_summary)}</pre>
      </div>
    `;
  }

  modalContent.innerHTML = `
    <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;">
      <span class="badge ${badgeClass}">${item.status}</span>
      <span style="color:var(--text-muted);font-size:13px;">HTTP ${item.http_status_code || '-'} | Latency: ${item.execution_time_ms.toFixed(1)}ms</span>
    </div>
    <div style="color:var(--text-muted);font-size:14px;margin-bottom:16px;">${escapeHtml(item.description)}</div>

    ${diffSection}

    <div class="config-group">
      <label class="config-label">Request (${item.request_method} ${escapeHtml(item.request_url)})</label>
      <pre class="code-block">${escapeHtml(JSON.stringify(item.request_body || {}, null, 2))}</pre>
    </div>

    <div class="config-group">
      <label class="config-label">Response Body</label>
      <pre class="code-block">${escapeHtml(JSON.stringify(item.response_body || item.response_raw_text || {}, null, 2))}</pre>
    </div>

    <div class="config-group">
      <label class="config-label">Execution Trace Logs</label>
      <pre class="code-block" style="color:var(--text-muted);">${escapeHtml(item.logs || 'No logs captured.')}</pre>
    </div>
  `;

  document.getElementById('modal-overlay').classList.add('active');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('active');
}

function renderLiveLogs(results) {
  const container = document.getElementById('logs-container');
  const allLogs = results.map(r => `=== [${r.status}] ${r.test_id} ===\n${r.logs}`).join('\n\n');
  container.innerText = allLogs || 'No execution logs available.';
}

function renderConnectorsTab(mode) {
  const container = document.getElementById('connectors-content');
  const isReal = mode === 'real';

  container.innerHTML = `
    <div class="kpis-grid" style="margin-bottom:20px;">
      <div class="kpi-card">
        <div class="kpi-title">Active Mode</div>
        <div class="kpi-value val-blue">${isReal ? 'REAL' : 'MOCK'}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Payment Connector</div>
        <div class="kpi-value val-pass">ACTIVE</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Servicing Connector</div>
        <div class="kpi-value val-pass">ACTIVE</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">CRM Connector</div>
        <div class="kpi-value val-pass">ACTIVE</div>
      </div>
    </div>
    <div class="table-container">
      <table class="data-table">
        <thead>
          <tr>
            <th>System</th>
            <th>Type</th>
            <th>Operations Tested</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Payment</strong></td>
            <td><code>payment_connector</code></td>
            <td>get_return_event, get_original_entry, list_reinitiations</td>
            <td><span class="badge badge-pass">HEALTHY</span></td>
          </tr>
          <tr>
            <td><strong>Servicing</strong></td>
            <td><code>servicing_connector</code></td>
            <td>get_account, list_returns, get_flags</td>
            <td><span class="badge badge-pass">HEALTHY</span></td>
          </tr>
          <tr>
            <td><strong>CRM</strong></td>
            <td><code>crm_connector</code></td>
            <td>get_contact, list_interactions</td>
            <td><span class="badge badge-pass">HEALTHY</span></td>
          </tr>
          <tr>
            <td><strong>Risk</strong></td>
            <td><code>risk_connector</code></td>
            <td>get_risk_profile</td>
            <td><span class="badge badge-pass">HEALTHY</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  `;
}

async function loadReportHistory() {
  try {
    const res = await fetch('/api/reports');
    const reports = await res.json();
    const tbody = document.getElementById('history-tbody');
    tbody.innerHTML = '';

    if (!reports || reports.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:32px;">No saved reports found.</td></tr>';
      return;
    }

    reports.forEach(rep => {
      const tr = document.createElement('tr');
      const passRate = rep.pass_rate_pct != null ? `${rep.pass_rate_pct}%` : '-';
      const mdFilename = rep.md_filename || rep.filename.replace('.json', '.md');
      tr.innerHTML = `
        <td><code>${escapeHtml(rep.filename)}</code></td>
        <td>${escapeHtml(rep.target_url || '-')}</td>
        <td>${rep.total_tests || 0}</td>
        <td><span style="color:var(--color-pass); font-weight:600;">${rep.passed || 0}</span></td>
        <td><span style="color:var(--color-fail); font-weight:600;">${rep.failed || 0}</span></td>
        <td>${passRate}</td>
        <td>
          <div style="display:flex; gap:6px; align-items:center;">
            <a href="/api/reports/${encodeURIComponent(rep.filename)}?download=true" download="${escapeHtml(rep.filename)}" class="btn btn-secondary btn-sm" title="Download JSON file">⬇ JSON</a>
            <a href="/api/reports/${encodeURIComponent(mdFilename)}?download=true" download="${escapeHtml(mdFilename)}" class="btn btn-secondary btn-sm" title="Download Markdown (.md) file">⬇ MD</a>
            <button class="btn btn-primary btn-sm" onclick="loadReportFromHistory('${escapeHtml(rep.filename)}')" title="Load into dashboard">👁 Load</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to load history:', err);
  }
}

async function loadReportFromHistory(filename) {
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error(`Report not found (${res.status})`);
    const data = await res.json();
    appState.currentReport = data;
    appState.allResults = data.results || [];
    renderReportSummary(data.summary);
    populateCategoryFilter(data.results || []);
    applyFilters();
    renderLiveLogs(data.results || []);
    switchTab('results');
  } catch (err) {
    alert(`Failed to load report: ${err.message}`);
  }
}

async function downloadReport(format) {
  if (!appState.currentReport) {
    alert('Please execute a test run or load a report first before downloading.');
    return;
  }

  const filename = format === 'md' ? 'report.md' : (format === 'html' ? 'report.html' : 'report.json');

  try {
    // Attempt downloading directly from server endpoint
    const res = await fetch(`/api/reports/${filename}?download=true`);
    if (res.ok) {
      const blob = await res.blob();
      triggerBlobDownload(blob, filename);
      return;
    }
  } catch (e) {
    console.warn('Direct server fetch failed, generating client-side file:', e);
  }

  // Fallback client-side generation
  exportFileClientSide(format);
}

function exportFileClientSide(format) {
  const report = appState.currentReport;
  if (!report) return;

  let filename = `report.${format}`;
  let content = '';
  let mimeType = 'text/plain';

  if (format === 'json') {
    content = JSON.stringify(report, null, 2);
    mimeType = 'application/json';
  } else if (format === 'md') {
    content = generateMarkdownReport(report);
    mimeType = 'text/markdown';
  } else if (format === 'html') {
    content = generateHtmlReport(report);
    mimeType = 'text/html';
  }

  const blob = new Blob([content], { type: mimeType });
  triggerBlobDownload(blob, filename);
}

function generateMarkdownReport(report) {
  const summary = report.summary || {};
  const statusBadge = summary.has_failures ? '❌ FAILED' : '✅ PASSED';
  const duration = summary.total_duration_ms ? summary.total_duration_ms.toFixed(1) : '0.0';

  let lines = [
    '# Return ACH Test Engine Report',
    '',
    `**Overall Status:** ${statusBadge}  `,
    `**Target URL:** \`${summary.target_url || '-'}\`  `,
    `**Execution Mode:** \`${summary.execution_mode || 'mock'}\`  `,
    `**Pass Rate:** ${summary.pass_rate_pct || 0}%  `,
    `**Total Duration:** ${duration} ms  `,
    '',
    '## Summary Metrics',
    '',
    '| Metric | Value |',
    '|---|---|',
    `| Total Tests | ${summary.total_tests || 0} |`,
    `| Passed | ${summary.passed || 0} |`,
    `| Failed | ${summary.failed || 0} |`,
    `| Errors | ${summary.errors || 0} |`,
    `| Skipped | ${summary.skipped || 0} |`,
    `| Pass Rate | ${summary.pass_rate_pct || 0}% |`,
    '',
    '## Category Breakdown',
    '',
    '| Category | Total | Passed | Failed/Errors | Pass Rate |',
    '|---|---|---|---|---|',
  ];

  if (summary.categories) {
    for (const [catName, metrics] of Object.entries(summary.categories)) {
      const rate = metrics.total > 0 ? ((metrics.passed / metrics.total) * 100).toFixed(1) + '%' : '0.0%';
      lines.push(`| ${catName} | ${metrics.total} | ${metrics.passed} | ${metrics.failed + metrics.errors} | ${rate} |`);
    }
  }

  lines.push('', '## Detailed Test Case Results', '', '| Status | Test ID | Category | HTTP | Latency | Description |', '|---|---|---|---|---|---|');

  const results = report.results || [];
  results.forEach(r => {
    const badge = r.status === 'PASS' ? '✅ PASS' : (r.status === 'ERROR' ? '⚠️ ERROR' : '❌ FAIL');
    const http = r.http_status_code || '-';
    const lat = r.execution_time_ms ? `${r.execution_time_ms.toFixed(1)}ms` : '-';
    lines.push(`| ${badge} | \`${r.test_id}\` | ${r.category} | ${http} | ${lat} | ${r.name} |`);
  });

  const failedTests = results.filter(r => r.status === 'FAIL' || r.status === 'ERROR');
  if (failedTests.length > 0) {
    lines.push('', '## Failure Diagnostics & Diffs', '');
    failedTests.forEach(r => {
      lines.push(`### ${r.test_id}: ${r.name}`, '');
      if (r.validation_failures && r.validation_failures.length > 0) {
        lines.push('**Failures:**');
        r.validation_failures.forEach(f => lines.push(`- ${f}`));
        lines.push('');
      }
      if (r.diff_summary) {
        lines.push('**Diff Analysis:**', '```text', r.diff_summary, '```', '');
      }
    });
  }

  return lines.join('\n');
}

function generateHtmlReport(report) {
  const summary = report.summary || {};
  const statusBadge = summary.has_failures
    ? '<span style="color:#ef4444;font-weight:bold;">FAILED</span>'
    : '<span style="color:#22c55e;font-weight:bold;">PASSED</span>';
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Return ACH Test Engine Report</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 24px; }
    h1 { color: #38bdf8; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; background: #1e293b; border-radius: 6px; overflow: hidden; }
    th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #334155; }
    th { background: #0f172a; color: #94a3b8; font-size: 13px; }
    code { font-family: monospace; color: #38bdf8; }
  </style>
</head>
<body>
  <h1>Return ACH Test Engine Report</h1>
  <p><strong>Status:</strong> ${statusBadge}</p>
  <p><strong>Target:</strong> <code>${escapeHtml(summary.target_url || '-')}</code> | <strong>Mode:</strong> ${summary.execution_mode || 'mock'}</p>
  <p><strong>Pass Rate:</strong> ${summary.pass_rate_pct || 0}% | <strong>Total Duration:</strong> ${(summary.total_duration_ms || 0).toFixed(1)} ms</p>
  <h2>Test Results</h2>
  <table>
    <thead><tr><th>Status</th><th>Test ID</th><th>Name</th><th>Category</th><th>HTTP</th><th>Duration</th></tr></thead>
    <tbody>
      ${(report.results || []).map(r => `<tr><td>${r.status}</td><td><code>${escapeHtml(r.test_id)}</code></td><td>${escapeHtml(r.name)}</td><td>${r.category}</td><td>${r.http_status_code || '-'}</td><td>${r.execution_time_ms ? r.execution_time_ms.toFixed(1) + 'ms' : '-'}</td></tr>`).join('')}
    </tbody>
  </table>
</body>
</html>`;
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str);
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

window.loadReportFromHistory = loadReportFromHistory;
window.loadReportHistory = loadReportHistory;
window.openInspector = openInspector;
window.downloadReport = downloadReport;
