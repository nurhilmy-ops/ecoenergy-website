#!/usr/bin/env bash
# EcoEnergy terrain screening tool: one-command server setup for Amazon Lightsail
# (Ubuntu 24.04 LTS or 22.04 LTS, "OS Only" blueprint). Paste into the Lightsail browser SSH window:
#
#   curl -fsSL https://raw.githubusercontent.com/nurhilmy-ops/ecoenergy-website/main/terrain-tool/deploy/aws-lightsail/setup.sh | sudo bash
#
# Before the pull request is merged into main, install from its branch instead:
#
#   curl -fsSL https://raw.githubusercontent.com/nurhilmy-ops/ecoenergy-website/claude/admiring-albattani-j1beqs/terrain-tool/deploy/aws-lightsail/setup.sh | sudo TOOL_REF=claude/admiring-albattani-j1beqs bash
#
# Optional settings (environment variables, e.g. `sudo TOOL_DOMAIN=... bash`):
#   TOOL_REF     git branch or tag to install. Default: the one installed last time, else main.
#   TOOL_DOMAIN  public address of the tool. Default: the one installed last time, else
#                tools.ecoconsultancy.services.
#   TOOL_REPO    git repository. Default: the one installed from last time, else the public
#                GitHub repository. (Tests point it at a local copy.)
#
# Running it again is safe and is how the server is updated (`sudo terrain-tool update` does it):
# it fetches the code again, installs what changed and restarts the tool. Settings and secrets
# in /etc/terrain-tool/terrain-tool.env are kept; only missing settings are added.
#
# What it does: Ubuntu packages and automatic security updates; 2 GB swap if there is none; a
# system user "terrain"; the code in /opt/terrain-tool/src (only the terrain-tool folder of the
# repository); a Python environment in /opt/terrain-tool/venv; data in /var/lib/terrain-tool;
# the settings file with fresh random secrets; the systemd service; Caddy (HTTPS) from Caddy's
# official apt repository; a nightly database backup (14 days kept); a size cap on the system
# log; then it starts everything, waits until the tool answers and prints a summary.

set -Eeuo pipefail
shopt -u patsub_replacement 2>/dev/null || true    # bash 5.2: keep "&" literal in ${var//x/y}
umask 022                                           # code and venv readable by the app user

readonly DEFAULT_REPO=https://github.com/nurhilmy-ops/ecoenergy-website.git
readonly DEFAULT_DOMAIN=tools.ecoconsultancy.services
readonly APP_USER=terrain
readonly BASE=/opt/terrain-tool
readonly SRC=$BASE/src
readonly APP_DIR=$SRC/terrain-tool
readonly KIT_DIR=$APP_DIR/deploy/aws-lightsail
readonly VENV=$BASE/venv
readonly DATA_DIR=/var/lib/terrain-tool
readonly ETC_DIR=/etc/terrain-tool
readonly ENV_FILE=$ETC_DIR/terrain-tool.env
readonly REF_FILE=$ETC_DIR/ref
readonly SWAPFILE=/swapfile
readonly SWAP_MB=2048
readonly HEALTH_URL=http://127.0.0.1:8000/healthz
readonly CADDY_KEYRING=/usr/share/keyrings/caddy-stable-archive-keyring.gpg
readonly CADDY_LIST=/etc/apt/sources.list.d/caddy-stable.list
readonly LOG=/var/log/terrain-tool-setup.log      # full output of apt, for when something fails

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a                  # never stop to ask which services to restart
export PIP_DISABLE_PIP_VERSION_CHECK=1
export GIT_TERMINAL_PROMPT=0               # a wrong repository fails instead of asking for a password
export LC_ALL=C.UTF-8

STEP="starting"
DONE=()

step() { STEP=$1; printf '\n==> %s\n' "$1"; }
ok() { printf '    %s\n' "$*"; }
warn() { printf '    NOTE: %s\n' "$*" >&2; }
did() { DONE+=("$*"); }

die() {
  printf '\nSETUP STOPPED: %s\n' "$*" >&2
  exit 1
}

# shellcheck disable=SC2329  # called by the ERR trap
on_error() {
  local rc=$? line=$1
  printf '\nSETUP FAILED during "%s" (setup.sh line %s, exit code %s).\n' "$STEP" "$line" "$rc" >&2
  printf 'Nothing is lost: run the same command again to retry. If it fails again, copy the\n' >&2
  printf 'messages above (the full log is in %s) and send them to whoever maintains the tool.\n' "$LOG" >&2
  exit "$rc"
}
trap 'on_error $LINENO' ERR

apt_get() {
  # Waits (up to 10 minutes) while Ubuntu's own updates hold the package lock on a new server.
  # The (long) output goes to the log; on failure its end is shown.
  printf '\n### apt-get %s (%s)\n' "$*" "$(date -u +%FT%TZ)" >>"$LOG"
  if ! apt-get -q -y -o DPkg::Lock::Timeout=600 -o Dpkg::Options::=--force-confdef \
      -o Dpkg::Options::=--force-confold "$@" </dev/null >>"$LOG" 2>&1; then
    tail -n 25 "$LOG" >&2
    return 1
  fi
}

# ---------------------------------------------------------------------------------------------
# Checks and settings
# ---------------------------------------------------------------------------------------------

check_system() {
  # The OS is checked first so the message is right even without sudo.
  local os_release=${TT_OS_RELEASE:-/etc/os-release}    # TT_OS_RELEASE: tests only
  local id="" version="" pretty="an unknown system"
  if [[ -r $os_release ]]; then
    # shellcheck source=/dev/null
    id=$(. "$os_release" && printf '%s' "${ID:-}")
    # shellcheck source=/dev/null
    version=$(. "$os_release" && printf '%s' "${VERSION_ID:-}")
    # shellcheck source=/dev/null
    pretty=$(. "$os_release" && printf '%s' "${PRETTY_NAME:-$ID $VERSION_ID}")
  fi
  if [[ $id != ubuntu || ( $version != 24.04 && $version != 22.04 ) ]]; then
    die "This setup is for Ubuntu 24.04 LTS (or 22.04 LTS) only, but this server runs ${pretty}.
Create the Lightsail instance with Linux/Unix > OS Only > Ubuntu 24.04 LTS and run it there."
  fi
  if [[ $EUID -ne 0 ]]; then
    die "It needs administrator rights. Put sudo in front of bash, like this:
  curl -fsSL <the setup.sh address> | sudo bash"
  fi
  if [[ $version == 22.04 ]]; then
    PYTHON=python3.11            # the tool needs Python 3.11 or newer; 22.04's python3 is 3.10
    PYTHON_PACKAGES=(python3.11 python3.11-venv)
  else
    PYTHON=python3
    PYTHON_PACKAGES=(python3 python3-venv)
  fi
}

env_value() {   # value of KEY in the settings file (empty if absent)
  [[ -r $ENV_FILE ]] || return 0
  awk -v k="$1" 'index($0, k "=") == 1 { v = substr($0, length(k) + 2) } END { print v }' "$ENV_FILE"
}

resolve_settings() {
  if [[ -z ${TOOL_REPO:-} ]]; then
    TOOL_REPO=$(git -C "$SRC" remote get-url origin 2>/dev/null || true)
    TOOL_REPO=${TOOL_REPO:-$DEFAULT_REPO}
  fi
  if [[ -z ${TOOL_REF:-} ]]; then
    TOOL_REF=$(head -n 1 "$REF_FILE" 2>/dev/null || true)
    TOOL_REF=${TOOL_REF:-main}
  fi
  if [[ -z ${TOOL_DOMAIN:-} ]]; then
    local base
    base=$(env_value BASE_URL)
    base=${base#https://}; base=${base#http://}; base=${base%%/*}
    TOOL_DOMAIN=${base:-$DEFAULT_DOMAIN}
  fi
  TOOL_DOMAIN=${TOOL_DOMAIN,,}
  [[ $TOOL_REF =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ && $TOOL_REF != *..* ]] \
    || die "TOOL_REF '$TOOL_REF' is not a valid branch or tag name."
  [[ $TOOL_DOMAIN =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] \
    || die "TOOL_DOMAIN '$TOOL_DOMAIN' is not a valid host name (example: $DEFAULT_DOMAIN)."
  export TOOL_REPO TOOL_REF TOOL_DOMAIN
}

take_lock() {
  # One setup at a time (e.g. if the command was pasted twice). The re-started second stage
  # inherits the lock on file descriptor 9.
  [[ ${TT_SETUP_STAGE:-1} == 2 ]] && return 0
  exec 9>/run/terrain-tool-setup.lock
  flock -n 9 || die "Setup is already running (in another window?). Wait for it to finish."
}

# ---------------------------------------------------------------------------------------------
# Stage 1: get the code, then continue with the setup.sh that came with it
# ---------------------------------------------------------------------------------------------

install_git() {
  step "Preparing Ubuntu (package lists, git)"
  apt_get update
  apt_get install --no-install-recommends git ca-certificates curl
}

no_kit() {
  die "'$TOOL_REF' does not contain the server kit (terrain-tool/deploy/aws-lightsail) yet.
Until the pull request is merged, install from its branch: put TOOL_REF=claude/admiring-albattani-j1beqs
after sudo (see the kit's README, Part D). If you did, the kit has not been pushed to that branch yet."
}

has_kit() {   # does commit $2 of the repository in $1 contain the kit? (reads trees only)
  [[ -n $(git -C "$1" ls-tree --name-only "$2" terrain-tool/deploy/aws-lightsail/setup.sh 2>/dev/null) ]]
}

fetch_source() {
  step "Downloading the tool ($TOOL_REF)"
  local failed="Could not download '$TOOL_REF' from $TOOL_REPO. Check the branch or tag name (it is case-sensitive) and the server's internet connection."
  mkdir -p "$BASE" "$ETC_DIR"
  if [[ -d $SRC/.git ]]; then
    local old_url
    old_url=$(git -C "$SRC" remote get-url origin 2>/dev/null || true)
    git -C "$SRC" remote set-url origin "$TOOL_REPO"
    # Check before switching, so a wrong name leaves the installed version untouched.
    if ! git -C "$SRC" fetch --quiet --depth 1 origin "$TOOL_REF"; then
      git -C "$SRC" remote set-url origin "${old_url:-$TOOL_REPO}"
      die "$failed"
    fi
    if ! has_kit "$SRC" FETCH_HEAD; then
      git -C "$SRC" remote set-url origin "${old_url:-$TOOL_REPO}"
      no_kit
    fi
    git -C "$SRC" sparse-checkout set terrain-tool
    git -C "$SRC" checkout --quiet --force --detach FETCH_HEAD
    git -C "$SRC" clean -ffdxq
  else
    rm -rf "$SRC" "$SRC.new"
    git clone --quiet --depth 1 --filter=blob:none --sparse --branch "$TOOL_REF" "$TOOL_REPO" "$SRC.new" \
      || die "$failed"
    if ! has_kit "$SRC.new" HEAD; then
      rm -rf "$SRC.new"
      no_kit
    fi
    git -C "$SRC.new" sparse-checkout set terrain-tool
    mv "$SRC.new" "$SRC"
  fi
  printf '%s\n' "$TOOL_REF" >"$REF_FILE"
  ok "Code: $TOOL_REF at commit $(git -C "$SRC" log -1 --format='%h (%cd)' --date=short)"
}

# ---------------------------------------------------------------------------------------------
# Stage 2: configure the server (always the setup.sh of the version just downloaded)
# ---------------------------------------------------------------------------------------------

install_packages() {
  step "Installing Ubuntu packages"
  [[ ${TT_APT_UPDATED:-} == 1 ]] || apt_get update
  apt_get install --no-install-recommends git ca-certificates curl gnupg debian-keyring \
    debian-archive-keyring apt-transport-https unattended-upgrades tzdata libexpat1 \
    "${PYTHON_PACKAGES[@]}"
  install -m 0644 "$KIT_DIR/unattended-upgrades.conf" /etc/apt/apt.conf.d/52terrain-tool-upgrades
  ok "Automatic security updates: on (restart at 03:30 Malaysia time only when an update needs it)"
  did "Ubuntu packages installed and up to date; automatic security updates on"
}

setup_swap() {
  step "Swap space (extra memory on disk)"
  local active
  active=$(swapon --show=NAME --noheadings 2>/dev/null || true)
  if [[ -n $active ]]; then
    ok "Swap already on: $(echo "$active" | tr '\n' ' ')"
  else
    local size_mb=0
    [[ -f $SWAPFILE ]] && size_mb=$(( $(stat -c %s "$SWAPFILE") / 1048576 ))
    if (( size_mb < SWAP_MB )); then
      fallocate -l "${SWAP_MB}M" "$SWAPFILE" 2>/dev/null \
        || dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SWAP_MB" status=none
    fi
    chmod 600 "$SWAPFILE"
    mkswap -f "$SWAPFILE" >/dev/null
    if swapon "$SWAPFILE" 2>/dev/null; then
      ok "Created a ${SWAP_MB} MB swap file ($SWAPFILE)"
      did "2 GB swap file added"
    else
      warn "This system does not allow a swap file here (normal inside containers); continuing without swap."
      rm -f "$SWAPFILE"
    fi
  fi
  if swapon --show=NAME --noheadings 2>/dev/null | grep -qx "$SWAPFILE" \
      && ! grep -qE "^[[:space:]]*${SWAPFILE}[[:space:]]" /etc/fstab; then
    printf '%s none swap sw 0 0\n' "$SWAPFILE" >>/etc/fstab
    ok "Swap file will be turned on again after a restart (/etc/fstab)"
  fi
  printf '# Installed by the terrain tool setup: use swap only when memory is nearly full.\nvm.swappiness = 10\n' \
    >/etc/sysctl.d/90-terrain-tool.conf
  sysctl -q -w vm.swappiness=10 2>/dev/null || warn "Could not set vm.swappiness now; it applies after a restart."
}

create_user_and_dirs() {
  step "App user and folders"
  if ! id -u "$APP_USER" >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$DATA_DIR" --no-create-home \
      --shell /usr/sbin/nologin --comment "EcoEnergy terrain screening tool" "$APP_USER"
    ok "Created system user '$APP_USER' (no password, no login shell)"
    did "System user '$APP_USER' created"
  else
    ok "System user '$APP_USER' exists"
  fi
  mkdir -p "$DATA_DIR" "$DATA_DIR/backups" "$ETC_DIR" /usr/local/lib/terrain-tool
  chown "$APP_USER:$APP_USER" "$DATA_DIR" "$DATA_DIR/backups"
  chmod 0750 "$DATA_DIR"
  chmod 0700 "$DATA_DIR/backups"
  chown root:"$APP_USER" "$ETC_DIR"
  chmod 0750 "$ETC_DIR"
  ok "Data: $DATA_DIR (only '$APP_USER' can read it); settings: $ETC_DIR"
}

python_env() {
  step "Python environment (the first time this takes a few minutes)"
  local want have=""
  want=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  if [[ -x $VENV/bin/python ]]; then
    have=$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
  fi
  if [[ $have != "$want" ]]; then
    rm -rf "$VENV"
    "$PYTHON" -m venv "$VENV"
    ok "Created $VENV (Python $want)"
  fi
  "$VENV/bin/python" -m pip install --quiet --progress-bar off --upgrade pip
  # boto3: the Amazon SES API client (MAIL_BACKEND=ses). Ready-built wheels only where possible.
  "$VENV/bin/python" -m pip install --quiet --progress-bar off --prefer-binary \
    -r "$APP_DIR/requirements.txt" boto3
  "$VENV/bin/python" -c "import rasterio, pyproj, shapely, matplotlib, scipy, boto3, uvicorn, fastapi" \
    || die "The Python libraries did not install correctly (see the messages above)."
  "$VENV/bin/python" -m compileall -q "$APP_DIR/app" >/dev/null || true
  ok "Libraries installed: $("$VENV/bin/python" -m pip list --format=freeze 2>/dev/null | wc -l) packages"
  did "Python environment ready ($VENV)"
}

random_token() {   # URL-safe random string of about $1 characters (no characters that need quoting)
  "$PYTHON" -c "import secrets, string, sys; a = string.ascii_letters + string.digits; print(''.join(secrets.choice(a) for _ in range(int(sys.argv[1]))))" "$1"
}

write_settings() {
  step "Settings file ($ENV_FILE)"
  local template rendered
  template=$(<"$KIT_DIR/terrain-tool.env.template")
  rendered=${template//@TOOL_DOMAIN@/$TOOL_DOMAIN}
  rendered=${rendered//@SECRET_KEY@/$(random_token 64)}
  rendered=${rendered//@ADMIN_PASSWORD@/$(random_token 24)}
  if [[ ! -f $ENV_FILE ]]; then
    (umask 077 && printf '%s\n' "$rendered" >"$ENV_FILE.new")
    chown root:"$APP_USER" "$ENV_FILE.new"
    chmod 0640 "$ENV_FILE.new"
    mv -f "$ENV_FILE.new" "$ENV_FILE"
    ok "Created with a new random SECRET_KEY and admin password"
    did "Settings created: $ENV_FILE (secrets generated on this server)"
  else
    local line key added=()
    while IFS= read -r line; do
      [[ $line =~ ^([A-Z][A-Z0-9_]*)= ]] || continue
      key=${BASH_REMATCH[1]}
      if ! grep -q "^$key=" "$ENV_FILE"; then
        printf '# Added by setup.sh on %s\n%s\n' "$(date -u +%F)" "$line" >>"$ENV_FILE"
        added+=("$key")
      fi
    done <<<"$rendered"
    local current_base
    current_base=$(env_value BASE_URL)
    if [[ $current_base != "https://$TOOL_DOMAIN" ]]; then
      sed -i "s|^BASE_URL=.*|BASE_URL=https://$TOOL_DOMAIN|" "$ENV_FILE"
      ok "Address changed from $current_base to https://$TOOL_DOMAIN"
    fi
    chown root:"$APP_USER" "$ENV_FILE"
    chmod 0640 "$ENV_FILE"
    if ((${#added[@]})); then
      ok "Kept your settings; added missing: ${added[*]}"
    else
      ok "Kept your settings and secrets (nothing missing)"
    fi
  fi
}

install_service_files() {
  step "Services (app, nightly backup, log size)"
  install -m 0644 "$KIT_DIR/terrain-tool.service" /etc/systemd/system/terrain-tool.service
  install -m 0644 "$KIT_DIR/terrain-tool-backup.service" /etc/systemd/system/terrain-tool-backup.service
  install -m 0644 "$KIT_DIR/terrain-tool-backup.timer" /etc/systemd/system/terrain-tool-backup.timer
  install -m 0755 "$KIT_DIR/backup-db.py" /usr/local/lib/terrain-tool/backup-db.py
  # The admin helper: copy, then rename, so a `terrain-tool update` that is running keeps
  # reading its own (old) file.
  install -m 0755 "$KIT_DIR/terrain-tool" /usr/local/sbin/.terrain-tool.new
  mv -f /usr/local/sbin/.terrain-tool.new /usr/local/sbin/terrain-tool
  mkdir -p /etc/systemd/journald.conf.d
  if ! cmp -s "$KIT_DIR/journald-terrain-tool.conf" /etc/systemd/journald.conf.d/terrain-tool.conf; then
    install -m 0644 "$KIT_DIR/journald-terrain-tool.conf" /etc/systemd/journald.conf.d/terrain-tool.conf
    systemctl restart systemd-journald || warn "Could not restart the system log; the size cap applies after a restart."
  fi
  systemctl daemon-reload
  systemctl enable --quiet terrain-tool.service terrain-tool-backup.timer
  systemctl restart terrain-tool-backup.timer
  ok "terrain-tool.service, nightly backup timer, log cap 500 MB / 30 days, helper /usr/local/sbin/terrain-tool"
  did "Service terrain-tool installed (starts by itself after a restart); nightly backups at 02:30 Malaysia time"
}

install_caddy() {
  step "Caddy web server (HTTPS)"
  # https://caddyserver.com/docs/install#debian-ubuntu-raspbian
  if [[ ! -s $CADDY_KEYRING || ! -s $CADDY_LIST ]]; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | gpg --batch --yes --dearmor -o "$CADDY_KEYRING" \
      || die "Could not download Caddy's signing key from dl.cloudsmith.io."
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' >"$CADDY_LIST.new" \
      || die "Could not download Caddy's package list from dl.cloudsmith.io."
    mv -f "$CADDY_LIST.new" "$CADDY_LIST"
    chmod o+r "$CADDY_KEYRING" "$CADDY_LIST"
    apt_get update
  fi
  apt_get install caddy
  local new=/etc/caddy/Caddyfile.terrain-tool.new template
  template=$(<"$KIT_DIR/Caddyfile")
  printf '%s\n' "${template//@TOOL_DOMAIN@/$TOOL_DOMAIN}" >"$new"
  grep -q '@TOOL_DOMAIN@' "$new" && die "The Caddyfile template still has a placeholder."
  caddy validate --adapter caddyfile --config "$new" >/dev/null 2>"$new.log" || {
    cat "$new.log" >&2
    die "The web server configuration is not valid (see above)."
  }
  rm -f "$new.log"
  if [[ -f /etc/caddy/Caddyfile && ! -f /etc/caddy/Caddyfile.before-terrain-tool ]] \
      && ! grep -q 'terrain screening tool' /etc/caddy/Caddyfile; then
    cp -p /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-terrain-tool
  fi
  chmod 0644 "$new"
  mv -f "$new" /etc/caddy/Caddyfile
  systemctl enable --quiet caddy
  systemctl reload-or-restart caddy
  ok "Caddy $(caddy version 2>/dev/null | cut -d' ' -f1) serves https://$TOOL_DOMAIN and gets its certificate by itself"
  did "Caddy installed: https://$TOOL_DOMAIN -> the tool (certificate from Let's Encrypt, renewed automatically)"
}

start_app() {
  step "Starting the tool"
  systemctl restart terrain-tool.service
  local i
  for i in $(seq 1 90); do
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
      ok "The tool answers on $HEALTH_URL (after ${i} s)"
      return 0
    fi
    if ! systemctl is-active --quiet terrain-tool.service && ((i > 10)); then
      break
    fi
    sleep 1
  done
  journalctl -u terrain-tool.service -n 40 --no-pager >&2 || true
  die "The tool did not start (its last log lines are above). The previous settings are unchanged."
}

summary() {
  step "Summary"
  printf '\nDone. What was set up:\n'
  local item
  for item in "${DONE[@]}"; do printf '  - %s\n' "$item"; done
  printf '\n'
  /usr/local/sbin/terrain-tool status || true
  # The admin password is printed once, at the end of the first setup that completes.
  if [[ ! -f $ETC_DIR/.admin-password-shown ]]; then
    cat <<EOF

ADMIN PAGES: https://$TOOL_DOMAIN/admin
  user:     $(env_value ADMIN_USER)
  password: $(env_value ADMIN_PASSWORD)
Write the password down somewhere safe now (a password manager). It is shown only this
once; to see it again later run: sudo terrain-tool admin-password
EOF
    touch "$ETC_DIR/.admin-password-shown"
  else
    printf '\nAdmin pages: https://%s/admin (password: sudo terrain-tool admin-password)\n' "$TOOL_DOMAIN"
  fi
  if [[ $(env_value MAIL_BACKEND) == ses && -z $(env_value AWS_ACCESS_KEY_ID) ]]; then
    cat <<EOF

NEXT STEP (README Part E): connect email. In AWS, verify the domain in Amazon SES and create
the IAM user terrain-tool-ses with an access key, then run:
  sudo terrain-tool set-aws-keys
  sudo terrain-tool test-email you@example.com
EOF
  fi
  printf '\nEveryday commands: sudo terrain-tool help\n'
  if [[ -f /var/run/reboot-required ]]; then
    printf '\nUbuntu asks for a restart to finish an update: it happens by itself at 03:30 Malaysia time,\nor now with: sudo reboot\n'
  fi
}

main() {
  check_system
  take_lock
  touch "$LOG" && chmod 0600 "$LOG"
  resolve_settings
  if [[ ${TT_SETUP_STAGE:-1} != 2 ]]; then
    printf 'EcoEnergy terrain screening tool: server setup (%s, %s)\n' "$TOOL_REF" "$TOOL_DOMAIN"
    install_git
    fetch_source
    # Continue with the setup.sh that belongs to the code just downloaded, so an update
    # always runs the matching, newest steps.
    exec env TT_SETUP_STAGE=2 TT_APT_UPDATED=1 bash "$KIT_DIR/setup.sh" </dev/null
  fi
  install_packages
  setup_swap
  create_user_and_dirs
  python_env
  write_settings
  install_service_files
  install_caddy
  start_app
  summary
}

main "$@"; exit $?
