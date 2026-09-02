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

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function loadNotifyPanel(box) {
    const panel = box.querySelector("[data-notify-panel]");
    if (!panel) return;
    const url = panel.getAttribute("data-notify-url");
    if (!url) return;
    fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok || /\/login\//.test(response.url || "")) {
          throw new Error("notify");
        }
        return response.text();
      })
      .then(function (html) {
        if (!html || html.indexOf("mgl-notify-head") === -1) return;
        panel.innerHTML = html;
        bindNotifyPanel(box);
        positionNotify(box);
      })
      .catch(function () {});
  }

  function bindNotifyPanel(box) {
    const panel = box.querySelector("[data-notify-panel]");
    if (!panel || panel.getAttribute("data-bound") === "1") return;
    panel.setAttribute("data-bound", "1");
    const markAll = panel.querySelector("[data-notify-read-all]");
    if (markAll) {
      markAll.addEventListener("submit", function (event) {
        event.preventDefault();
        fetch(markAll.action, {
          method: "POST",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": csrfToken(),
          },
          credentials: "same-origin",
          body: new FormData(markAll),
        }).then(function () {
          loadNotifyPanel(box);
          const badge = box.querySelector(".mgl-notify-count");
          if (badge) badge.remove();
        });
      });
    }
    panel.querySelectorAll("[data-notify-item]").forEach(function (item) {
      item.addEventListener("click", function (event) {
        if (event.target.closest("a, button, form, textarea, input")) return;
        const url = item.getAttribute("data-notify-read-url");
        if (!url || !item.classList.contains("is-unread")) return;
        const body = new URLSearchParams();
        body.set("csrfmiddlewaretoken", csrfToken());
        fetch(url, {
          method: "POST",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": csrfToken(),
            "Content-Type": "application/x-www-form-urlencoded",
          },
          credentials: "same-origin",
          body: body.toString(),
        }).then(function (response) { return response.json(); }).then(function (data) {
          item.classList.remove("is-unread");
          const badge = box.querySelector(".mgl-notify-count");
          if (badge && data && typeof data.unread === "number") {
            if (data.unread > 0) badge.textContent = data.unread;
            else badge.remove();
          }
        }).catch(function () {});
      });
    });
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
          bindNotifyPanel(box);
          positionNotify(box);
          loadNotifyPanel(box);
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

  (function initUflTicker() {
    const root = document.querySelector("[data-ufl-ticker]");
    if (!root) return;
    const items = Array.prototype.slice.call(root.querySelectorAll(".ufl-ticker-item"));
    if (items.length <= 1) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      items.forEach(function (el, index) {
        el.classList.toggle("is-active", index === 0);
      });
      return;
    }
    let index = 0;
    let timer = null;
    function show(next) {
      items.forEach(function (el, itemIndex) {
        el.classList.toggle("is-active", itemIndex === next);
      });
    }
    function tick() {
      index = (index + 1) % items.length;
      show(index);
    }
    function start() {
      if (!timer) timer = window.setInterval(tick, 1500);
    }
    function stop() {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    }
    const bar = document.querySelector("[data-ufl-ticker-root]") || root;
    bar.addEventListener("mouseenter", stop);
    bar.addEventListener("mouseleave", start);
    bar.addEventListener("focusin", stop);
    bar.addEventListener("focusout", start);
    start();
  })();
})();
