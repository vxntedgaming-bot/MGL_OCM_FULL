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

    document.querySelectorAll("[data-cp-tabs]").forEach(function (tabs) {
        var card = tabs.closest("[data-review-card]") || tabs.parentElement;
        tabs.querySelectorAll("[data-tab-target]").forEach(function (button) {
            button.addEventListener("click", function () {
                tabs.querySelectorAll("[data-tab-target]").forEach(function (item) {
                    item.classList.toggle("is-active", item === button);
                });
                var target = button.getAttribute("data-tab-target");
                card.querySelectorAll(".mgl-cp-tab-panel").forEach(function (panel) {
                    panel.hidden = panel.id !== target;
                });
            });
        });
    });

    document.querySelectorAll("form[data-confirm-phrase]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            var needed = form.getAttribute("data-confirm-phrase") || "";
            var typed = (form.querySelector("[name='confirm_text']") || {}).value || "";
            if (typed.trim() !== needed) {
                event.preventDefault();
                event.stopImmediatePropagation();
                window.alert("Type " + needed + " to continue.");
                form.querySelectorAll("button[type='submit']").forEach(function (button) {
                    button.disabled = false;
                });
            }
        });
    });
})();
