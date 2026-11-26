/* Small progressive-enhancement helpers. No framework, no build step. */
(function () {
  "use strict";

  // Demo accounts on the login page prefill the email field.
  document.querySelectorAll(".demo-row").forEach(function (row) {
    row.addEventListener("click", function () {
      var email = row.getAttribute("data-email");
      var field = document.getElementById("email");
      if (field && email) {
        field.value = email;
        field.focus();
      }
    });
  });

  // Flash messages fade out so they do not pile up.
  document.querySelectorAll(".flash").forEach(function (flash) {
    window.setTimeout(function () {
      flash.style.transition = "opacity .4s ease";
      flash.style.opacity = "0";
      window.setTimeout(function () { flash.remove(); }, 420);
    }, 6000);
  });

  // Guard the destructive status change (closing a ticket).
  document.querySelectorAll('form[action$="/status"]').forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var input = form.querySelector('input[name="status"]');
      if (input && input.value === "Closed") {
        if (!window.confirm("Close this ticket? It can be reopened later.")) {
          event.preventDefault();
        }
      }
    });
  });

  // Client-side guard mirroring the server-side validation rules.
  var ticketForm = document.getElementById("ticket-form");
  if (ticketForm) {
    ticketForm.addEventListener("submit", function (event) {
      var title = ticketForm.querySelector('[name="title"]');
      var description = ticketForm.querySelector('[name="description"]');
      if (title && title.value.trim().length < 5) {
        event.preventDefault();
        title.focus();
        return;
      }
      if (description && description.value.trim().length < 10) {
        event.preventDefault();
        description.focus();
      }
    });
  }
})();
