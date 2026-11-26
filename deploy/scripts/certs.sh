#!/bin/sh
# The TLS files of one farm's server, made locally with openssl into SECRETS_DIR (never into git; docs/ops/access.md).
#
#   certs.sh mqtt-ca                      the farm's MQTT certificate authority: mqtt/ca.crt (given to the broker and
#                                         to every device), mqtt-ca/ca.key (signs; keep it off the server once the
#                                         devices have their certificates)
#   certs.sh mqtt-server NAME...          the broker's certificate for the names and addresses the devices connect to
#                                         (the VPN address, a DNS name): mqtt/server.crt, mqtt/server.key
#   certs.sh mqtt-device DEVICE           a device's client certificate (MQTT_DEVICE_AUTH=clientcert), common name
#                                         DEVICE (its broker user, the Credential's username on the Sensors pages):
#                                         mqtt-devices/DEVICE/{client.crt,client.key,ca.crt}, to be loaded into the
#                                         device and then removed from here
#   certs.sh proxy-internal HOST          a certificate for the web proxy from a farm-internal CA (proxy-ca/), for a
#                                         console reached over the VPN only, or a test: tls/fullchain.pem,
#                                         tls/privkey.pem, and proxy-ca/ca.crt to install in the browsers. With public
#                                         DNS use Let's Encrypt (DNS-01) or a Cloudflare origin certificate instead
#                                         and put the same two files in tls/ (docs/ops/access.md).
#
# Keys are ECDSA P-256; certificates live 825 days (devices and servers), CAs 10 years. Nothing is overwritten:
# remove a file first to make it again (a new CA means new certificates for every device).
set -eu
DIR=${SECRETS_DIR:-$(dirname "$0")/../secrets}
command -v openssl > /dev/null || { echo "openssl is needed" >&2; exit 1; }
umask 077
mkdir -p "$DIR"
chmod 0700 "$DIR"

fresh() { for f in "$@"; do [ ! -e "$f" ] || { echo "$f exists: remove it first to make it again" >&2; exit 1; }; done; }
key() { openssl ecparam -name prime256v1 -genkey -noout -out "$1"; }
ca() {  # ca CERT KEY NAME
  fresh "$1" "$2"
  mkdir -p "$(dirname "$1")" "$(dirname "$2")"
  key "$2"
  openssl req -new -x509 -sha256 -days 3650 -key "$2" -out "$1" -subj "/CN=$3" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign"
}
sign() {  # sign CSR CACERT CAKEY OUT EXTFILE
  openssl x509 -req -sha256 -days 825 -in "$1" -CA "$2" -CAkey "$3" -CAcreateserial -out "$4" -extfile "$5"
  rm -f "$1" "$5" "${2%.crt}.srl"
}
san() {  # san NAME...: subjectAltName entries, an address as IP, anything else as DNS
  out=""
  for name in "$@"; do
    case "$name" in *[!0-9.]*) entry="DNS:$name" ;; *) entry="IP:$name" ;; esac
    out="${out:+$out,}$entry"
  done
  echo "$out"
}
readable() { chmod 0444 "$@"; }

case "${1:-}" in
  mqtt-ca)
    ca "$DIR/mqtt/ca.crt" "$DIR/mqtt-ca/ca.key" "farm MQTT CA"
    readable "$DIR/mqtt/ca.crt"
    echo "made mqtt/ca.crt and mqtt-ca/ca.key" ;;
  mqtt-server)
    shift
    [ $# -ge 1 ] || { echo "usage: certs.sh mqtt-server NAME..." >&2; exit 2; }
    fresh "$DIR/mqtt/server.crt" "$DIR/mqtt/server.key"
    key "$DIR/mqtt/server.key"
    openssl req -new -key "$DIR/mqtt/server.key" -out "$DIR/mqtt/server.csr" -subj "/CN=$1"
    printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature\n' "$(san "$@")" \
      > "$DIR/mqtt/server.ext"
    sign "$DIR/mqtt/server.csr" "$DIR/mqtt/ca.crt" "$DIR/mqtt-ca/ca.key" "$DIR/mqtt/server.crt" "$DIR/mqtt/server.ext"
    readable "$DIR/mqtt/server.crt" "$DIR/mqtt/server.key"
    echo "made mqtt/server.crt for $*" ;;
  mqtt-device)
    [ $# = 2 ] || { echo "usage: certs.sh mqtt-device DEVICE" >&2; exit 2; }
    case "$2" in *[!A-Za-z0-9_.@-]*|'') echo "a device name holds letters, digits, _ . @ - only" >&2; exit 2 ;; esac
    out=$DIR/mqtt-devices/$2
    fresh "$out/client.crt"
    mkdir -p "$out"
    key "$out/client.key"
    openssl req -new -key "$out/client.key" -out "$out/client.csr" -subj "/CN=$2"
    printf 'extendedKeyUsage=clientAuth\nkeyUsage=critical,digitalSignature\n' > "$out/client.ext"
    sign "$out/client.csr" "$DIR/mqtt/ca.crt" "$DIR/mqtt-ca/ca.key" "$out/client.crt" "$out/client.ext"
    cp "$DIR/mqtt/ca.crt" "$out/ca.crt"
    readable "$out/client.crt" "$out/client.key" "$out/ca.crt"
    echo "made mqtt-devices/$2: load client.crt, client.key and ca.crt into the device, then remove the folder" ;;
  proxy-internal)
    [ $# = 2 ] || { echo "usage: certs.sh proxy-internal HOST" >&2; exit 2; }
    [ -e "$DIR/proxy-ca/ca.crt" ] || ca "$DIR/proxy-ca/ca.crt" "$DIR/proxy-ca/ca.key" "farm console CA"
    fresh "$DIR/tls/fullchain.pem" "$DIR/tls/privkey.pem"
    mkdir -p "$DIR/tls"
    key "$DIR/tls/privkey.pem"
    openssl req -new -key "$DIR/tls/privkey.pem" -out "$DIR/tls/server.csr" -subj "/CN=$2"
    printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature\n' "$(san "$2")" \
      > "$DIR/tls/server.ext"
    sign "$DIR/tls/server.csr" "$DIR/proxy-ca/ca.crt" "$DIR/proxy-ca/ca.key" "$DIR/tls/server.crt" "$DIR/tls/server.ext"
    cat "$DIR/tls/server.crt" "$DIR/proxy-ca/ca.crt" > "$DIR/tls/fullchain.pem"
    rm -f "$DIR/tls/server.crt"
    readable "$DIR/tls/fullchain.pem" "$DIR/tls/privkey.pem" "$DIR/proxy-ca/ca.crt"
    echo "made tls/fullchain.pem for $2; install proxy-ca/ca.crt in the browsers that open it" ;;
  *)
    echo "usage: certs.sh mqtt-ca | mqtt-server NAME... | mqtt-device DEVICE | proxy-internal HOST" >&2
    exit 2 ;;
esac
