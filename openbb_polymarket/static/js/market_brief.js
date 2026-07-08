(function () {
  function readJson(id, fallback) {
    var el = document.getElementById(id);
    try { return JSON.parse((el && el.textContent) || "") || fallback; }
    catch (e) { return fallback; }
  }
  var CFG = readJson("mb-cfg", {});
  var PARAM_DEFS = CFG.paramDefs || [];
  var PARAM_KEYS = PARAM_DEFS.map(function (p) { return p.paramName; });
  var target = window.top || window.parent;
  if (target !== window) {
    target.postMessage({ type: "openbb-connect", widgets: [], params: PARAM_DEFS }, "*");
  }

  function extractTheme(d) {
    if (!d || typeof d !== "object") return null;
    var raw = d.theme || d.colorScheme || d.appearance
      || (d.payload && (d.payload.theme || d.payload.colorScheme))
      || (d.params && (typeof d.params.theme === "object" ? d.params.theme && d.params.theme.value : d.params.theme));
    if (typeof raw === "object" && raw) raw = raw.value;
    return (raw === "dark" || raw === "light") ? raw : null;
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme === "light" ? "light" : "dark");
  }

  window.addEventListener("message", function (event) {
    var d = event.data;
    if (!d || typeof d !== "object") return;
    var updates = {};
    var th = extractTheme(d);
    if (th) { applyTheme(th); }
    if (d.type === "openbb-params-update" && d.params) {
      var p = d.params;
      if (Array.isArray(p)) p.forEach(function (x) { updates[x.paramName || x.name] = x.value; });
      else Object.keys(p).forEach(function (k) {
        var v = p[k];
        updates[k] = (v && typeof v === "object" && "value" in v) ? v.value : v;
      });
    }
    var qs = new URLSearchParams(window.location.search), changed = false;
    Object.keys(updates).forEach(function (k) {
      if (PARAM_KEYS.indexOf(k) < 0) return;
      var v = updates[k];
      if (v == null) return;
      if (qs.get(k) !== String(v)) { qs.set(k, String(v)); changed = true; }
    });
    if (changed) window.location.search = qs.toString();
  });

  // Cross-widget market selection sync via server-sent events.
  var CURRENT = CFG.current || "", SYNC = CFG.sync || "";
  if (SYNC && typeof EventSource !== "undefined") {
    new EventSource(SYNC).onmessage = function (e) {
      var mk = e.data;
      if (mk && mk !== CURRENT) {
        var qs = new URLSearchParams(window.location.search);
        qs.set("market_key", mk);
        window.location.search = qs.toString();
      }
    };
  }
})();
