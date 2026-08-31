(function () {
    function pad(value) {
        return String(value).padStart(2, "0");
    }

    function formatRemaining(ms) {
        if (ms <= 0) {
            return "00:00:00";
        }
        var total = Math.floor(ms / 1000);
        var hours = Math.floor(total / 3600);
        var minutes = Math.floor((total % 3600) / 60);
        var seconds = total % 60;
        return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds);
    }

    var reloaded = false;
    function tick() {
        document.querySelectorAll("[data-scout-end]").forEach(function (node) {
            var end = new Date(node.getAttribute("data-scout-end"));
            if (Number.isNaN(end.getTime())) {
                return;
            }
            var remaining = end.getTime() - Date.now();
            node.textContent = remaining <= 0 ? "READY" : formatRemaining(remaining) + " REMAINING";
            if (remaining <= 0 && !reloaded) {
                reloaded = true;
                window.setTimeout(function () {
                    window.location.reload();
                }, 800);
            }
        });
    }

    tick();
    window.setInterval(tick, 1000);
})();
