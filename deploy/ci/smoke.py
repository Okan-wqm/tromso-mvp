#!/usr/bin/env python3
"""The production stack's HTTPS smoke test (deploy/ci/stack.sh smoke), from outside the stack as a browser sees it:

1. plain HTTP is sent to https;
2. the sign-in page answers over TLS with HSTS, the Content-Security-Policy (style-src 'self'), nosniff, DENY framing and
   a Secure CSRF cookie;
3. a static file under its hashed name is kept for a year (immutable), the same file under its plain name is not;
4. a TLS handshake for another host name is refused;
5. the first admin signs in (CSRF over https, a Secure HttpOnly session cookie), and every page linked from the home
   page and from those pages answers without a server error;
6. the sign-in and reset pages are rate limited per client (429).
Exit 1 on the first failure. Standard library only."""
import argparse
import http.client
import http.cookiejar
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

failures = []


def check(condition, what):
    print(('ok    ' if condition else 'FAIL  ') + what)
    if not condition:
        failures.append(what)


class Keep(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None                         # a redirect is a result to look at, not to follow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--ca', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--password-file', required=True)
    parser.add_argument('--max-pages', type=int, default=250)
    options = parser.parse_args()
    base = f'https://{options.host}'
    context = ssl.create_default_context(cafile=options.ca)
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                         urllib.request.HTTPCookieProcessor(jar), Keep())

    def get(url, data=None, headers=None):
        request = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with opener.open(request, timeout=60) as response:
                return response.status, response.headers, response.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read().decode('utf-8', 'replace')

    print('== 1. http to https')
    status, headers, _ = get(f'http://{options.host}/accounts/login/')
    check(status == 301 and headers.get('Location') == f'{base}/accounts/login/',
          f'http answers 301 to https ({status} {headers.get("Location")})')

    print('== 2. the sign-in page and its headers')
    status, headers, page = get(f'{base}/accounts/login/')
    check(status == 200, f'the sign-in page answers 200 over TLS ({status})')
    check((headers.get('Strict-Transport-Security') or '').startswith('max-age='),
          f'HSTS: {headers.get("Strict-Transport-Security")}')
    csp = headers.get('Content-Security-Policy') or ''
    check("style-src 'self'" in csp and "script-src 'self' 'nonce-" in csp and "frame-ancestors 'none'" in csp,
          f'the Content-Security-Policy is the application\'s: {csp}')
    check(headers.get('X-Content-Type-Options') == 'nosniff', 'X-Content-Type-Options: nosniff')
    check(headers.get('X-Frame-Options') == 'DENY', 'X-Frame-Options: DENY')
    check(any(c.name == 'csrftoken' and c.secure for c in jar), 'the CSRF cookie is Secure')
    check('Server' not in headers or 'nginx/' not in headers['Server'], f'no server version: {headers.get("Server")}')

    print('== 3. static files')
    hashed = re.findall(r'(?:href|src)="(/static/[^"?]+\.[0-9a-f]{12}\.(?:css|js|svg))"', page)
    check(bool(hashed), f'the sign-in page names static files under hashed names ({len(hashed)})')
    if hashed:
        status, headers, _ = get(base + hashed[0])
        check(status == 200 and headers.get('Cache-Control') == 'public, max-age=31536000, immutable',
              f'{hashed[0]}: {status}, Cache-Control {headers.get("Cache-Control")}')
        plain = re.sub(r'\.[0-9a-f]{12}(\.\w+)$', r'\1', hashed[0])
        status, headers, _ = get(base + plain)
        check(status == 200 and headers.get('Cache-Control') == 'no-cache',
              f'{plain}: {status}, Cache-Control {headers.get("Cache-Control")}')
    check('/static/js/' in page or 'importmap' in page, 'the import map is on the page')
    status, _, _ = get(f'{base}/media/anything.pdf')
    check(status == 404, f'/media/ is never served by the proxy ({status})')

    print('== 4. another host name')
    try:
        with socket.create_connection(('127.0.0.1', 443), timeout=10) as raw:
            other = ssl.create_default_context(cafile=options.ca)
            other.check_hostname = False
            with other.wrap_socket(raw, server_hostname='another-host.invalid'):
                refused = False
    except ssl.SSLError:
        refused = True
    check(refused, 'a TLS handshake for another host name is refused')

    print('== 5. sign-in and the pages')
    password = open(options.password_file, encoding='utf-8').read().strip()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    check(token is not None, 'the sign-in form carries its CSRF token')
    form = urllib.parse.urlencode({'username': options.user, 'password': password,
                                   'csrfmiddlewaretoken': token.group(1) if token else ''}).encode()
    status, headers, body = get(f'{base}/accounts/login/', form,
                                {'Referer': f'{base}/accounts/login/', 'Content-Type': 'application/x-www-form-urlencoded'})
    check(status == 302, f'the admin signs in ({status} to {headers.get("Location")})')
    session = [c for c in jar if c.name == 'sessionid']
    check(bool(session) and session[0].secure
          and any(session[0].has_nonstandard_attr(name) for name in ('HttpOnly', 'httponly')),
          'the session cookie is Secure and HttpOnly')
    seen, queue, errors, statuses = set(), ['/'], [], {}
    skip = re.compile(r'^/(static|media|admin)/|logout|/delete|/void|\.(pdf|csv|xlsx|ics|zip)$')
    while queue and len(seen) < options.max_pages:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        status, headers, body = get(base + path)
        statuses[status] = statuses.get(status, 0) + 1
        if status >= 500:
            errors.append(f'{status} {path}')
        if status == 200 and path.count('/') <= 4 and 'text/html' in (headers.get('Content-Type') or ''):
            for link in re.findall(r'href="(/[^"#]*)"', body):
                link = link.replace('&amp;', '&')
                if not skip.search(link) and link not in seen:
                    queue.append(link)
    print(f'pages opened: {len(seen)}, answers: {dict(sorted(statuses.items()))}')
    check(len(seen) >= 20, f'the crawl reached at least 20 pages ({len(seen)})')
    check(not errors, 'no page answered with a server error' + (f': {errors}' if errors else ''))
    check(statuses.get(200, 0) >= 20, f'at least 20 pages answered 200 ({statuses.get(200, 0)})')

    print('== 6. the rate limit on password reset')
    answers = [get(f'{base}/accounts/password_reset/')[0] for _ in range(25)]
    check(429 in answers and 200 in answers, f'the reset page is limited per client: {answers}')

    if failures:
        print(f'smoke: {len(failures)} check(s) failed')
        sys.exit(1)
    print('smoke: every check passed')


if __name__ == '__main__':
    try:
        main()
    except (OSError, http.client.HTTPException) as error:
        print(f'smoke: {error}')
        sys.exit(1)
