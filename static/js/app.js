document.addEventListener('DOMContentLoaded', () => {
  const toastElList = [].slice.call(document.querySelectorAll('.toast'));

  // 각 토스트를 순차적으로(2초 간격) 나타내고, 3초 후 autohide
  toastElList.forEach((toastEl, index) => {
    const delayBeforeShow = 2000 * index; // 이전 것과 2초 간격
    const options = {
      animation: true,
      autohide: true,
      delay: 3000 // 3초 후 자동 닫힘
    };
    const toast = new bootstrap.Toast(toastEl, options);

    setTimeout(() => {
      toast.show();
    }, delayBeforeShow);
  });
});
