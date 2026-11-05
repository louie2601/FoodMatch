window.addEventListener("DOMContentLoaded", function () {
  const analyzingOverlay = document.getElementById("analyzingOverlay");
  const checkForm = document.querySelector("form[enctype='multipart/form-data']");
  const checkBtn = document.querySelector("[data-check-similarity-btn]");
  const checkLabel = document.querySelector("[data-check-similarity-label]");

  if (checkForm && checkBtn) {
    checkForm.addEventListener("submit", function () {
      if (analyzingOverlay) {
        analyzingOverlay.classList.remove("hidden");
        analyzingOverlay.classList.add("flex");
      }
      checkBtn.disabled = true;
      if (checkLabel) checkLabel.textContent = "Analyzing...";
    });
  }
});
