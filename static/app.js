// app.js (MVP Hackathon)
// Mantenerlo simple: helpers UX sin romper nada.

(function () {
  // Autofocus en el primer input del primer form
  try {
    const firstInput = document.querySelector("form input, form select, form textarea");
    if (firstInput) firstInput.focus();
  } catch (_) {}

  // Confirmación por data-confirm (por si quieres usarlo en botones/forms)
  // Ej: <button data-confirm="¿Seguro?">Eliminar</button>
  document.addEventListener("click", function (e) {
    const el = e.target.closest("[data-confirm]");
    if (!el) return;

    const msg = el.getAttribute("data-confirm") || "¿Seguro?";
    const ok = window.confirm(msg);
    if (!ok) {
      e.preventDefault();
      e.stopPropagation();
    }
  });

  // Helper para limpiar mensajes de error/success si usas #errorBox o #successBox
  // (En el checkout los usamos)
  function autoHide(id, ms) {
    const box = document.getElementById(id);
    if (!box) return;
    if (box.classList.contains("hidden")) return;

    setTimeout(() => {
      // solo oculta si no cambió el texto (para no esconder algo nuevo)
      box.classList.add("hidden");
    }, ms);
  }

  autoHide("successBox", 8000);

  // Debug básico (si quieres ver que cargó)
  // console.log("app.js loaded");
})();
