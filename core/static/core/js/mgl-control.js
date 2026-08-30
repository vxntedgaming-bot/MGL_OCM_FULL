(function () {
    var menu = document.getElementById("cp-menu");
    var sidebar = document.getElementById("cp-sidebar");
    if (menu && sidebar) {
        menu.addEventListener("click", function () {
            var open = !sidebar.classList.contains("is-open");
            sidebar.classList.toggle("is-open", open);
            menu.setAttribute("aria-expanded", open ? "true" : "false");
        });
        sidebar.querySelectorAll("a").forEach(function (link) {
            link.addEventListener("click", function () {
                sidebar.classList.remove("is-open");
                menu.setAttribute("aria-expanded", "false");
            });
        });
    }

    document.querySelectorAll(".mgl-cp-page form[method='post']").forEach(function (form) {
        form.addEventListener("submit", function () {
            form.querySelectorAll("button[type='submit']").forEach(function (button) {
                button.disabled = true;
            });
        });
    });

    var search = document.getElementById("cp-player-search");
    if (search) {
        search.addEventListener("input", function () {
            var query = (search.value || "").trim().toLowerCase();
            document.querySelectorAll(".mgl-cp-player-row").forEach(function (row) {
                var name = (row.getAttribute("data-player-name") || "").toLowerCase();
                var show = !query || name.indexOf(query) !== -1;
                row.hidden = !show;
                row.style.display = show ? "" : "none";
            });
        });
    }
})();
