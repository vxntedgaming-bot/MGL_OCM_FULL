(function () {
    var board = document.querySelector("[data-market-board='sales']");
    if (!board) {
        return;
    }

    var posButtons = board.querySelectorAll("[data-pos-filter]");
    var lineButtons = board.querySelectorAll("[data-line-filter]");
    var rows = board.querySelectorAll("[data-position]");
    var empty = board.querySelector("[data-filter-empty]");
    var search = document.getElementById("mk-search");
    var club = document.getElementById("mk-club");
    var currentPos = "ALL";
    var currentLine = "ALL";

    function applyFilter() {
        var query = search ? search.value.trim().toLowerCase() : "";
        var wantedClub = club ? club.value : "";
        var visible = 0;
        rows.forEach(function (row) {
            var position = row.getAttribute("data-position") || "";
            var line = row.getAttribute("data-line") || "";
            var name = row.getAttribute("data-name") || "";
            var rowClub = row.getAttribute("data-club") || "";
            var match = true;
            if (currentPos !== "ALL" && position !== currentPos) match = false;
            if (currentLine !== "ALL" && line !== currentLine) match = false;
            if (wantedClub && rowClub !== wantedClub) match = false;
            if (query && name.indexOf(query) === -1) match = false;
            row.hidden = !match;
            if (match) visible += 1;
        });
        if (empty) {
            empty.hidden = rows.length === 0 || visible > 0;
        }
    }

    posButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            currentPos = button.getAttribute("data-pos-filter") || "ALL";
            posButtons.forEach(function (item) {
                item.classList.toggle("is-active", item === button);
            });
            applyFilter();
        });
    });

    lineButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            currentLine = button.getAttribute("data-line-filter") || "ALL";
            currentPos = "ALL";
            lineButtons.forEach(function (item) {
                item.classList.toggle("is-active", item === button);
            });
            posButtons.forEach(function (item) {
                item.classList.toggle("is-active", item.getAttribute("data-pos-filter") === "ALL");
            });
            applyFilter();
        });
    });

    if (search) search.addEventListener("input", applyFilter);
    if (club) club.addEventListener("change", applyFilter);
})();
