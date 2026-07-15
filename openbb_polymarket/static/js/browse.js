(function () {
  var MANIFESTS = JSON.parse(document.getElementById("ob-manifests").textContent || "[]");
  var PARAM_DEFS = JSON.parse(document.getElementById("ob-params").textContent || "[]");
  var ROWS = JSON.parse(document.getElementById("ob-rowdata").textContent || "[]");
  var CFG = JSON.parse(document.getElementById("ob-cfg").textContent || "{}");
  var PARAM_KEYS = PARAM_DEFS.map(function (p) { return p.paramName; });
  var CURRENT = {};
  PARAM_DEFS.forEach(function (p) {
    CURRENT[p.paramName] = String(p.value == null ? "" : p.value);
  });
  var GROUP_FILTER_VALUES = {};
  PARAM_DEFS.forEach(function (p) {
    if (p.paramName !== "tag") return;
    (p.options || []).forEach(function (opt) {
      var value = typeof opt === "object" ? opt.value : opt;
      if (value != null && String(value).trim() && String(value) !== "All") {
        GROUP_FILTER_VALUES[String(value).toLowerCase()] = true;
      }
    });
  });

  var WIDGET_DATA = {};
  MANIFESTS.forEach(function (m) {
    WIDGET_DATA[m.widgetId] = { type: "openbb-data", widgetId: m.widgetId, dataType: m.dataType, data: ROWS };
  });

  function localizeTimes(root) {
    (root || document).querySelectorAll(".ts-d").forEach(function (el) {
      var ms = Number(el.getAttribute("data-ts")); if (!ms) return;
      el.textContent = (el.getAttribute("data-prefix") || "")
        + new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    });
  }
  localizeTimes();

  var target = window.top || window.parent;
  if (target !== window) {
    target.postMessage({ type: "openbb-connect", widgets: MANIFESTS, params: PARAM_DEFS }, "*");
  }

  function applyTheme(theme) {
    var t = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
    CFG.theme = t;
    var grid = document.getElementById("ob-grid");
    if (grid) {
      grid.classList.remove("ag-theme-quartz", "ag-theme-quartz-dark");
      grid.classList.add(t === "light" ? "ag-theme-quartz" : "ag-theme-quartz-dark");
    }
  }
  function extractTheme(d) {
    if (!d || typeof d !== "object") return null;
    var raw = d.theme || d.colorScheme || d.appearance
      || (d.payload && (d.payload.theme || d.payload.colorScheme))
      || (d.data && d.data.theme)
      || (d.params && (typeof d.params.theme === "object" ? d.params.theme && d.params.theme.value : d.params.theme));
    if (typeof raw === "object" && raw) raw = raw.value;
    if (raw === "dark" || raw === "light") return raw;
    if (typeof d.type === "string" && d.type.toLowerCase().indexOf("theme") >= 0 && (d.value === "dark" || d.value === "light")) return d.value;
    return null;
  }
  applyTheme(CFG.theme || "dark");

  function applyParams(params) {
    if (!params) return;
    var incoming = {};
    if (Array.isArray(params)) {
      params.forEach(function (p) { incoming[p.paramName || p.name] = p.value; });
    } else if (typeof params === "object") {
      Object.keys(params).forEach(function (k) {
        var v = params[k];
        incoming[k] = (v && typeof v === "object" && "value" in v) ? v.value : v;
      });
    }
    var qs = new URLSearchParams(window.location.search), changed = false;
    var tag = String(incoming.tag != null ? incoming.tag : (CURRENT.tag || ""));
    var search = String(incoming.search != null ? incoming.search : (CURRENT.search || ""));
    var grouped = !!tag && tag !== "All";
    if (grouped && GROUP_FILTER_VALUES[search.toLowerCase()]) {
      incoming.search = "";
      emitWidgetParams({ search: "" });
    }
    Object.keys(incoming).forEach(function (k) {
      var v = incoming[k];
      if (!k || v == null || PARAM_KEYS.indexOf(k) < 0) return;
      var s = String(v);
      if (CURRENT[k] !== s) { qs.set(k, s); changed = true; }
    });
    if (changed) window.location.search = qs.toString();
  }

  function emitWidgetParams(params) {
    if (target === window || !params) return;
    target.postMessage({ type: "openbb:widget-params:update", params: params }, "*");
  }


  window.addEventListener("message", function (event) {
    var d = event.data;
    if (!d || typeof d !== "object") return;
    var th = extractTheme(d);
    if (th) applyTheme(th);
    if (!d.type) return;
    if (d.type === "openbb-request") {
      var widgetId = d.widgetId;
      if (widgetId === null || widgetId === undefined) {
        Object.keys(WIDGET_DATA).forEach(function (id) { target.postMessage(WIDGET_DATA[id], "*"); });
      } else if (WIDGET_DATA[widgetId]) {
        target.postMessage(WIDGET_DATA[widgetId], "*");
      }
    } else if (d.type === "openbb-params-update") {
      applyParams(d.params || d.payload || d.data || d.values || d);
    }
  });

  var gridApi = null;
  function intFmt(p) { return p.value == null ? "" : Number(p.value).toLocaleString(); }
  function pctFmt(p) { return p.value == null ? "" : Number(p.value).toFixed(0) + "%"; }
  function eventUrl(id, mk) {
    var u = CFG.base + "/browse_markets?view=" + encodeURIComponent(id);
    if (mk) u += "&market_key=" + encodeURIComponent(mk);
    if (CFG.back) u += "&" + CFG.back;
    return u;
  }
  function selectEvent(id, mk) {
    emitWidgetParams({ event_id: id, market_key: mk || "", view: id });
  }
  function selectAndOpen(id, mk) {
    if (!id) return;
    selectEvent(id, mk);
    window.location.href = eventUrl(id, mk);
  }
  function buildGrid() {
    if (gridApi || !window.agGrid) return;
    gridApi = agGrid.createGrid(document.getElementById("ob-grid"), {
      rowData: ROWS,
      defaultColDef: { sortable: true, filter: true, resizable: true },
      columnDefs: [
        { headerName: "Event", field: "title", flex: 2, minWidth: 260, pinned: "left" },
        { headerName: "Tags", field: "tags", width: 180 },
        { headerName: "Leading", field: "leading_outcome", width: 170 },
        { headerName: "Leading %", field: "leading_pct", width: 110, type: "numericColumn", valueFormatter: pctFmt },
        { headerName: "Markets", field: "market_count", width: 100, type: "numericColumn", valueFormatter: intFmt },
        { headerName: "24h Vol", field: "volume_24h", width: 120, type: "numericColumn", valueFormatter: intFmt },
        { headerName: "Total Vol", field: "volume_total", width: 120, type: "numericColumn", valueFormatter: intFmt },
        { headerName: "Liquidity", field: "liquidity", width: 120, type: "numericColumn", valueFormatter: intFmt },
        { headerName: "OI", field: "open_interest", width: 110, type: "numericColumn", valueFormatter: intFmt },
        { headerName: "Ends", field: "close_time", width: 160 }
      ],
      onRowClicked: function (e) {
        if (e.data && e.data.event_id) {
          selectAndOpen(e.data.event_id, e.data.market_key || "");
        }
      }
    });
  }
  function setView(view) {
    var cards = document.getElementById("ob-cards"), grid = document.getElementById("ob-grid");
    var bc = document.getElementById("ob-view-cards"), bt = document.getElementById("ob-view-table"), csv = document.getElementById("ob-csv");
    if (view === "table") {
      buildGrid();
      cards.classList.add("ob-hidden"); grid.classList.remove("ob-hidden");
      bt.classList.add("active"); bc.classList.remove("active"); csv.classList.remove("ob-hidden");
    } else {
      grid.classList.add("ob-hidden"); cards.classList.remove("ob-hidden");
      bc.classList.add("active"); bt.classList.remove("active"); csv.classList.add("ob-hidden");
    }
  }
  document.getElementById("ob-view-cards").addEventListener("click", function () { setView("cards"); });
  document.getElementById("ob-view-table").addEventListener("click", function () { setView("table"); });
  document.getElementById("ob-csv").addEventListener("click", function () { if (gridApi) gridApi.exportDataAsCsv({ fileName: "polymarket_events.csv" }); });
  ["ob-prev", "ob-next"].forEach(function (id) {
    var btn = document.getElementById(id);
    if (!btn || btn.disabled) return;
    btn.addEventListener("click", function () {
      var qs = new URLSearchParams(window.location.search);
      qs.set("offset", btn.getAttribute("data-offset") || "0");
      emitWidgetParams({ offset: btn.getAttribute("data-offset") || "0" });
      window.location.search = qs.toString();
    });
  });
  document.addEventListener("click", function (event) {
    var a = event.target && event.target.closest ? event.target.closest("a.event[data-event-id]") : null;
    if (!a) return;
    selectEvent(a.getAttribute("data-event-id"), a.getAttribute("data-market-key") || "");
  });
})();
