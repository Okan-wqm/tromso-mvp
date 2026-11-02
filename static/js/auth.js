// "Show / Hide" toggle for password fields.
document.querySelectorAll('[data-reveal]').forEach((button) => {
  const input = document.getElementById(button.dataset.reveal);
  if (!input) return;
  button.addEventListener('click', () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.textContent = show ? 'Hide' : 'Show';
    button.setAttribute('aria-pressed', String(show));
    input.focus();
  });
});
