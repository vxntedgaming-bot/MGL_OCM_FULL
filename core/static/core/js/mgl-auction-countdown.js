(function () {
    function pad(value) {
        return String(value).padStart(2, "0");
    }

    function formatRemaining(ms) {
        if (ms <= 0) {
            return "ENDED";
        }
        var total = Math.floor(ms / 1000);
        var hours = Math.floor(total / 3600);
        var minutes = Math.floor((total % 3600) / 60);
        var seconds = total % 60;
        if (hours >= 24) {
            var days = Math.floor(hours / 24);
            hours = hours % 24;
            return pad(days) + "d " + pad(hours) + "h " + pad(minutes) + "m";
        }
        return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds);
    }

    function closeCard(card) {
        if (!card || card.classList.contains("is-ended")) {
            return;
        }
        card.classList.add("is-ended");
        card.querySelectorAll("[data-auction-bid-form] input, [data-auction-bid-form] button").forEach(
            function (node) {
                node.disabled = true;
            }
        );
        var button = card.querySelector("[data-auction-bid-form] button");
        if (button) {
            button.textContent = "ENDED";
        }
        card.querySelectorAll("[data-auction-open]").forEach(function (node) {
            node.setAttribute("aria-disabled", "true");
            node.classList.add("is-disabled");
        });
    }

    function tick() {
        document.querySelectorAll("[data-auction-end]").forEach(function (node) {
            var endValue = node.getAttribute("data-auction-end");
            if (!endValue) {
                return;
            }
            var end = new Date(endValue);
            if (Number.isNaN(end.getTime())) {
                return;
            }
            var remaining = end.getTime() - Date.now();
            node.textContent = formatRemaining(remaining);
            if (remaining <= 0) {
                closeCard(node.closest("[data-auction-card]"));
            }
        });
    }

    function openDialog(id) {
        var dialog = document.getElementById("auction-bid-" + id);
        if (!dialog) {
            return false;
        }
        if (typeof dialog.showModal === "function") {
            if (!dialog.open) {
                dialog.showModal();
            }
        } else {
            dialog.setAttribute("open", "");
        }
        return true;
    }

    document.querySelectorAll("[data-auction-open]").forEach(function (trigger) {
        trigger.addEventListener("click", function (event) {
            var id = trigger.getAttribute("data-auction-open");
            if (!id) {
                return;
            }
            if (openDialog(id)) {
                event.preventDefault();
            }
        });
    });

    document.querySelectorAll("[data-auction-close]").forEach(function (trigger) {
        trigger.addEventListener("click", function () {
            var dialog = trigger.closest("dialog");
            if (dialog && typeof dialog.close === "function") {
                dialog.close();
            } else if (dialog) {
                dialog.removeAttribute("open");
            }
        });
    });

    var params = new URLSearchParams(window.location.search);
    var openId = params.get("auction");
    if (openId) {
        openDialog(openId);
    }

    tick();
    window.setInterval(tick, 1000);
})();
