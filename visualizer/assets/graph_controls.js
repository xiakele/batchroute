(function () {
  "use strict";

  function getCyInstance() {
    const container = document.getElementById("topo-graph");
    if (!container) return null;

    const key = Object.keys(container).find(function (k) {
      return k.startsWith("__reactInternalInstance") || k.startsWith("__reactFiber");
    });
    if (!key) return null;

    let fiber = container[key];
    while (fiber) {
      if (fiber.stateNode && fiber.stateNode._cy) {
        return fiber.stateNode._cy;
      }
      fiber = fiber.return;
    }
    return null;
  }

  let cy = null;
  let checkInterval = null;
  let resizeTimeout = null;

  function setup() {
    if (cy) return true;
    cy = getCyInstance();
    if (!cy) return false;

    const btnZoomOut = document.getElementById("btn-zoom-out");
    const btnCenter = document.getElementById("btn-center");
    const btnZoomIn = document.getElementById("btn-zoom-in");
    const btnFullscreen = document.getElementById("btn-fullscreen");

    if (btnZoomOut) {
      btnZoomOut.addEventListener("click", function () {
        cy.zoom(cy.zoom() / 1.25);
      });
    }
    if (btnZoomIn) {
      btnZoomIn.addEventListener("click", function () {
        cy.zoom(cy.zoom() * 1.25);
      });
    }
    if (btnCenter) {
      btnCenter.addEventListener("click", function () {
        cy.fit();
      });
    }
    if (btnFullscreen) {
      btnFullscreen.addEventListener("click", function () {
        const card = document.querySelector(".graph-card");
        if (!document.fullscreenElement) {
          if (card && card.requestFullscreen) card.requestFullscreen();
        } else {
          if (document.exitFullscreen) document.exitFullscreen();
        }
      });
    }

    const graphCard = document.querySelector(".graph-card");
    if (graphCard && typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(function () {
        var container = document.getElementById("topo-graph");
        if (!container) return;
        var w = graphCard.clientWidth;
        var h = graphCard.clientHeight;
        if (w <= 0 || h <= 0) return;
        if (resizeTimeout) clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(function () {
          if (cy.elements().length === 0) return;
          cy.fit();
        }, 150);
      });
      ro.observe(graphCard);
    }

    if (checkInterval) {
      clearInterval(checkInterval);
      checkInterval = null;
    }
    return true;
  }

  if (!setup()) {
    checkInterval = setInterval(function () {
      if (setup()) {
        clearInterval(checkInterval);
        checkInterval = null;
      }
    }, 500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setup);
  }
})();
