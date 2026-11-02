// "Show / Hide" toggle for password fields on the sign-in and password pages. The two texts are
// data attributes of the button (data-label-show, data-label-hide): the server translates them.
import { label } from './dom.js';

document.querySelectorAll<HTMLButtonElement>('[data-reveal]').forEach((button) => {
  const input = document.getElementById(button.dataset.reveal ?? '');
  if (!(input instanceof HTMLInputElement)) return;
  button.addEventListener('click', () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.textContent = label(button, show ? 'labelHide' : 'labelShow');
    button.setAttribute('aria-pressed', String(show));
    input.focus();
  });
});

export {};
