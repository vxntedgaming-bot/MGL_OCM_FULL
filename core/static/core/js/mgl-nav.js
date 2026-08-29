(function () {
  const nav = document.querySelector(".mgl-nav");

  function menus() {
    if (!nav) return [];
    return nav.querySelectorAll("[data-nav-dropdown]");
  }

  function closeMenu(menu) {
    menu.classList.remove("is-open");
    const trigger = menu.querySelector("[data-nav-trigger]");
    const panel = menu.querySelector(".mgl-nav-menu");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    if (panel) {
      panel.setAttribute("aria-hidden", "true");
      panel.style.left = "";
      panel.style.right = "";
    }
  }

  function closeNotify(except) {
    document.querySelectorAll("[data-notify-dropdown]").forEach(function (box) {
      if (box === except) return;
      box.classList.remove("is-open");
      const trigger = box.querySelector("[data-notify-trigger]");
      const panel = box.querySelector(".mgl-notify-panel");
      if (trigger) trigger.setAttribute("aria-expanded", "false");
      if (panel) {
        panel.hidden = true;
        panel.style.left = "";
        panel.style.right = "";
        panel.style.width = "";
      }
    });
  }

  function closeAll(except) {
    menus().forEach(function (menu) {
      if (menu !== except) closeMenu(menu);
    });
    closeNotify(except && except.hasAttribute("data-notify-dropdown") ? except : null);
  }

  function positionPanel(menu) {
    const panel = menu.querySelector(".mgl-nav-menu");
    if (!panel || window.matchMedia("(max-width: 1100px)").matches) return;
    panel.style.left = "0";
    panel.style.right = "auto";
    const rect = panel.getBoundingClientRect();
    if (rect.right > window.innerWidth - 8) {
      panel.style.left = "auto";
      panel.style.right = "0";
    }
    if (panel.getBoundingClientRect().left < 8) {
      panel.style.left = "0";
      panel.style.right = "auto";
    }
  }

  function positionNotify(box) {
    const panel = box.querySelector(".mgl-notify-panel");
    if (!panel) return;
    if (window.matchMedia("(max-width: 390px)").matches) {
      panel.style.left = "8px";
      panel.style.right = "8px";
      panel.style.width = "auto";
      return;
    }
    panel.style.left = "auto";
    panel.style.right = "0";
    panel.style.width = "";
    const rect = panel.getBoundingClientRect();
    if (rect.left < 8) {
      panel.style.right = "auto";
      panel.style.left = "0";
    }
    if (panel.getBoundingClientRect().right > window.innerWidth - 8) {
      panel.style.left = "auto";
      panel.style.right = "0";
    }
  }

  if (nav) {
    nav.addEventListener("click", function (event) {
      const trigger = event.target.closest("[data-nav-trigger]");
      if (!trigger || !nav.contains(trigger)) return;
      event.preventDefault();
      event.stopPropagation();
      const menu = trigger.closest("[data-nav-dropdown]");
      const willOpen = !menu.classList.contains("is-open");
      closeAll();
      if (willOpen) {
        menu.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
        const panel = menu.querySelector(".mgl-nav-menu");
        if (panel) panel.setAttribute("aria-hidden", "false");
        positionPanel(menu);
      }
    });

    nav.addEventListener("click", function (event) {
      const link = event.target.closest("a");
      if (!link) return;
      const toggle = document.getElementById("mgl-nav-toggle");
      if (toggle && window.matchMedia("(max-width: 1100px)").matches) {
        toggle.checked = false;
        closeAll();
      }
    });
  }

  document.addEventListener("click", function (event) {
    const trigger = event.target.closest("[data-notify-trigger]");
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      const box = trigger.closest("[data-notify-dropdown]");
      const willOpen = !box.classList.contains("is-open");
      closeAll();
      if (willOpen) {
        box.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
        const panel = box.querySelector(".mgl-notify-panel");
        if (panel) {
          panel.hidden = false;
          positionNotify(box);
        }
      }
      return;
    }
    if (
      !event.target.closest("[data-nav-dropdown]") &&
      !event.target.closest("[data-notify-dropdown]")
    ) {
      closeAll();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeAll();
  });

  window.addEventListener("resize", function () {
    menus().forEach(function (menu) {
      if (menu.classList.contains("is-open")) positionPanel(menu);
    });
    document.querySelectorAll("[data-notify-dropdown].is-open").forEach(positionNotify);
  });
})();
