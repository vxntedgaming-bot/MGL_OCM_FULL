(function () {
    var board = document.querySelector("[data-market-board='sales']");
    if (!board) {
        return;
    }

    var buttons = board.querySelectorAll("[data-pos-filter]");
    var rows = board.querySelectorAll("[data-position]");
    var empty = board.querySelector("[data-filter-empty]");

    function applyFilter(position) {
        var visible = 0;
        rows.forEach(function (row) {
            var match = position === "ALL" || row.getAttribute("data-position") === position;
            row.hidden = !match;
            if (match) {
                visible += 1;
            }
        });
        if (empty) {
            empty.hidden = rows.length === 0 || visible > 0;
        }
    }

    buttons.forEach(function (button) {
        button.addEventListener("click", function () {
            buttons.forEach(function (item) {
                item.classList.toggle("is-active", item === button);
            });
            applyFilter(button.getAttribute("data-pos-filter") || "ALL");
        });
    });
})();
