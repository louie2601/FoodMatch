document.addEventListener("DOMContentLoaded", function () {
  const actionButton = document.getElementById("actionButton");
  const statusText = document.getElementById("statusText");

  if (!actionButton || !statusText) {
    return;
  }

  actionButton.addEventListener("click", function () {
    statusText.textContent = "🎉 JavaScript is working with Tailwind CSS and Django!";
    actionButton.textContent = "Clicked!";
    actionButton.classList.add("bg-emerald-400", "text-slate-950");
  });
});
