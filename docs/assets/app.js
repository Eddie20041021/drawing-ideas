// 首頁依狀態篩選。只有這一個功能；其他頁面載入時沒有篩選按鈕，不會做任何事。
document.querySelectorAll(".filter").forEach((btn) => {
  btn.addEventListener("click", () => {
    const want = btn.dataset.status;
    document.querySelectorAll(".filter").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    document.querySelectorAll(".card").forEach((card) => {
      card.hidden = want !== "all" && card.dataset.status !== want;
    });
  });
});
