// Applies the saved (or system) theme before the first paint. A file, not inline, so the page needs no inline scripts.
try {
  var saved = localStorage.getItem("hub.theme");
  if (saved === "dark" || (!saved && matchMedia("(prefers-color-scheme: dark)").matches)) document.documentElement.classList.add("dark");
} catch (e) {}
