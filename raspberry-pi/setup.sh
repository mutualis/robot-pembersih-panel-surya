#!/bin/bash
# ============================================================================
# setup.sh — Setup Produksi Raspberry Pi (Solar Panel Cleaning Robot)
# ============================================================================
# SATU script untuk seluruh setup. Idempoten (aman dijalankan berulang).
# Menggabungkan: dependensi, WiFi AP+Client, izin kontrol web, dan service
# auto-start. Sudah membawa semua perbaikan stabilitas WiFi Pi 5.
#
# Pakai:
#   sudo bash setup.sh            # setup penuh (default)
#   sudo bash setup.sh wifi       # hanya WiFi AP+Client
#   sudo bash setup.sh perms      # hanya izin kontrol web (polkit+sudoers)
#   sudo bash setup.sh service    # hanya install service auto-start
#   sudo bash setup.sh deps       # hanya dependensi (apt + venv + pip)
#
# Setelah setup penuh: WAJIB reboot (sudo reboot) agar workaround driver
# WiFi aktif.
#
# Author: Muhammad Ridho Assidiqi — UGM Sekolah Vokasi (TRIK)
# ============================================================================

set -e

# ----------------------------------------------------------------------------
# KONFIGURASI (ubah di sini bila perlu)
# ----------------------------------------------------------------------------
AP_SSID="SolarPanelCleaner"        # nama WiFi hotspot robot
AP_PASS="solarpanel123"            # password hotspot (8-63 karakter)
AP_IP="192.168.50.1"               # IP statis AP
AP_CHANNEL_DEFAULT="1"             # fallback bila channel wlan0 tak terdeteksi
DHCP_START="192.168.50.50"
DHCP_END="192.168.50.199"
WEB_PORT="5000"

# Domain akses web (HTTPS via Caddy). SATU domain dipakai di semua kondisi:
#  - DOMAIN     : domain utama (asli, dikelola Cloudflare). Dipakai online
#                 (Cloudflare Tunnel) maupun lokal/AP (split-horizon DNS → AP_IP).
#  - AP_HOSTNAME: nama mDNS bonus untuk LAN/WiFi rumah → <hostname>.local
DOMAIN="wipevision.my.id"
AP_HOSTNAME="wipevision"

# Cloudflare API token untuk penerbitan sertifikat Let's Encrypt via DNS-01.
# Token TIDAK ditulis di script ini. Buat file env berisi: CF_API_TOKEN=xxxx
# (lihat cloudflare.env.example). Bila file tidak ada → fallback ke CA internal.
CF_TOKEN_FILE="/etc/caddy/cloudflare.env"

# Deteksi user & lokasi otomatis
APP_USER="${SUDO_USER:-$(whoami)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
VENV_DIR="${PROJECT_DIR}/venv"

CLIENT_IFACE="wlan0"
AP_IFACE="uap0"
LAN_IFACE="eth0"
HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
CMDLINE="/boot/firmware/cmdline.txt"
[ -f "${CMDLINE}" ] || CMDLINE="/boot/cmdline.txt"

# ----------------------------------------------------------------------------
# Helper
# ----------------------------------------------------------------------------
require_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "ERROR: jalankan dengan sudo → sudo bash setup.sh"
        exit 1
    fi
}

hr()    { echo "=========================================="; }
title() { hr; echo " $1"; hr; }

# Deteksi channel wlan0 saat ini (agar AP seuchannel — WAJIB di mode AP+STA).
detect_ap_channel() {
    local freq ch
    freq=$(iw dev "${CLIENT_IFACE}" link 2>/dev/null | awk '/freq:/ {print $2}' | head -1)
    if [ -n "${freq}" ]; then
        # 2.4GHz: channel = (freq - 2407) / 5
        ch=$(awk "BEGIN { f=${freq}; if (f>=2412 && f<=2472) print int((f-2407)/5); else print 0 }")
    fi
    if [ -z "${ch}" ] || [ "${ch}" -le 0 ]; then
        ch="${AP_CHANNEL_DEFAULT}"
    fi
    echo "${ch}"
}

# ============================================================================
# STEP: DEPENDENSI (apt + venv + pip)
# ============================================================================
do_deps() {
    title "[DEPS] Dependensi sistem & Python"

    echo "[1/3] apt: hostapd, dnsmasq, avahi-daemon, iptables-persistent..."
    apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        hostapd dnsmasq avahi-daemon netfilter-persistent iptables-persistent \
        python3-venv python3-pip iw rfkill

    echo "[2/3] Membuat virtualenv di ${VENV_DIR}..."
    if [ ! -d "${VENV_DIR}" ]; then
        sudo -u "${APP_USER}" python3 -m venv "${VENV_DIR}"
    fi

    echo "[3/3] Install requirements.txt..."
    if [ -f "${PROJECT_DIR}/requirements.txt" ]; then
        sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip
        sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"
    else
        echo "  (requirements.txt tidak ditemukan, lewati)"
    fi
    echo "[DEPS] selesai."
    echo ""
}

# ============================================================================
# STEP: WIFI AP + CLIENT (dual mode, sudah anti-bug Pi 5)
# ============================================================================
do_wifi() {
    title "[WIFI] AP '${AP_SSID}' + Client (dual mode)"

    # --- Cek dukungan interface virtual AP ---
    echo "[1/8] Cek dukungan AP virtual..."
    if iw dev "${CLIENT_IFACE}" interface add "${AP_IFACE}" type __ap 2>/dev/null; then
        echo "  OK — chip mendukung AP+STA."
        iw dev "${AP_IFACE}" del 2>/dev/null || true
    else
        echo "  PERINGATAN: gagal membuat ${AP_IFACE}. Lanjut — service akan coba saat boot."
    fi

    # --- Channel mengikuti wlan0 (WAJIB di mode AP+STA satu radio) ---
    AP_CHANNEL="$(detect_ap_channel)"
    echo "[2/8] Channel AP = ${AP_CHANNEL} (mengikuti ${CLIENT_IFACE})."

    # --- hostapd.conf LENGKAP (channel eksplisit, TANPA ACS) ---
    echo "[3/8] Menulis ${HOSTAPD_CONF}..."
    cat > "${HOSTAPD_CONF}" << EOF
# WipeVision AP — auto-generated oleh setup.sh
# channel DIPAKSA (tanpa ACS): brcmfmac Pi 5 tidak bisa survey channel,
# dan pada mode AP+STA channel HARUS sama dengan ${CLIENT_IFACE}.
ctrl_interface=/var/run/hostapd
interface=${AP_IFACE}
driver=nl80211
country_code=ID
ssid=${AP_SSID}
hw_mode=g
channel=${AP_CHANNEL}
ieee80211n=1
wmm_enabled=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${AP_PASS}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF
    chmod 600 "${HOSTAPD_CONF}"
    sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || true
    echo "  OK"

    # --- dnsmasq (DHCP + DNS lokal untuk klien AP) ---
    echo "[4/8] Menulis /etc/dnsmasq.conf..."
    [ -f /etc/dnsmasq.conf ] && [ ! -f /etc/dnsmasq.conf.orig ] && cp /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
    cat > /etc/dnsmasq.conf << EOF
# WipeVision — DHCP + DNS server untuk WiFi AP
interface=${AP_IFACE}
no-dhcp-interface=lo,${CLIENT_IFACE},${LAN_IFACE}
bind-interfaces
domain-needed
bogus-priv
dhcp-range=${DHCP_START},${DHCP_END},255.255.255.0,12h
dhcp-option=3,${AP_IP}
# Arahkan DNS klien AP ke Pi sendiri (dnsmasq) agar domain lokal bisa di-resolve.
dhcp-option=6,${AP_IP}
# Upstream DNS untuk query internet (selain domain lokal).
server=8.8.8.8
server=8.8.4.4
# Domain lokal robot → IP AP. Klien cukup buka https://${DOMAIN}
# (local=/.../ menandai domain ini lokal: tidak diteruskan ke upstream).
local=/${DOMAIN}/
address=/${DOMAIN}/${AP_IP}
# Captive-portal opsional: arahkan juga nama-nama umum ke web robot bila perlu.
EOF
    echo "  OK"

    # --- NetworkManager: power-save off + uap0 unmanaged ---
    echo "[5/8] NetworkManager: power-save off + ${AP_IFACE} unmanaged..."
    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/98-wifi-powersave-off.conf << 'EOF'
# Power-save WiFi merusak stabilitas AP+STA di Pi 5. 2 = disable.
[connection]
wifi.powersave=2
EOF
    cat > /etc/NetworkManager/conf.d/99-unmanage-uap0.conf << EOF
[keyfile]
unmanaged-devices=interface-name:${AP_IFACE}
EOF
    nmcli device set "${AP_IFACE}" managed no 2>/dev/null || true
    echo "  OK"

    # --- Service uap@0 (robust: cleanup, IP, power_save off, restart dnsmasq) ---
    echo "[6/8] Menulis service /etc/systemd/system/uap@.service..."
    cat > /etc/systemd/system/uap@.service << 'EOF'
[Unit]
Description=IEEE 802.11 AP on uap%i with hostapd
After=network.target wpa_supplicant.service NetworkManager.service
Wants=network.target

[Service]
Type=forking
PIDFile=/run/hostapd.pid
Restart=on-failure
RestartSec=5
Environment=DAEMON_CONF=/etc/hostapd/hostapd.conf
EnvironmentFile=-/etc/default/hostapd

ExecStartPre=-/sbin/iw dev uap0 del
ExecStartPre=/bin/sleep 1
ExecStartPre=/sbin/iw dev wlan0 interface add uap0 type __ap
ExecStartPre=/bin/sleep 2
ExecStartPre=-/sbin/iw dev uap0 set power_save off
ExecStartPre=-/sbin/ip addr add 192.168.50.1/24 dev uap0
ExecStartPre=-/sbin/ip link set uap0 up

ExecStart=/usr/sbin/hostapd -i uap0 -P /run/hostapd.pid -B $DAEMON_OPTS ${DAEMON_CONF}

ExecStartPost=/bin/sleep 1
ExecStartPost=-/sbin/ip addr add 192.168.50.1/24 dev uap0
ExecStartPost=-/bin/systemctl --no-block restart dnsmasq

ExecStopPost=-/sbin/iw dev uap0 del

[Install]
WantedBy=multi-user.target
EOF

    mkdir -p /etc/systemd/system/dnsmasq.service.d
    cat > /etc/systemd/system/dnsmasq.service.d/override.conf << EOF
[Unit]
After=uap@0.service
Wants=uap@0.service

[Service]
Restart=on-failure
RestartSec=3
EOF
    echo "  OK"

    # --- Workaround driver brcmfmac (chanspec -52) di cmdline.txt ---
    echo "[7/8] Workaround driver di ${CMDLINE}..."
    if [ -f "${CMDLINE}" ]; then
        cp "${CMDLINE}" "${CMDLINE}.bak.$(date +%s)" 2>/dev/null || true
        ADD=""
        grep -q "brcmfmac.roamoff=" "${CMDLINE}" || ADD="${ADD} brcmfmac.roamoff=1"
        grep -q "brcmfmac.feature_disable=" "${CMDLINE}" || ADD="${ADD} brcmfmac.feature_disable=0x282000"
        if [ -n "${ADD}" ]; then
            sed -i "1 s|\$|${ADD}|" "${CMDLINE}"
            echo "  Ditambahkan:${ADD} (aktif setelah reboot)"
        else
            echo "  Sudah ada."
        fi
    else
        echo "  PERINGATAN: ${CMDLINE} tidak ditemukan."
    fi

    # --- Aktifkan service ---
    echo "[8/8] Mengaktifkan service..."
    rfkill unblock wlan 2>/dev/null || true
    systemctl unmask hostapd 2>/dev/null || true
    systemctl disable hostapd 2>/dev/null || true   # dipakai via uap@0, bukan langsung
    systemctl daemon-reload
    systemctl enable uap@0 dnsmasq 2>/dev/null || true
    systemctl enable avahi-daemon 2>/dev/null || true   # mDNS: <hostname>.local di LAN/WiFi
    systemctl restart avahi-daemon 2>/dev/null || true
    iw dev "${AP_IFACE}" del 2>/dev/null || true
    sleep 1
    systemctl restart uap@0 || true
    sleep 4
    ip addr add "${AP_IP}/24" dev "${AP_IFACE}" 2>/dev/null || true
    systemctl restart dnsmasq || true
    echo "  OK"
    echo "[WIFI] selesai."
    echo ""
}

# ============================================================================
# STEP: IZIN KONTROL WEB (polkit + sudoers)
# ============================================================================
do_perms() {
    title "[PERMS] Izin kontrol web untuk user '${APP_USER}'"

    # Grup netdev (kelola NetworkManager)
    if id "${APP_USER}" &>/dev/null; then
        usermod -aG netdev "${APP_USER}"
        echo "[OK] '${APP_USER}' ditambahkan ke grup netdev"
    fi

    # polkit: grup netdev kelola NM tanpa password
    cat > /etc/polkit-1/rules.d/50-wipevision-nm.rules << 'EOF'
// WipeVision: grup netdev kelola WiFi via NetworkManager tanpa prompt password.
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 &&
        subject.isInGroup("netdev")) {
        return polkit.Result.YES;
    }
});
EOF
    echo "[OK] polkit rule dipasang"

    # sudoers: app kelola hostapd + restart service + reboot tanpa password
    SUDOERS_FILE="/etc/sudoers.d/wipevision-wifi"
    cat > "${SUDOERS_FILE}" << EOF
# WipeVision: izin terbatas untuk fitur web (ganti AP, restart, reboot)
${APP_USER} ALL=(root) NOPASSWD: /bin/cat /etc/hostapd/hostapd.conf
${APP_USER} ALL=(root) NOPASSWD: /usr/bin/cat /etc/hostapd/hostapd.conf
${APP_USER} ALL=(root) NOPASSWD: /bin/cp /tmp/*.conf /etc/hostapd/hostapd.conf
${APP_USER} ALL=(root) NOPASSWD: /bin/chmod 600 /etc/hostapd/hostapd.conf
${APP_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart uap@0
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl restart uap@0
${APP_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart solar-panel-cleaner
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl restart solar-panel-cleaner
${APP_USER} ALL=(root) NOPASSWD: /sbin/reboot
${APP_USER} ALL=(root) NOPASSWD: /usr/sbin/reboot
EOF
    chmod 440 "${SUDOERS_FILE}"
    if visudo -c -f "${SUDOERS_FILE}" >/dev/null 2>&1; then
        echo "[OK] sudoers dipasang: ${SUDOERS_FILE}"
    else
        echo "[ERROR] sintaks sudoers invalid — dihapus demi keamanan"
        rm -f "${SUDOERS_FILE}"
    fi

    systemctl restart polkit 2>/dev/null || true
    echo "[PERMS] selesai."
    echo ""
}

# ============================================================================
# STEP: SERVICE AUTO-START
# ============================================================================
do_service() {
    title "[SERVICE] Auto-start solar-panel-cleaner"

    SRC="${PROJECT_DIR}/solar-panel-cleaner.service"
    if [ ! -f "${SRC}" ]; then
        echo "ERROR: ${SRC} tidak ditemukan."
        return 1
    fi

    # Sesuaikan User & path ke kondisi nyata (user + lokasi project + venv)
    sed -e "s|^User=.*|User=${APP_USER}|" \
        -e "s|^WorkingDirectory=.*|WorkingDirectory=${PROJECT_DIR}|" \
        -e "s|^Environment=.*|Environment=\"PATH=${VENV_DIR}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\"|" \
        -e "s|^ExecStart=.*|ExecStart=${VENV_DIR}/bin/python3 ${PROJECT_DIR}/main.py|" \
        "${SRC}" > /etc/systemd/system/solar-panel-cleaner.service
    chmod 644 /etc/systemd/system/solar-panel-cleaner.service

    systemctl daemon-reload
    systemctl enable solar-panel-cleaner.service
    systemctl restart solar-panel-cleaner.service || true
    echo "[OK] service aktif & auto-start saat boot."
    echo "[SERVICE] selesai."
    echo ""
}

# ============================================================================
# RINGKASAN
# ============================================================================
summary() {
    title " SETUP SELESAI"
    echo "  User aplikasi : ${APP_USER}"
    echo "  Lokasi        : ${PROJECT_DIR}"
    echo ""
    echo "  WiFi AP       : ${AP_SSID}  (pass: ${AP_PASS})"
    echo "  Akses via AP  : http://${AP_IP}:${WEB_PORT}"
    LANIP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -n "${LANIP}" ] && echo "  Akses via LAN/WiFi: http://${LANIP}:${WEB_PORT}"
    HOSTN=$(hostname 2>/dev/null)
    [ -n "${HOSTN}" ] && echo "  Akses via LAN (mDNS): http://${HOSTN}.local:${WEB_PORT}"
    if command -v caddy >/dev/null 2>&1; then
        echo ""
        echo "  HTTPS (tanpa port, installable PWA):"
        echo "    https://${DOMAIN}    https://${AP_HOSTNAME}.local"
        if [ -f "${PROJECT_DIR}/web/static/caddy-root-ca.crt" ]; then
            echo "    (mode CA internal) Trust root CA di HP sekali:"
            echo "    http://${AP_IP}:${WEB_PORT}/static/caddy-root-ca.crt"
        else
            echo "    (mode sertifikat asli Cloudflare — tanpa install CA di HP)"
        fi
    fi
    echo ""
    echo "  Verifikasi cepat:"
    echo "    ip addr show ${AP_IFACE} | grep inet"
    echo "    systemctl is-active uap@0 dnsmasq solar-panel-cleaner"
    echo ""
    echo "  >>> WAJIB REBOOT agar workaround driver WiFi aktif: sudo reboot <<<"
    hr
}

# ============================================================================
# STEP: REVERSE PROXY + HTTPS (Caddy)
# ============================================================================
# Caddy menyajikan web di port 443/80 dan mem-proxy ke Flask:${WEB_PORT}.
# Dua mode sertifikat (otomatis terpilih):
#   * Cloudflare DNS-01 (DISARANKAN): jika ${CF_TOKEN_FILE} berisi CF_API_TOKEN,
#     Caddy menerbitkan sertifikat Let's Encrypt ASLI untuk ${DOMAIN}. Valid di
#     mana saja (online & AP offline) TANPA perlu install CA di HP.
#   * CA internal (fallback): jika token tidak ada, Caddy pakai CA sendiri →
#     HP perlu trust root CA sekali (diekspor ke web/static/caddy-root-ca.crt).
do_https() {
    title "[HTTPS] Reverse proxy + HTTPS (Caddy)"

    if ! command -v caddy >/dev/null 2>&1; then
        echo "[1/5] Menambah repo & instal Caddy..."
        DEBIAN_FRONTEND=noninteractive apt-get install -y \
            debian-keyring debian-archive-keyring apt-transport-https curl gnupg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
            > /etc/apt/sources.list.d/caddy-stable.list
        apt-get update -y
        DEBIAN_FRONTEND=noninteractive apt-get install -y caddy
    else
        echo "[1/5] Caddy sudah terpasang — lewati instalasi."
    fi

    if ! command -v caddy >/dev/null 2>&1; then
        echo "[HTTPS] PERINGATAN: instalasi Caddy gagal (butuh internet). Lewati step ini."
        echo ""
        return 0
    fi

    # --- Tentukan mode sertifikat ---
    mkdir -p /etc/caddy
    local USE_CF=0
    if [ -f "${CF_TOKEN_FILE}" ]; then
        # Ambil nilai token, buang spasi/kutip.
        local _tok
        _tok=$(grep -E '^CF_API_TOKEN=' "${CF_TOKEN_FILE}" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' "'"'"'')
        if [ -n "${_tok}" ] && [ "${_tok}" != "ISI_TOKEN_CLOUDFLARE_DISINI" ] && [ "${#_tok}" -ge 20 ]; then
            USE_CF=1
        else
            echo "[!] ${CF_TOKEN_FILE} ada tapi token belum diisi (masih placeholder/kosong)."
            echo "    -> sementara pakai CA internal. Isi token lalu jalankan ulang: sudo bash setup.sh https"
        fi
    fi

    if [ "${USE_CF}" = "1" ]; then
        echo "[2/5] Token Cloudflare terdeteksi → mode sertifikat ASLI (DNS-01)."
        echo "      Menambah modul caddy-dns/cloudflare (butuh internet)..."
        caddy add-package github.com/caddy-dns/cloudflare 2>/dev/null || \
            echo "      (catatan: add-package gagal/sudah ada — lanjut)"

        # Token dibaca Caddy via environment (systemd EnvironmentFile).
        chmod 600 "${CF_TOKEN_FILE}" 2>/dev/null || true
        mkdir -p /etc/systemd/system/caddy.service.d
        cat > /etc/systemd/system/caddy.service.d/override.conf << EOF
[Service]
EnvironmentFile=-${CF_TOKEN_FILE}
EOF

        echo "[3/5] Menulis /etc/caddy/Caddyfile (Let's Encrypt via Cloudflare)..."
        cat > /etc/caddy/Caddyfile << EOF
# WipeVision — reverse proxy + HTTPS (auto-generated oleh setup.sh)
# Sertifikat ASLI Let's Encrypt untuk ${DOMAIN} via Cloudflare DNS-01.
# Catatan: .local TIDAK disertakan di sini karena tidak bisa dapat
# sertifikat publik. Akses LAN pakai ${DOMAIN} atau IP:${WEB_PORT}.
${DOMAIN} {
    tls {
        dns cloudflare {env.CF_API_TOKEN}
        resolvers 1.1.1.1 8.8.8.8
    }
    encode gzip
    # flush_interval -1: streaming MJPEG (/api/preview/stream) tanpa buffering;
    # WebSocket di-upgrade otomatis oleh reverse_proxy.
    reverse_proxy localhost:${WEB_PORT} {
        flush_interval -1
    }
}
EOF
    else
        echo "[2/5] Token Cloudflare TIDAK ada → mode CA internal (fallback)."
        echo "      (Buat ${CF_TOKEN_FILE} berisi CF_API_TOKEN=... untuk sertifikat asli.)"
        echo "[3/5] Menulis /etc/caddy/Caddyfile (CA internal)..."
        cat > /etc/caddy/Caddyfile << EOF
# WipeVision — reverse proxy + HTTPS (auto-generated oleh setup.sh)
# CA internal Caddy (tanpa Let's Encrypt). HP perlu trust root CA sekali.
${DOMAIN}, ${AP_HOSTNAME}.local {
    tls internal
    encode gzip
    reverse_proxy localhost:${WEB_PORT} {
        flush_interval -1
    }
}
EOF
    fi
    chmod 644 /etc/caddy/Caddyfile

    echo "[4/5] Mengaktifkan service caddy..."
    systemctl daemon-reload
    systemctl enable caddy 2>/dev/null || true
    systemctl restart caddy || true

    echo "[5/5] Menyiapkan sertifikat untuk HP..."
    if [ "${USE_CF}" = "1" ]; then
        echo "  Mode sertifikat asli: TIDAK perlu install CA di HP."
        echo "  Caddy menerbitkan & memperbarui sertifikat ${DOMAIN} otomatis."
        echo "  Pantau penerbitan: sudo journalctl -u caddy -f"
        rm -f "${PROJECT_DIR}/web/static/caddy-root-ca.crt" 2>/dev/null || true
    else
        # Ekspor root CA internal agar bisa di-trust di HP.
        local CA_SRC=""
        for i in $(seq 1 15); do
            CA_SRC=$(find /var/lib/caddy /root /etc/caddy -path '*pki/authorities/local/root.crt' 2>/dev/null | head -1)
            [ -n "${CA_SRC}" ] && break
            sleep 1
        done
        if [ -n "${CA_SRC}" ] && [ -f "${CA_SRC}" ]; then
            cp "${CA_SRC}" "${PROJECT_DIR}/web/static/caddy-root-ca.crt"
            chmod 644 "${PROJECT_DIR}/web/static/caddy-root-ca.crt"
            echo "  OK -> web/static/caddy-root-ca.crt"
            echo "  Unduh di HP: http://${AP_IP}:${WEB_PORT}/static/caddy-root-ca.crt"
        else
            echo "  PERINGATAN: root CA belum ditemukan. Jalankan ulang 'sudo bash setup.sh https'."
        fi
    fi
    echo "[HTTPS] selesai."
    echo ""
}

# ============================================================================
# MAIN
# ============================================================================
require_root
MODE="${1:-all}"
echo ""
echo "  Mode: ${MODE} | User: ${APP_USER} | Dir: ${PROJECT_DIR}"
echo ""

case "${MODE}" in
    all)     do_deps; do_wifi; do_perms; do_service; do_https; summary ;;
    deps)    do_deps ;;
    wifi)    do_wifi; summary ;;
    perms)   do_perms ;;
    service) do_service ;;
    https)   do_https ;;
    *)       echo "Mode tidak dikenal: ${MODE}"
             echo "Pilihan: all | deps | wifi | perms | service | https"; exit 1 ;;
esac
