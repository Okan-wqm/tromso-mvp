"""S0f spike: a Mosquitto 2.x password-file line ($7$, PBKDF2-SHA512) computed with Python hashlib only.

Run: python s0f_mosquitto_hash.py            (offline check against lines made by mosquitto_passwd 2.0.20)
     python s0f_mosquitto_hash.py line USER PASSWORD   (prints one passwd line, used by s0f_live.sh)

The format (mosquitto 2.0.20, src/password_mosq.c): USER:$7$ITERATIONS$BASE64(SALT 12 bytes)$BASE64(PBKDF2-HMAC-SHA512
(password, salt, ITERATIONS, 64 bytes)). Standard base64 with padding. mosquitto_passwd uses 101 iterations by default
(-I changes it); the broker reads the iteration count from the line, so a higher count is accepted.
"""
import base64
import hashlib
import hmac
import os
import sys

ITERATIONS = 101  # mosquitto_passwd's default; the broker accepts any count written in the line.
SALT_LEN = 12
HASH_LEN = 64


def mosquitto_hash(password, salt=None, iterations=ITERATIONS):
    salt = os.urandom(SALT_LEN) if salt is None else salt
    digest = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, iterations, HASH_LEN)
    return '$7$%d$%s$%s' % (iterations, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify(password, encoded):
    kind, iterations, salt, digest = encoded.split('$')[1:]
    assert kind == '7', kind
    mine = mosquitto_hash(password, base64.b64decode(salt), int(iterations))
    return hmac.compare_digest(mine, encoded)


# Lines written by `mosquitto_passwd -b` of eclipse-mosquitto:2.0.20 (the second with -I 1000).
VECTORS = [
    ('sim', 's3cret-Pw',
     '$7$101$eNpewiJraEJc6yAU$FA/w3SuMmL8poIy/iwcWjnlXtjIl+310YExJ7J5vkS3urYVSaj0T/Q+MkNVuVkFnTxGOueGZ5hEmw/pDndsEiA=='),
    ('sim2', 'other',
     '$7$1000$TUEUhm33aWhXAH0Q$sZUYlKoPiSEgVPDnUK4Kv+MER3b3he4BofDSlw4hUfkF7dJcUJ50zNibb9ECKvYvk/RwFo/q4ocaTmOIr0FKYQ=='),
]

if __name__ == '__main__':
    if sys.argv[1:2] == ['line']:
        print('%s:%s' % (sys.argv[2], mosquitto_hash(sys.argv[3])))
        sys.exit(0)
    for user, password, encoded in VECTORS:
        assert verify(password, encoded), user
        assert not verify(password + 'x', encoded), user
    print('PASS: hashlib reproduces mosquitto_passwd 2.0.20 $7$ lines (101 and 1000 iterations)')
