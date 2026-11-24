// The product's Content-Security-Policy (config/settings.py, SECURE_CSP) as the browser tests serve their pages with it,
// without the nonce: a page of islands needs none. One copy for every browser test. Test code only.
export const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
  + "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
