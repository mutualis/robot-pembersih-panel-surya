# Setup Raspberry Pi — Solar Panel Cleaning Robot

Panduan setup produksi dari nol. Satu script (`setup.sh`) menangani semua:
dependensi, WiFi AP, izin web, dan service auto-start.

---

## 1. Prasyarat

- Raspberry Pi 5 dengan Raspberry Pi OS Bookworm (64-bit).
- Sudah bisa SSH / akses terminal ke Pi.
- Project sudah di-`git clone` ke `~/wipevision`.

```bash
cd ~/wipevision/raspberry-pi
```

---

## 2. Setup Penuh (sekali jalan)

```bash
sudo bash setup.sh
sudo reboot
```

Script melakukan, berurutan:

| Tahap | Isi |
|-------|-----|
| `deps` | apt (hostapd, dnsmasq, iptables), buat `venv/`, install `requirements.txt` |
| `wifi` | WiFi AP `SolarPanelCleaner` + client, anti-bug Pi 5 (lihat §5) |
| `perms` | polkit + sudoers agar fitur web (ganti WiFi, restart, reboot) jalan tanpa password |
| `service` | `solar-panel-cleaner.service` auto-start saat boot |

**Reboot wajib** agar workaround driver WiFi (`cmdline.txt`) aktif.

### Menjalankan sebagian saja

```bash
sudo bash setup.sh deps      # hanya dependensi
sudo bash setup.sh wifi      # hanya WiFi AP+client
sudo bash setup.sh perms     # hanya izin web
sudo bash setup.sh service   # hanya service auto-start
```

---

## 3. Verifikasi

```bash
ip addr show uap0 | grep inet                          # → inet 192.168.50.1
systemctl is-active uap@0 dnsmasq solar-panel-cleaner  # → active active active
```

Akses web:
- **Via WiFi AP (IP):** connect HP/laptop ke WiFi `SolarPanelCleaner` (pass `solarpanel123`) → buka `http://192.168.50.1:5000`
- **Via domain (HTTPS):** `https://wipevision.my.id` — jalan online (Cloudflare Tunnel) maupun AP offline (split-horizon DNS → IP AP). Lihat §4b.
- **Via LAN/WiFi rumah (IP):** `http://<ip-pi>:5000` (cek IP: `hostname -I`)
- **Via LAN/WiFi rumah (mDNS):** `http://<hostname>.local:5000` (mis. `wipevision.local`, butuh avahi-daemon)

> Akses IP:port `:5000` (seperti di Bab 3) selalu tersedia sebagai jalur langsung/fallback, terlepas dari status Caddy/Tunnel.

Akun web: `taridho` / `2026` (admin penuh). Tanpa login = view-only.

---

## 4. Konfigurasi (ubah sebelum jalankan, di bagian atas `setup.sh`)

| Variabel | Default | Keterangan |
|----------|---------|------------|
| `AP_SSID` | `SolarPanelCleaner` | Nama hotspot |
| `AP_PASS` | `solarpanel123` | Password (8–63 karakter) |
| `AP_IP` | `192.168.50.1` | IP statis AP |
| `DOMAIN` | `wipevision.my.id` | Domain HTTPS (online via Tunnel, AP via split-horizon) |
| `AP_HOSTNAME` | `wipevision` | Acuan nama mDNS `<hostname>.local` di LAN |
| `WEB_PORT` | `5000` | Port web |

SSID & password AP juga bisa diganti dari halaman **Settings** di web (aman,
tidak merusak config).

---

## 4b. HTTPS + Domain `wipevision.my.id` (Caddy + Cloudflare)

`setup.sh https` (otomatis ikut di mode `all`) memasang **Caddy** sebagai
reverse proxy: web tampil di `https://wipevision.my.id` (port 443, tanpa
`:5000`) dan mem-proxy ke Flask `localhost:5000`. WebSocket & streaming kamera
diteruskan otomatis. Akses IP:port (Bab 3) tetap hidup sebagai jalur langsung.

Satu domain `wipevision.my.id` dipakai di **semua kondisi**:
- **Online** (mobile data / WiFi rumah) → via Cloudflare Tunnel (`setup_cloudflare_tunnel.sh`).
- **AP offline** (lapangan tanpa internet) → split-horizon DNS: `dnsmasq` me-resolve
  `wipevision.my.id` ke `192.168.50.1`, disajikan Caddy dengan sertifikat asli.

### Langkah (mode sertifikat ASLI — disarankan, tanpa install CA di HP)

1. Buat **API token Cloudflare** (sekali): dashboard Cloudflare → My Profile →
   API Tokens → Create Token → template **Edit zone DNS** → Zone DNS Edit untuk
   zona `wipevision.my.id` → salin token.
2. Taruh token di Pi:
   ```bash
   sudo cp cloudflare.env.example /etc/caddy/cloudflare.env
   sudo nano /etc/caddy/cloudflare.env      # ganti CF_API_TOKEN=...
   sudo chmod 600 /etc/caddy/cloudflare.env
   ```
3. Jalankan:
   ```bash
   sudo bash setup.sh https
   ```
   Caddy menambah modul `caddy-dns/cloudflare`, menerbitkan sertifikat Let's
   Encrypt untuk `wipevision.my.id` via DNS-01, dan memperbaruinya otomatis.
4. Di HP: buka `https://wipevision.my.id` → menu browser → **Install / Add to
   Home screen**. Tidak perlu install sertifikat apa pun.

> Penerbitan/renewal sertifikat butuh internet (akses API Cloudflare). Setelah
> terbit, sertifikat di-cache di Pi sehingga HTTPS lokal tetap valid saat AP
> offline. Pantau: `sudo journalctl -u caddy -f`.

### Fallback (tanpa token Cloudflare — CA internal)

Jika `/etc/caddy/cloudflare.env` tidak ada, Caddy memakai CA internal. HP perlu
trust root CA sekali: unduh `http://192.168.50.1:5000/static/caddy-root-ca.crt`
lalu install (Android: Settings → Security → Install certificate → CA; iOS:
Install Profile + aktifkan di Certificate Trust Settings).

| Akses | URL |
|-------|-----|
| HTTPS (PWA, tanpa port) | `https://wipevision.my.id` · `https://<hostname>.local` |
| HTTP langsung (fallback, Bab 3) | `http://192.168.50.1:5000` · `http://<ip-pi>:5000` |

> Caddy butuh internet **saat instalasi & penerbitan cert**. Web tetap bisa
> diakses via `http://...:5000` kapan pun.

---

## 5. Catatan Penting WiFi (Pi 5)

Chip WiFi internal Pi 5 menjalankan AP (`uap0`) + Client (`wlan0`) di **satu
radio**. Ada dua batasan keras yang sudah ditangani `setup.sh`:

1. **Channel AP wajib sama dengan channel `wlan0`.** Script mendeteksi channel
   `wlan0` otomatis dan memakainya untuk AP. Jika robot pindah ke router dengan
   channel berbeda, jalankan ulang `sudo bash setup.sh wifi` agar AP menyesuaikan.
2. **Tidak boleh ACS (auto channel)** — driver `brcmfmac` gagal survey channel.
   Channel selalu ditulis eksplisit.

Workaround tambahan yang dipasang otomatis:
- WiFi power-save **off** (mencegah AP terganggu saat `wlan0` scan).
- `cmdline.txt`: `brcmfmac.roamoff=1 brcmfmac.feature_disable=0x282000`
  (menekan bug `set chanspec fail, reason -52`). Aktif **setelah reboot**.

> Jika di lapangan tidak ada router, mode **AP-only** paling stabil. Cukup
> jangan sambungkan `wlan0` ke WiFi mana pun — AP tetap jalan tanpa konflik.

---

## 6. Perintah Operasional

```bash
# Service aplikasi
sudo systemctl restart solar-panel-cleaner
sudo journalctl -u solar-panel-cleaner -f

# WiFi AP
sudo systemctl restart uap@0
sudo systemctl restart dnsmasq
sudo journalctl -u uap@0 -n 30 --no-pager

# HTTPS / reverse proxy (Caddy)
sudo systemctl restart caddy
sudo journalctl -u caddy -n 30 --no-pager
sudo caddy validate --config /etc/caddy/Caddyfile

# Status WiFi
nmcli device status
iw dev wlan0 link
```

---

## 7. Troubleshooting

**HP bisa lihat WiFi AP tapi "connection failed" / tidak dapat IP**
```bash
ip addr show uap0 | grep inet     # harus 192.168.50.1
systemctl is-active dnsmasq       # harus active
sudo bash setup.sh wifi           # tulis ulang config + restart
sudo reboot
```

**`uap@0` gagal start ("ACS / survey data failed")**
Channel AP tidak cocok / kosong. Jalankan ulang `sudo bash setup.sh wifi`
(otomatis menyamakan channel ke `wlan0`).

**Fitur web (ganti WiFi / reboot) minta password / gagal**
```bash
sudo bash setup.sh perms
sudo reboot                       # agar keanggotaan grup netdev aktif
```

**Service tidak auto-start**
```bash
sudo bash setup.sh service
systemctl status solar-panel-cleaner --no-pager -l
```

---

## 8. File Pendukung Lain

| File | Fungsi |
|------|--------|
| `README.md` | Overview lengkap proyek RPi |
| `restore_single_wifi.sh` | Matikan AP, kembali ke client-only |
| `uninstall_service.sh` | Hapus service auto-start |
| `setup_cloudflare_tunnel.sh` | (Opsional) akses remote via domain |
| `check_performance.py` | Cek FPS/CPU/memori untuk Bab 4 |

---

**Author:** Muhammad Ridho Assidiqi — UGM Sekolah Vokasi (TRIK)
