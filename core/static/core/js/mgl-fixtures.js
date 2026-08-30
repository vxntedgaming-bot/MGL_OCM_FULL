(function () {
    var tabs = document.querySelectorAll("[data-fx-tab]");
    var panels = document.querySelectorAll("[data-fx-panel]");
    var filter = document.getElementById("fx-kind");

    function showTab(name) {
        tabs.forEach(function (tab) {
            var active = tab.getAttribute("data-fx-tab") === name;
            tab.classList.toggle("is-active", active);
            tab.setAttribute("aria-selected", active ? "true" : "false");
        });
        panels.forEach(function (panel) {
            var match = panel.getAttribute("data-fx-panel") === name;
            if (match) {
                panel.removeAttribute("hidden");
            } else {
                panel.setAttribute("hidden", "");
            }
        });
    }

    function applyFilter() {
        var value = filter ? filter.value : "all";
        document.querySelectorAll("[data-fx-row]").forEach(function (row) {
            var kind = row.getAttribute("data-fx-kind");
            var state = row.getAttribute("data-fx-state");
            var show =
                value === "all" ||
                kind === value ||
                state === value ||
                (value === "upcoming" && state === "upcoming") ||
                (value === "pending" && state === "pending");
            row.hidden = !show;
        });
    }

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            showTab(tab.getAttribute("data-fx-tab"));
        });
    });
    if (filter) {
        filter.addEventListener("change", applyFilter);
    }
})();
