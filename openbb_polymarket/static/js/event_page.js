(function () {
  function readJson(id, fallback) {
    var el = document.getElementById(id);
    try { return JSON.parse((el && el.textContent) || "") || fallback; }
    catch (e) { return fallback; }
  }
  var EVCFG = readJson("ev-cfg", {});
  var FILTERS = EVCFG.filters || {};
  var FILTER_KEYS = ["tag", "search", "sort", "close_within", "reverse", "limit", "offset"];
  var host = window.top || window.parent;

  function emit(params) {
    if (host !== window) host.postMessage({ type: "openbb:widget-params:update", params: params }, "*");
  }

  function listUrl(overrides) {
    var qs = new URLSearchParams();
    FILTER_KEYS.forEach(function (k) {
      var v = overrides && overrides[k] != null ? overrides[k] : FILTERS[k];
      if (v != null && String(v) !== "") qs.set(k, String(v));
    });
    if (EVCFG.theme) qs.set("theme", EVCFG.theme);
    return "/browse_markets?" + qs.toString();
  }

  if (EVCFG.event_id) {
    emit({ event_id: EVCFG.event_id, market_key: EVCFG.market_key || "", view: EVCFG.event_id });
  }

  var backLink = document.querySelector("a.back");
  if (backLink) {
    backLink.addEventListener("click", function () { emit({ view: "" }); });
  }

  window.addEventListener("message", function (event) {
    var d = event.data;
    if (!d || typeof d !== "object" || d.type !== "openbb-params-update") return;
    var raw = d.params || d.payload || d.data || d.values || {};
    var incoming = {};
    if (Array.isArray(raw)) {
      raw.forEach(function (p) { incoming[p.paramName || p.name] = p.value; });
    } else {
      Object.keys(raw).forEach(function (k) {
        var v = raw[k];
        incoming[k] = (v && typeof v === "object" && "value" in v) ? v.value : v;
      });
    }
    var overrides = {}, changed = false;
    FILTER_KEYS.forEach(function (k) {
      if (incoming[k] == null) return;
      var s = String(incoming[k]);
      if (s !== String(FILTERS[k] == null ? "" : FILTERS[k])) { overrides[k] = s; changed = true; }
    });
    if (changed) {
      emit({ view: "" });
      window.location.href = listUrl(overrides);
    }
  });

  document.querySelectorAll(".ts-d").forEach(function (el) {
    var ms = Number(el.getAttribute("data-ts")); if (!ms) return;
    el.textContent = (el.getAttribute("data-prefix") || "")
      + new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  });
  // Plotly renders datetime axes in UTC; shift x to the viewer's local time.
  function localize(fig) {
    if (fig && fig.data) fig.data.forEach(function (tr) {
      if (tr.x && tr.x.length) tr.x = tr.x.map(function (v) {
        var d = new Date(v);
        return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 23);
      });
    });
    return fig;
  }
  var el = document.getElementById("ev-chart");
  var CFG = { responsive: true, displayModeBar: false, scrollZoom: true };
  if (el && window.Plotly) {
    var fig = localize(readJson("ev-fig", {}));
    if (fig.data) Plotly.newPlot(el, fig.data, fig.layout || {}, CFG);
    var POLL = EVCFG.poll || "";
    if (POLL) setInterval(function () {
      fetch(POLL, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (f) { if (f && f.data) { localize(f); Plotly.react(el, f.data, f.layout || {}, CFG); } })
        .catch(function () {});
    }, 30000);
  }
})();
