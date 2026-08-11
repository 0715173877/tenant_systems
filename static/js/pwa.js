/**
 * Tenant Systems - PWA Registration & Install Prompt
 * Handles service worker registration and the "Add to Home Screen" installer.
 */
(function () {
  "use strict";

  // ---- Service Worker Registration ----
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker
        .register("/static/sw.js")
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
                // New version available
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

  // ---- Install Prompt (beforeinstallprompt event) ----
  var deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    // Prevent Chrome 67 and earlier from automatically showing the prompt
    e.preventDefault();
    // Stash the event so it can be triggered later
    deferredPrompt = e;

    // Show a custom install button
    showInstallButton();
  });

  // Feature-detect: only show install UI if install is supported
  window.addEventListener("appinstalled", function (e) {
    // App successfully installed
    console.log("PWA installed!");
    deferredPrompt = null;
    hideInstallButton();
  });

  // ---- Show / Hide Install Button ----
  function showInstallButton() {
    var btn = document.getElementById("pwaInstallBtn");
    if (btn) btn.classList.remove("d-none");
  }

  function hideInstallButton() {
    var btn = document.getElementById("pwaInstallBtn");
    if (btn) btn.classList.add("d-none");
  }

  // Expose install trigger to the button click handler
  window.installPWA = function () {
    if (!deferredPrompt) {
      // Fallback: guide the user (iOS Safari needs manual add-to-home)
      showInstallInstructions();
      return;
    }
    // Show the browser's native install prompt
    deferredPrompt.prompt();
    deferredPrompt.userChoice.then(function (choiceResult) {
      if (choiceResult.outcome === "accepted") {
        console.log("User accepted the install prompt");
      } else {
        console.log("User dismissed the install prompt");
      }
      deferredPrompt = null;
      hideInstallButton();
    });
  };

  // ---- Install Instructions (for iOS / when prompt unavailable) ----
  function showInstallInstructions() {
    var el = document.getElementById("pwaInstallModal");
    if (el && typeof bootstrap !== "undefined") {
      bootstrap.Modal.getOrCreateInstance(el).show();
    }
  }

  // ---- New Version Available Notification ----
  function notifyUpdate(registration, newWorker) {
    // Create a toast if bootstrap is available
    if (typeof bootstrap !== "undefined") {
      var toastEl = document.getElementById("swUpdateToast");
      if (toastEl) {
        toastEl.querySelector(".btn-primary").addEventListener("click", function () {
          // Activate the new worker
          newWorker.postMessage({ type: "SKIP_WAITING" });
          newWorker.addEventListener("statechange", function () {
            if (newWorker.state === "activated") {
              window.location.reload();
            }
          });
        });
        bootstrap.Toast.getOrCreateInstance(toastEl).show();
      }
    }
  }
})();
