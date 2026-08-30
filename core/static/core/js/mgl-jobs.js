/* Public Jobs page only. Filters already-rendered vacant cards. */
(function () {
    var list = document.getElementById("jobs-list");
    var search = document.getElementById("jobs-search");
    var sort = document.getElementById("jobs-sort");
    var empty = document.getElementById("jobs-empty-filter");
    var form = document.getElementById("jobs-apply-form");
    var pending = document.getElementById("jobs-apply-pending");
    var selectedName = document.getElementById("jobs-selected-name");
    var filters = document.querySelectorAll(".mgl-jobs-filter");
    var leagueFilter = "";

    if (!list) return;

    function cards() {
        return Array.prototype.slice.call(list.querySelectorAll(".mgl-jobs-card"));
    }

    function setVisible(node, show) {
        if (!node) return;
        node.hidden = !show;
        node.classList.toggle("is-filtered-out", !show);
        node.style.display = show ? "" : "none";
    }

    function applyFilters() {
        var query = ((search && search.value) || "").trim().toLowerCase();
        var visible = 0;
        cards().forEach(function (card) {
            var leagueOk = !leagueFilter || card.getAttribute("data-league-id") === leagueFilter;
            var name = (card.getAttribute("data-club-name") || "").toLowerCase();
            var leagueName = (card.getAttribute("data-league-name") || "").toLowerCase();
            var searchOk = !query || name.indexOf(query) !== -1 || leagueName.indexOf(query) !== -1;
            var show = leagueOk && searchOk;
            setVisible(card, show);
            if (show) visible += 1;
        });
        setVisible(empty, visible === 0);
    }

    function applySort() {
        if (!sort) return;
        var key = sort.value;
        var items = cards();
        items.sort(function (a, b) {
            if (key === "squad") {
                return (Number(a.getAttribute("data-squad")) || 0) - (Number(b.getAttribute("data-squad")) || 0);
            }
            if (key === "name") {
                return (a.getAttribute("data-club-name") || "").localeCompare(b.getAttribute("data-club-name") || "");
            }
            var leagueCmp = (a.getAttribute("data-league-name") || "").localeCompare(b.getAttribute("data-league-name") || "");
            if (leagueCmp) return leagueCmp;
            return (a.getAttribute("data-club-name") || "").localeCompare(b.getAttribute("data-club-name") || "");
        });
        items.forEach(function (card) { list.appendChild(card); });
        if (empty) list.appendChild(empty);
    }

    function selectCard(card) {
        if (!card) return;
        cards().forEach(function (item) { item.classList.toggle("is-selected", item === card); });
        if (selectedName) selectedName.textContent = (card.getAttribute("data-club-name") || "").toUpperCase();
        var applyUrl = card.getAttribute("data-apply-url") || "";
        var isPending = card.getAttribute("data-pending") === "1";
        if (form) {
            if (applyUrl) form.setAttribute("action", applyUrl);
            form.hidden = isPending;
            form.style.display = isPending ? "none" : "";
        }
        if (pending) {
            pending.hidden = !isPending;
            pending.style.display = isPending ? "" : "none";
        }
    }

    window.mglJobsApplyFilters = applyFilters;

    filters.forEach(function (button) {
        button.addEventListener("click", function () {
            leagueFilter = button.getAttribute("data-league") || "";
            filters.forEach(function (item) {
                var active = item === button;
                item.classList.toggle("is-active", active);
                item.setAttribute("aria-pressed", active ? "true" : "false");
            });
            applyFilters();
        });
    });

    if (search) {
        ["input", "keyup", "change", "search"].forEach(function (eventName) {
            search.addEventListener(eventName, applyFilters);
        });
        var valueDesc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
        if (valueDesc && valueDesc.set) {
            Object.defineProperty(search, "value", {
                get: function () { return valueDesc.get.call(this); },
                set: function (next) {
                    valueDesc.set.call(this, next);
                    applyFilters();
                }
            });
        }
    }
    if (sort) sort.addEventListener("change", function () {
        applySort();
        applyFilters();
    });

    list.addEventListener("click", function (event) {
        var button = event.target.closest(".mgl-jobs-select");
        var card = event.target.closest(".mgl-jobs-card");
        if (!card) return;
        if (button || event.target.closest(".mgl-jobs-card-identity, .mgl-jobs-card-crest")) {
            selectCard(card);
            if (button && window.matchMedia("(max-width: 980px)").matches) {
                var panel = document.getElementById("jobs-apply-panel");
                if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        }
    });
})();
