(function () {
  function readJson(id, fallback) {
    var el = document.getElementById(id);
    try { return JSON.parse((el && el.textContent) || "") || fallback; }
    catch (e) { return fallback; }
  }
  var EVCFG = readJson("ev-cfg", {});
  var backLink = document.querySelector("a.back");
  if (backLink) {
    backLink.addEventListener("click", function () {
      var t = window.top || window.parent;
      if (t !== window) {
        t.postMessage({ type: "openbb:widget-params:update", params: { event_id: "", market_key: "" } }, "*");
      }
    });
  }
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
