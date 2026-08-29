(function () {
    function copyOptions(source, includeBlank, blankLabel) {
        var html = includeBlank ? '<option value="">' + blankLabel + "</option>" : "";
        Array.prototype.forEach.call(source.options, function (option) {
            html += '<option value="' + option.value + '">' + option.textContent + "</option>";
        });
        return html;
    }

    function renderSlots(container, count, namePrefix, source, includeBlank, blankLabel, heading) {
        container.innerHTML = "";
        var n = parseInt(count, 10) || 0;
        for (var i = 1; i <= n; i += 1) {
            var label = document.createElement("label");
            label.textContent = heading + " " + i;
            var select = document.createElement("select");
            select.name = namePrefix + i;
            select.innerHTML = copyOptions(source, includeBlank, blankLabel);
            if (!includeBlank) {
                select.required = true;
            }
            label.appendChild(select);
            container.appendChild(label);
        }
    }

    function bindSide(panel) {
        var prefix = panel.getAttribute("data-prefix");
        var goalsInput = panel.querySelector(".js-goals");
        var source = panel.querySelector(".js-player-options");
        var goalSlots = panel.querySelector(".js-goal-slots");
        var assistSlots = panel.querySelector(".js-assist-slots");
        if (!goalsInput || !source) {
            return;
        }
        function refresh() {
            renderSlots(goalSlots, goalsInput.value, prefix + "_goal_", source, false, "", "Goal");
            renderSlots(assistSlots, goalsInput.value, prefix + "_assist_", source, true, "Unassisted", "Assist");
        }
        goalsInput.addEventListener("input", refresh);
        goalsInput.addEventListener("change", refresh);
        refresh();
    }

    document.querySelectorAll(".mgl-match-side").forEach(bindSide);
})();
