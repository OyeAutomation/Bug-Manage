/* 1) Show only the sub-modules that belong to the chosen module. */
function linkSubmodules(moduleId, subId) {
  const map = JSON.parse(document.getElementById('submodule-map').textContent);
  const mod = document.getElementById(moduleId), sub = document.getElementById(subId);
  const keep = sub.value;
  function refill() {
    sub.innerHTML = '<option value="">---------</option>';
    (map[mod.value] || []).forEach(([id, name]) => {
      const o = new Option(name, id); if (String(id) === keep) o.selected = true; sub.add(o);
    });
  }
  mod.addEventListener('change', () => { sub.dataset.touched = 1; refill(); });
  refill();
}

/* 2) Quick-add grid: add rows, and paste spreadsheet data (tab-separated text). */
function parseTSV(text) {            // handles Excel's quotes around cells that contain line breaks
  const rows = []; let row = [], cell = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false; else cell += ch;
    } else if (ch === '"' && cell === '') quoted = true;
    else if (ch === '\t') { row.push(cell); cell = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(cell); rows.push(row); row = []; cell = '';
    } else cell += ch;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows;
}
function initGrid() {
  const body = document.querySelector('#grid tbody');
  const dataRows = () => [...body.querySelectorAll('tr.gridrow')];
  const fields = r => [...r.querySelectorAll('input,textarea,select')];
  function addRow() {
    const last = dataRows().pop(), copy = last.cloneNode(true);
    copy.classList.remove('bad');
    fields(copy).forEach(f => { if (f.tagName !== 'SELECT') f.value = ''; else f.selectedIndex = f.name === 'priority' ? 1 : 0; });
    body.appendChild(copy);
    return copy;
  }
  document.getElementById('addrow').addEventListener('click', addRow);
  body.addEventListener('paste', e => {
    const text = e.clipboardData.getData('text');
    if (!/[\t\n]/.test(text)) return;                 // plain single value: let the browser paste normally
    e.preventDefault();
    const start = e.target.closest('tr.gridrow'), col = fields(start).indexOf(e.target);
    parseTSV(text.replace(/\s+$/, '')).forEach((cells, i) => {
      const rows = dataRows(); const row = rows[dataRows().indexOf(start) + i] || addRow();
      cells.forEach((value, j) => {
        const f = fields(row)[col + j]; if (!f) return;
        if (f.tagName === 'SELECT') {
          const o = [...f.options].find(o => o.text.toLowerCase() === value.trim().toLowerCase()); if (o) f.value = o.value;
        } else f.value = value;
      });
    });
  });
}
