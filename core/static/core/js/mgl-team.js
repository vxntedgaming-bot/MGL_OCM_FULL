(function () {
    var table = document.getElementById("mgl-squad-table");
    if (!table) return;
    var body = table.tBodies[0];
    var headers = table.querySelectorAll("th[data-sort]");
    var tabs = document.querySelectorAll("[data-sq-tab]");
    var search = document.getElementById("sq-search");
    var pos = document.getElementById("sq-pos");
    var pageSize = document.getElementById("sq-page-size");
    var pages = document.getElementById("sq-pages");
    var range = document.getElementById("sq-range");
    var current = { key: "name", dir: 1 };
    var tab = "all";
    var page = 1;

    function rows() {
        return Array.prototype.slice.call(body.rows);
    }

    function matches(row) {
        var line = row.getAttribute("data-line") || "";
        var name = row.getAttribute("data-name") || "";
        var position = row.getAttribute("data-pos") || "";
        var query = search ? search.value.trim().toLowerCase() : "";
        var wantedPos = pos ? pos.value : "";
        if (tab !== "all" && line !== tab) return false;
        if (wantedPos && position !== wantedPos) return false;
        if (query && name.indexOf(query) === -1) return false;
        return true;
    }

    function render() {
        var visible = rows().filter(matches);
        var size = pageSize ? parseInt(pageSize.value, 10) : 0;
        var total = visible.length;
        var pagesCount = size ? Math.max(1, Math.ceil(total / size)) : 1;
        if (page > pagesCount) page = pagesCount;
        var start = size ? (page - 1) * size : 0;
        var end = size ? start + size : total;
        rows().forEach(function (row) {
            row.hidden = true;
        });
        visible.forEach(function (row, index) {
            row.hidden = size ? index < start || index >= end : false;
            var num = row.querySelector(".mgl-sq-num");
            if (num) num.textContent = String(index + 1);
        });
        if (range) {
            if (!total) {
                range.textContent = "Showing 0 players";
            } else {
                range.textContent =
                    "Showing " +
                    (start + 1) +
                    " to " +
                    Math.min(end, total) +
                    " of " +
                    total +
                    " players";
            }
        }
        if (pages) {
            pages.innerHTML = "";
            for (var i = 1; i <= pagesCount; i += 1) {
                var button = document.createElement("button");
                button.type = "button";
                button.textContent = String(i);
                if (i === page) button.className = "is-active";
                button.addEventListener("click", function (index) {
                    return function () {
                        page = index;
                        render();
                    };
                }(i));
                pages.appendChild(button);
            }
            if (pagesCount > 1 && page < pagesCount) {
                var next = document.createElement("button");
                next.type = "button";
                next.textContent = ">";
                next.addEventListener("click", function () {
                    page += 1;
                    render();
                });
                pages.appendChild(next);
            }
        }
    }

    headers.forEach(function (th) {
        th.addEventListener("click", function () {
            var key = th.getAttribute("data-sort");
            current.dir = current.key === key ? -current.dir : 1;
            current.key = key;
            var sorted = rows().sort(function (a, b) {
                var av = a.getAttribute("data-" + key) || "";
                var bv = b.getAttribute("data-" + key) || "";
                if (key === "ovr" || key === "age") {
                    return ((Number(av) || 0) - (Number(bv) || 0)) * current.dir;
                }
                return av.localeCompare(bv) * current.dir;
            });
            sorted.forEach(function (row) {
                body.appendChild(row);
            });
            render();
        });
    });

    tabs.forEach(function (button) {
        button.addEventListener("click", function () {
            tab = button.getAttribute("data-sq-tab") || "all";
            tabs.forEach(function (item) {
                item.classList.toggle("is-active", item === button);
            });
            page = 1;
            render();
        });
    });
    if (search) search.addEventListener("input", function () { page = 1; render(); });
    if (pos) pos.addEventListener("change", function () { page = 1; render(); });
    if (pageSize) pageSize.addEventListener("change", function () { page = 1; render(); });
    var boards = document.querySelectorAll("[data-sq-board]");
    var panels = document.querySelectorAll("[data-sq-board-panel]");
    boards.forEach(function (button) {
        button.addEventListener("click", function () {
            var name = button.getAttribute("data-sq-board") || "squad";
            boards.forEach(function (item) {
                item.classList.toggle("is-active", item === button);
            });
            panels.forEach(function (panel) {
                panel.hidden = panel.getAttribute("data-sq-board-panel") !== name;
            });
        });
    });
    render();
})();
