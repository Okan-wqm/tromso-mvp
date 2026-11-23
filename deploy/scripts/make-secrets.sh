#!/bin/sh
# Makes the secret files of one farm's server (docs/ops/install.md, docs/ops/rotate-secrets.md) in SECRETS_DIR
# (default deploy/secrets, which git ignores; on a real server a folder outside the checkout, e.g.
# /etc/balik/<farm>/secrets). Only what is missing is made: an existing file is never overwritten, so running it again
# is safe. Nothing is printed but the names.
#
#   SECRETS_DIR=/etc/balik/farm-a/secrets sh deploy/scripts/make-secrets.sh
#
# Random (openssl rand): the database roles' passwords (postgres, balik_owner, balik_app, sensors_ingest,
# balik_backup), DJANGO_SECRET_KEY, DJANGO_AUDIT_DIGEST_KEY, the backup repository's password (restic: KEEP A COPY
# OFF THE SERVER, without it no backup can be read), the ingest's MQTT password and its broker line
# (mqtt_passwd_extra, the hash Mosquitto keeps, made with the broker's own mosquitto_passwd in its image).
# Left for a person to fill in: email_password (the SMTP account's, empty when the server takes no sign-in),
# backup-ca.crt (the backup REST server's CA certificate, empty when its certificate is a public one),
# backup.env (the repository's access keys, if any), cloudflared.env (the tunnel's token, Cloudflare only).
# The TLS files are certs.sh's.
#
# Modes: the folder 0700 (only root on the host reaches it), each file 0444, because each container reads its own as
# its own user (postgres, the web user, mosquitto) and sees nothing else of the folder.
set -eu
DIR=${SECRETS_DIR:-$(dirname "$0")/../secrets}
MQTT_INGEST_USER=${MQTT_INGEST_USER:-ingest}
MOSQUITTO_IMAGE=eclipse-mosquitto:2.0.23@sha256:6a332cc7a8dbe011cbc076180cbb76b37c6f0f55809682ea08e7980ef0112ad9
command -v openssl > /dev/null || { echo "openssl is needed" >&2; exit 1; }
umask 077
mkdir -p "$DIR"
chmod 0700 "$DIR"

made() { chmod 0444 "$DIR/$1"; echo "made $1"; }
random() {  # random NAME BYTES: a random value without characters a shell, a URL or a libpq string treats specially
  [ -e "$DIR/$1" ] && { echo "kept $1"; return 0; }
  openssl rand -base64 "$(( $2 * 2 ))" | tr -d '\n+/=' | cut -c1-"$(( $2 * 4 / 3 ))" > "$DIR/$1"
  [ "$(wc -c < "$DIR/$1")" -ge 32 ] || { echo "openssl gave too little for $1" >&2; rm -f "$DIR/$1"; exit 1; }
  made "$1"
}
template() {  # template NAME TEXT: a file a person fills in
  [ -e "$DIR/$1" ] && { echo "kept $1"; return 0; }
  printf '%s' "$2" > "$DIR/$1"
  made "$1"
  echo "  fill in $DIR/$1"
}

random postgres_password 32
random db_owner_password 32
random db_app_password 32
random db_ingest_password 32
random db_backup_password 32
random django_secret_key 48
random django_audit_digest_key 48
random restic_password 48
random mqtt_ingest 32

if [ -e "$DIR/mqtt_passwd_extra" ]; then
  echo "kept mqtt_passwd_extra"
else
  # The ingest's broker user, as Mosquitto keeps it ($7$, PBKDF2-SHA512), made by mosquitto_passwd in the broker's own
  # image; the password reaches it on stdin, never on a command line.
  docker run --rm -i --network none -e USER_NAME="$MQTT_INGEST_USER" --entrypoint sh "$MOSQUITTO_IMAGE" -c '
    read -r password
    mosquitto_passwd -c -b /tmp/passwd "$USER_NAME" "$password" > /dev/null 2>&1
    cat /tmp/passwd' < "$DIR/mqtt_ingest" > "$DIR/mqtt_passwd_extra"
  grep -q "^$MQTT_INGEST_USER:[$]7[$]" "$DIR/mqtt_passwd_extra" || { echo "mosquitto_passwd failed" >&2; rm -f "$DIR/mqtt_passwd_extra"; exit 1; }
  made mqtt_passwd_extra
fi

template email_password ''
template backup.env '# The backup repository'"'"'s access, read by the backup and restore services (docs/ops/backup-and-restore.md).
# A restic REST server in append-only mode (the recommended target): the farm user there, which may add only.
# RESTIC_REST_USERNAME=
# RESTIC_REST_PASSWORD=
# S3-compatible storage:
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
# AWS_DEFAULT_REGION=
# SFTP: an ssh key and known_hosts are mounted instead (docs/ops/backup-and-restore.md).
'
template backup-ca.crt ''
template cloudflared.env '# Cloudflare Tunnel only (docs/ops/access.md): the token of the tunnel made in the Zero Trust dashboard.
# TUNNEL_TOKEN=
'
echo "secrets in $DIR (folder 0700, files 0444). Copy restic_password and django_audit_digest_key to the owner's safe."
