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
            if (form.getAttribute("data-confirm") || form.getAttribute("data-confirm-phrase")) {
                return;
            }
            form.querySelectorAll("button[type='submit']").forEach(function (button) {
                button.disabled = true;
            });
        });
    });

    function matchesQuery(row, query) {
        if (!query) return true;
        var hay = [
            row.getAttribute("data-player-name") || "",
            row.getAttribute("data-club") || "",
            row.getAttribute("data-position") || "",
            row.textContent || ""
        ].join(" ").toLowerCase();
        return hay.indexOf(query) !== -1;
    }

    var search = document.getElementById("cp-player-search");
    var position = document.getElementById("cp-position-filter");
    function filterPlayers() {
        var query = search ? (search.value || "").trim().toLowerCase() : "";
        var pos = position ? (position.value || "all") : "all";
        document.querySelectorAll(".mgl-cp-player-row").forEach(function (row) {
            var ok = matchesQuery(row, query);
            if (pos !== "all" && (row.getAttribute("data-position") || "") !== pos) ok = false;
            row.hidden = !ok;
            row.style.display = ok ? "" : "none";
        });
    }
    if (search) search.addEventListener("input", filterPlayers);
    if (position) position.addEventListener("change", filterPlayers);

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

    var modal = document.getElementById("cp-confirm-modal");
    var title = document.getElementById("cp-confirm-title");
    var copy = document.getElementById("cp-confirm-copy");
    var ok = document.getElementById("cp-confirm-ok");
    var cancel = document.getElementById("cp-confirm-cancel");
    var pendingForm = null;

    function closeModal() {
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.hidden = true;
        pendingForm = null;
    }

    function openModal(form) {
        pendingForm = form;
        if (title) title.textContent = form.getAttribute("data-confirm-title") || "This action cannot be undone.";
        if (copy) copy.textContent = form.getAttribute("data-confirm") || "Please confirm before continuing.";
        if (ok) ok.textContent = form.getAttribute("data-confirm-ok") || "CONFIRM";
        modal.hidden = false;
        modal.classList.add("is-open");
    }

    if (cancel) cancel.addEventListener("click", closeModal);
    if (modal) {
        modal.addEventListener("click", function (event) {
            if (event.target === modal) closeModal();
        });
    }
    if (ok) {
        ok.addEventListener("click", function () {
            if (!pendingForm) return;
            var form = pendingForm;
            closeModal();
            form.setAttribute("data-confirmed", "1");
            if (form.requestSubmit) form.requestSubmit();
            else form.submit();
        });
    }

    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            if (form.getAttribute("data-confirmed") === "1") return;
            event.preventDefault();
            event.stopImmediatePropagation();
            form.querySelectorAll("button[type='submit']").forEach(function (button) {
                button.disabled = false;
            });
            openModal(form);
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
