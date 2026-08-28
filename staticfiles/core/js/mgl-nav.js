(function () {
  const nav = document.querySelector(".mgl-nav");
  if (!nav) return;

  function menus() {
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

  function closeAll(except) {
    menus().forEach(function (menu) {
      if (menu !== except) closeMenu(menu);
    });
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

  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-nav-dropdown]")) closeAll();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeAll();
  });

  window.addEventListener("resize", function () {
    menus().forEach(function (menu) {
      if (menu.classList.contains("is-open")) positionPanel(menu);
    });
  });
})();
