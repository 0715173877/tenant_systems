/**
 * Tenant Systems - PWA Registration & Install Prompt
 * Handles service worker registration and the "Add to Home Screen" installer.
 */
(function () {
  "use strict";

  var INSTALL_BTN_SELECTOR = ".pwa-install-btn";

  // ---- Service Worker Registration ----
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker
        .register("/sw.js", { scope: "/" })
        .then(function (registration) {
          console.log("SW registered:", registration.scope);

          // Check for updates on each new page load
          registration.update();

          // Listen for new service worker installs
          registration.addEventListener("updatefound", function () {
            var newWorker = registration.installing;
            if (!newWorker) return;

            newWorker.addEventListener("statechange", function () {
              if (
                newWorker.state === "installed" &&
                navigator.serviceWorker.controller
              ) {
                notifyUpdate(registration, newWorker);
              }
            });
          });
        })
        .catch(function (error) {
          console.error("SW registration failed:", error);
        });
    });
  }

  // ---- Detect "already installed" (running as a standalone app) ----
  function isStandalone() {
    var mq = window.matchMedia;
    return (
      (mq && mq("(display-mode: standalone)").matches) ||
      (mq && mq("(display-mode: fullscreen)").matches) ||
      (mq && mq("(display-mode: minimal-ui)").matches) ||
      window.navigator.standalone === true
    );
  }

  function installButtons() {
    return Array.prototype.slice.call(
      document.querySelectorAll(INSTALL_BTN_SELECTOR)
    );
  }

  function showInstallButtons() {
    installButtons().forEach(function (btn) {
      btn.classList.remove("d-none");
    });
  }

  function hideInstallButtons() {
    installButtons().forEach(function (btn) {
      btn.classList.add("d-none");
    });
  }

  // ---- Install Prompt (beforeinstallprompt event) ----
  var deferredPrompt = null;

  window.addEventListener("beforeinstallprompt", function (e) {
    // Suppress Chrome's default mini-infobar; we drive install from our own UI.
    e.preventDefault();
    // Stash the event so it can be triggered later by our install button.
    deferredPrompt = e;
    showInstallButtons();
  });

  window.addEventListener("appinstalled", function () {
    console.log("PWA installed!");
    deferredPrompt = null;
    hideInstallButtons();
  });

  // Expose install trigger to the button click handlers.
  window.installPWA = function () {
    if (deferredPrompt) {
      // Show the browser's native install prompt.
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(function (choiceResult) {
        console.log("Install choice:", choiceResult.outcome);
        var accepted = choiceResult.outcome === "accepted";
        deferredPrompt = null;
        if (accepted) hideInstallButtons();
      });
      return;
    }
    // No native prompt available (iOS Safari, Firefox, or already installed):
    // fall back to manual "Add to Home Screen" guidance.
    showInstallInstructions();
  };

  // ---- Install Instructions (for iOS / when the prompt is unavailable) ----
  function showInstallInstructions() {
    var el = document.getElementById("pwaInstallModal");
    if (el && typeof bootstrap !== "undefined") {
      bootstrap.Modal.getOrCreateInstance(el).show();
    } else {
      window.alert(
        "To install: open your browser menu and choose " +
          '"Add to Home screen" / "Install app".'
      );
    }
  }

  // ---- New Version Available Notification ----
  function notifyUpdate(registration, newWorker) {
    if (typeof bootstrap === "undefined") return;
    var toastEl = document.getElementById("swUpdateToast");
    if (!toastEl) return;
    toastEl.querySelector(".btn-primary").addEventListener("click", function () {
      // Activate the new worker
      newWorker.postMessage({ type: "SKIP_WAITING" });
      newWorker.addEventListener("statechange", function () {
        if (newWorker.state === "activated") window.location.reload();
      });
    });
    bootstrap.Toast.getOrCreateInstance(toastEl).show();
  }

  // ---- Init: reveal install buttons, unless already installed ----
  function init() {
    if (isStandalone()) {
      hideInstallButtons();
    } else {
      showInstallButtons();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

