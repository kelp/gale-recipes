// Tiny progressive-enhancement: search filter + column
// sort for the status table. Table is fully usable
// without JS.
(function () {
  const table = document.getElementById("status");
  if (!table) return;

  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const input = document.getElementById("filter");
  const failingOnly = document.getElementById("failing-only");

  function rowMatches(row, q) {
    if (failingOnly && failingOnly.checked) {
      if (!row.querySelector("td.fail")) return false;
    }
    if (!q) return true;
    return (row.dataset.name || "").toLowerCase().includes(q);
  }

  function applyFilter() {
    const q = (input.value || "").toLowerCase().trim();
    for (const row of rows) {
      row.style.display = rowMatches(row, q) ? "" : "none";
    }
  }

  if (input) input.addEventListener("input", applyFilter);
  if (failingOnly) failingOnly.addEventListener("change", applyFilter);

  // Column sort.
  const headers = Array.from(table.querySelectorAll("thead th"));
  let sortKey = null;
  let sortDir = 1;

  function cellValue(row, idx) {
    const td = row.cells[idx];
    if (!td) return "";
    if (td.classList.contains("ok")) return 1;
    if (td.classList.contains("fail")) return 0;
    return (td.textContent || "").trim().toLowerCase();
  }

  headers.forEach((th, idx) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort || String(idx);
      sortDir = sortKey === key ? -sortDir : 1;
      sortKey = key;
      const sorted = rows.slice().sort((a, b) => {
        const av = cellValue(a, idx);
        const bv = cellValue(b, idx);
        if (av < bv) return -1 * sortDir;
        if (av > bv) return  1 * sortDir;
        return 0;
      });
      for (const r of sorted) tbody.appendChild(r);
    });
  });
})();
