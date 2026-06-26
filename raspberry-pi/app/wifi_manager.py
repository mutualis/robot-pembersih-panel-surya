"""
WiFi Manager - Konfigurasi WiFi via NetworkManager (nmcli)

Modul untuk mengelola koneksi WiFi client (wlan0) secara dinamis tanpa
mengubah kode program. Memungkinkan robot dipindah ke lokasi berbeda dan
mengganti WiFi cukup lewat antarmuka web.

Catatan deployment:
- Sistem memakai NetworkManager (default Raspberry Pi OS Bookworm).
- Perintah nmcli dijalankan via subprocess dengan argumen list (tanpa shell)
  untuk mencegah command injection dari input SSID/password pengguna.
- Saat mengganti WiFi client (wlan0), akses melalui WiFi AP (uap0,
  "SolarPanelCleaner") TIDAK terputus sehingga pengguna tetap bisa
  memantau proses penggantian.
- Agar bisa jalan tanpa password sudo, lihat setup.sh (mode perms)
  (memasang aturan polkit untuk grup netdev).

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import subprocess
import threading
from typing import Dict, List, Optional


class WiFiManager:
    """Pengelola koneksi WiFi client via nmcli (NetworkManager)."""

    def __init__(self, client_iface: str = "wlan0", ap_iface: str = "uap0",
                 timeout: int = 25):
        self.client_iface = client_iface
        self.ap_iface = ap_iface
        self.timeout = timeout
        # Lock agar tidak ada dua operasi nmcli berjalan bersamaan
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Helper internal
    # ------------------------------------------------------------------
    def _run(self, args: List[str], timeout: Optional[int] = None) -> Dict:
        """
        Jalankan perintah nmcli dengan argumen list (aman dari injection).

        Mengembalikan dict: {'ok': bool, 'stdout': str, 'stderr': str, 'code': int}
        """
        cmd = ["nmcli"] + args
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
            )
            return {
                "ok": proc.returncode == 0,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "code": proc.returncode,
            }
        except FileNotFoundError:
            return {"ok": False, "stdout": "", "stderr": "nmcli tidak ditemukan (NetworkManager belum terpasang)", "code": -1}
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "Perintah nmcli timeout", "code": -2}
        except Exception as e:
            return {"ok": False, "stdout": "", "stderr": str(e), "code": -3}

    @staticmethod
    def _split_escaped(line: str, sep: str = ":") -> List[str]:
        """
        Pisahkan baris output nmcli mode terse (-t) yang memakai escape '\\'.
        nmcli meng-escape karakter pemisah dengan backslash (mis. '\\:').
        """
        fields = []
        current = []
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "\\" and i + 1 < len(line):
                current.append(line[i + 1])
                i += 2
                continue
            if ch == sep:
                fields.append("".join(current))
                current = []
                i += 1
                continue
            current.append(ch)
            i += 1
        fields.append("".join(current))
        return fields

    # ------------------------------------------------------------------
    # Operasi publik
    # ------------------------------------------------------------------
    def scan(self) -> Dict:
        """
        Scan jaringan WiFi yang tersedia pada interface client.

        Return: {'success': bool, 'networks': [...], 'message': str}
        Setiap network: {ssid, signal(int), security, in_use(bool)}
        """
        with self._lock:
            # Minta rescan agar daftar segar (abaikan error bila baru saja rescan)
            self._run(["device", "wifi", "rescan", "ifname", self.client_iface], timeout=15)
            res = self._run([
                "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                "device", "wifi", "list", "ifname", self.client_iface,
            ])

        if not res["ok"]:
            return {"success": False, "networks": [], "message": res["stderr"] or "Gagal scan WiFi"}

        networks: List[Dict] = []
        seen = set()
        for line in res["stdout"].splitlines():
            if not line.strip():
                continue
            parts = self._split_escaped(line)
            if len(parts) < 4:
                continue
            in_use, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
            if not ssid:  # lewati SSID kosong/hidden tanpa nama
                continue
            # Hindari duplikat SSID, simpan sinyal terkuat
            try:
                sig = int(signal) if signal.isdigit() else 0
            except ValueError:
                sig = 0
            if ssid in seen:
                # update bila sinyal lebih kuat
                for n in networks:
                    if n["ssid"] == ssid and sig > n["signal"]:
                        n["signal"] = sig
                continue
            seen.add(ssid)
            sec = security or "Open"
            networks.append({
                "ssid": ssid,
                "signal": sig,
                "security": sec,
                "auth_type": self._detect_auth_type(sec),
                "in_use": in_use.strip() in ("*", "yes"),
            })

        networks.sort(key=lambda n: n["signal"], reverse=True)
        return {"success": True, "networks": networks, "message": f"{len(networks)} jaringan ditemukan"}

    def status(self) -> Dict:
        """
        Status koneksi WiFi client saat ini.

        Return: {success, connected, ssid, signal, ip, message}
        """
        with self._lock:
            # SSID & sinyal yang sedang dipakai
            res = self._run([
                "-t", "-f", "ACTIVE,SSID,SIGNAL",
                "device", "wifi", "list", "ifname", self.client_iface,
            ])
            ip_res = self._run([
                "-t", "-f", "IP4.ADDRESS",
                "device", "show", self.client_iface,
            ])

        ssid = None
        signal = 0
        if res["ok"]:
            for line in res["stdout"].splitlines():
                parts = self._split_escaped(line)
                if len(parts) >= 3 and parts[0] == "yes":
                    ssid = parts[1]
                    signal = int(parts[2]) if parts[2].isdigit() else 0
                    break

        ip = None
        if ip_res["ok"]:
            for line in ip_res["stdout"].splitlines():
                # format: IP4.ADDRESS[1]:192.168.1.9/24
                if ":" in line:
                    val = line.split(":", 1)[1].strip()
                    if val:
                        ip = val.split("/")[0]
                        break

        return {
            "success": True,
            "connected": ssid is not None,
            "ssid": ssid,
            "signal": signal,
            "ip": ip,
            "message": f"Terhubung ke {ssid}" if ssid else "Tidak terhubung ke WiFi",
        }

    @staticmethod
    def _detect_auth_type(security: str) -> str:
        """
        Klasifikasikan metode autentikasi WiFi dari string security nmcli.

        Return salah satu dari:
          'open'       — tidak ada enkripsi
          'wep'        — WEP (usang, jarang)
          'psk'        — WPA/WPA2/WPA3 Personal (hanya password)
          'enterprise' — WPA2/WPA3 Enterprise / 802.1X (username + password)
        """
        sec = (security or "").upper()
        if not sec or sec == "OPEN" or sec == "--":
            return "open"
        if "802.1X" in sec or "EAP" in sec or "ENTERPRISE" in sec:
            return "enterprise"
        if "WEP" in sec:
            return "wep"
        if any(k in sec for k in ("WPA", "PSK", "SAE", "OWE")):
            return "psk"
        return "psk"  # default aman

    def connect(self, ssid: str, password: Optional[str] = None,
                username: Optional[str] = None, auth_type: Optional[str] = None) -> Dict:
        """
        Sambungkan WiFi client (wlan0) ke SSID baru.

        auth_type='enterprise' → gunakan WPA2-Enterprise (802.1X PEAP/MSCHAPv2)
                                  dengan username + password.
        auth_type='psk' / None → WPA2-Personal, hanya password.
        auth_type='open'       → tidak butuh kredensial.
        """
        ssid = (ssid or "").strip()
        if not ssid:
            return {"success": False, "message": "SSID tidak boleh kosong"}

        # Deteksi otomatis jika auth_type tidak dikirim
        if not auth_type:
            auth_type = "psk"

        if auth_type == "enterprise":
            return self._connect_enterprise(ssid, username or "", password or "")

        # PSK / Open
        if password is not None and password != "" and len(password) < 8:
            return {"success": False, "message": "Password WiFi minimal 8 karakter"}

        args = ["device", "wifi", "connect", ssid, "ifname", self.client_iface]
        if password:
            args += ["password", password]

        with self._lock:
            res = self._run(args, timeout=45)

        if res["ok"]:
            return {"success": True, "message": f"Berhasil terhubung ke {ssid}"}

        err = res["stderr"] or "Gagal menghubungkan"
        low = err.lower()
        if "secrets were required" in low or "no key available" in low or "802.1" in low:
            err = "Password salah atau diperlukan password"
        elif "no network with ssid" in low:
            err = f"Jaringan '{ssid}' tidak ditemukan"
        return {"success": False, "message": err}

    def _connect_enterprise(self, ssid: str, username: str, password: str) -> Dict:
        """
        Sambungkan ke WiFi WPA2-Enterprise (802.1X) menggunakan PEAP/MSCHAPv2.
        Ini tipe yang dipakai hampir semua WiFi kampus/institusi.

        Langkah:
        1. Hapus profil lama (jika ada) agar tidak konflik.
        2. Buat profil baru via 'nmcli connection add'.
        3. Aktifkan koneksi via 'nmcli connection up'.
        """
        if not username:
            return {"success": False, "message": "Username diperlukan untuk WiFi Enterprise"}
        if not password:
            return {"success": False, "message": "Password diperlukan untuk WiFi Enterprise"}

        conn_name = f"wv-{ssid}"  # nama profil unik agar mudah dihapus nanti

        with self._lock:
            # 1. Hapus profil lama bila ada
            self._run(["connection", "delete", conn_name], timeout=10)

            # 2. Buat profil WPA2-Enterprise PEAP/MSCHAPv2
            add_res = self._run([
                "connection", "add",
                "type", "wifi",
                "con-name", conn_name,
                "ifname", self.client_iface,
                "ssid", ssid,
                "wifi-sec.key-mgmt", "wpa-eap",
                "802-1x.eap", "peap",
                "802-1x.phase2-auth", "mschapv2",
                "802-1x.identity", username,
                "802-1x.password", password,
                "802-1x.anonymous-identity", "",
            ], timeout=15)

            if not add_res["ok"]:
                err = add_res["stderr"] or "Gagal membuat profil koneksi"
                return {"success": False, "message": err}

            # 3. Aktifkan koneksi
            up_res = self._run(["connection", "up", conn_name,
                                 "ifname", self.client_iface], timeout=45)

        if up_res["ok"]:
            return {"success": True,
                    "message": f"Berhasil terhubung ke {ssid} (WPA2-Enterprise)"}

        err = up_res["stderr"] or "Gagal terhubung"
        low = err.lower()
        if "secrets" in low or "authentication" in low or "failed" in low:
            err = f"Username/password salah untuk jaringan '{ssid}'"
        elif "no network" in low or "not found" in low:
            err = f"Jaringan '{ssid}' tidak ditemukan"
        return {"success": False, "message": err}

    def saved_networks(self) -> Dict:
        """Daftar profil WiFi yang sudah tersimpan (bisa auto-connect)."""
        with self._lock:
            res = self._run(["-t", "-f", "NAME,TYPE", "connection", "show"])
        if not res["ok"]:
            return {"success": False, "networks": [], "message": res["stderr"]}
        nets = []
        for line in res["stdout"].splitlines():
            parts = self._split_escaped(line)
            if len(parts) >= 2 and "wireless" in parts[1]:
                nets.append(parts[0])
        return {"success": True, "networks": nets, "message": f"{len(nets)} profil tersimpan"}

    def forget(self, ssid: str) -> Dict:
        """Hapus profil WiFi tersimpan agar tidak auto-connect lagi."""
        ssid = (ssid or "").strip()
        if not ssid:
            return {"success": False, "message": "SSID tidak boleh kosong"}
        # Lindungi AP & profil sistem penting
        if ssid in (self.ap_iface, "SolarPanelCleaner", "preconfigured"):
            return {"success": False, "message": f"Profil '{ssid}' dilindungi dan tidak boleh dihapus"}
        with self._lock:
            res = self._run(["connection", "delete", ssid], timeout=15)
        if res["ok"]:
            return {"success": True, "message": f"Profil '{ssid}' dihapus"}
        return {"success": False, "message": res["stderr"] or "Gagal menghapus profil"}

    # ------------------------------------------------------------------
    # Konfigurasi WiFi AP (hostapd)
    # ------------------------------------------------------------------
    HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"
    AP_SERVICE = "uap@0"

    def get_ap_config(self) -> Dict:
        """
        Baca konfigurasi AP saat ini dari hostapd.conf.

        Return: {success, ssid, password, channel, message}
        Password ditampilkan apa adanya agar admin mudah melihat/menyalin
        (halaman ini sudah dilindungi login admin).

        Karena hostapd.conf biasanya chmod 600 (root-only), bila pembacaan
        langsung gagal akibat izin, otomatis mencoba `sudo -n cat`.
        """
        import os

        def _parse(text: str) -> Dict:
            ssid = password = channel = None
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("ssid="):
                    ssid = line.split("=", 1)[1]
                elif line.startswith("wpa_passphrase="):
                    password = line.split("=", 1)[1]
                elif line.startswith("channel="):
                    channel = line.split("=", 1)[1]
            return {
                "success": True,
                "ssid": ssid or "",
                "password": password or "",
                "channel": channel or "",
                "message": "OK",
            }

        if not os.path.exists(self.HOSTAPD_CONF):
            return {
                "success": False,
                "message": "Konfigurasi AP tidak ditemukan. Jalankan setup.sh (mode wifi) dulu.",
            }

        # 1. Coba baca langsung
        try:
            with open(self.HOSTAPD_CONF, "r") as f:
                return _parse(f.read())
        except PermissionError:
            pass  # lanjut ke fallback sudo
        except Exception as e:
            return {"success": False, "message": str(e)}

        # 2. Fallback: baca via sudo (file root-only)
        try:
            proc = subprocess.run(
                ["sudo", "-n", "cat", self.HOSTAPD_CONF],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if proc.returncode == 0:
                return _parse(proc.stdout)
            return {
                "success": False,
                "message": "Tidak ada izin membaca konfigurasi AP. "
                           "Jalankan setup.sh (mode perms) agar app bisa akses hostapd.conf.",
            }
        except Exception as e:
            return {"success": False, "message": f"Gagal membaca konfigurasi AP: {e}"}

    # Channel AP default. Pada mode AP+STA satu radio (chip internal Pi 5),
    # channel AP HARUS sama dengan channel wlan0. brcmfmac Pi 5 TIDAK bisa ACS
    # (auto channel) — channel WAJIB eksplisit, jika tidak hostapd gagal start
    # ("ACS: Unable to collect survey data").
    AP_DEFAULT_CHANNEL = "1"

    def _build_hostapd_conf(self, ssid: str, password: str,
                            channel: str = None, country: str = "ID") -> str:
        """
        Bangun isi hostapd.conf LENGKAP & valid dari template.

        Selalu menulis config penuh (interface, driver, hw_mode, channel, wpa,
        dst.) agar file tidak pernah jadi parsial/rusak. channel dipaksa
        eksplisit (tanpa ACS) demi kompatibilitas brcmfmac Pi 5.
        """
        ch = channel or self.AP_DEFAULT_CHANNEL
        return (
            "# WipeVision AP — Solar Panel Cleaning Robot (auto-generated)\n"
            "# channel DIPAKSA (tanpa ACS): brcmfmac Pi 5 tidak bisa survey channel,\n"
            "# dan pada mode AP+STA channel harus sama dengan wlan0.\n"
            "ctrl_interface=/var/run/hostapd\n"
            f"interface={self.ap_iface}\n"
            "driver=nl80211\n"
            f"country_code={country}\n"
            f"ssid={ssid}\n"
            "hw_mode=g\n"
            f"channel={ch}\n"
            "ieee80211n=1\n"
            "wmm_enabled=1\n"
            "macaddr_acl=0\n"
            "auth_algs=1\n"
            "ignore_broadcast_ssid=0\n"
            "wpa=2\n"
            f"wpa_passphrase={password}\n"
            "wpa_key_mgmt=WPA-PSK\n"
            "rsn_pairwise=CCMP\n"
        )

    def set_ap_config(self, ssid: Optional[str] = None,
                       password: Optional[str] = None) -> Dict:
        """
        Ubah SSID dan/atau password WiFi AP, lalu restart service AP.

        - Validasi: SSID 1-32 karakter, password 8-63 karakter (standar WPA2).
        - Field yang tidak diisi mempertahankan nilai lama.
        - Config SELALU ditulis ulang LENGKAP dari template (tidak pernah
          parsial) agar hostapd.conf tidak rusak/kehilangan baris penting.
        - Memakai sudo untuk menulis file root & restart service.
          (Lihat setup.sh mode perms untuk izin sudoers.)
        """
        ssid = ssid.strip() if ssid else None
        # Validasi
        if ssid is not None:
            if not (1 <= len(ssid) <= 32):
                return {"success": False, "message": "SSID harus 1-32 karakter"}
        if password is not None and password != "":
            if not (8 <= len(password) <= 63):
                return {"success": False, "message": "Password AP harus 8-63 karakter"}

        if ssid is None and (password is None or password == ""):
            return {"success": False, "message": "Tidak ada perubahan (SSID & password kosong)"}

        with self._lock:
            # Baca config saat ini (get_ap_config sudah punya fallback sudo).
            # Nilai yang tidak diubah dipertahankan dari sini.
            current = self.get_ap_config()
            cur_ssid = current.get("ssid") or "SolarPanelCleaner"
            cur_pass = current.get("password") or ""
            cur_channel = current.get("channel") or self.AP_DEFAULT_CHANNEL

            new_ssid = ssid if ssid is not None else cur_ssid
            new_pass = password if (password is not None and password != "") else cur_pass

            # Password akhir wajib valid (8-63). Bila lama kosong/invalid &
            # tidak ada password baru, tolak agar tidak bikin AP tanpa sandi.
            if not (8 <= len(new_pass) <= 63):
                return {
                    "success": False,
                    "message": "Password AP saat ini tidak terbaca. "
                               "Isi password baru (8-63 karakter) untuk memperbaiki.",
                }

            content = self._build_hostapd_conf(new_ssid, new_pass, channel=cur_channel)
            return self._write_hostapd_and_restart(content)

    def _write_hostapd_and_restart(self, content: str) -> Dict:
        """Tulis hostapd.conf (via sudo tee) dan restart service AP."""
        import tempfile
        import os

        try:
            # Tulis ke file sementara di /tmp (cocok dengan aturan sudoers)
            fd, tmp_path = tempfile.mkstemp(suffix=".conf", prefix="wipevision_ap_",
                                            dir="/tmp", text=True)
            with os.fdopen(fd, "w") as f:
                f.write(content)

            # Salin ke lokasi root via sudo (non-interaktif)
            cp = subprocess.run(
                ["sudo", "-n", "cp", tmp_path, self.HOSTAPD_CONF],
                capture_output=True, text=True, timeout=10, check=False,
            )
            os.unlink(tmp_path)

            if cp.returncode != 0:
                err = cp.stderr.strip() or "Gagal menyimpan konfigurasi AP"
                if "password" in err.lower() or "sudo:" in err.lower():
                    err = "Perlu izin sudo. Jalankan setup.sh (mode perms)."
                return {"success": False, "message": err}

            # Pastikan permission aman
            subprocess.run(["sudo", "-n", "chmod", "600", self.HOSTAPD_CONF],
                           capture_output=True, text=True, timeout=10, check=False)

            # Restart service AP agar perubahan aktif
            rs = subprocess.run(
                ["sudo", "-n", "systemctl", "restart", self.AP_SERVICE],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if rs.returncode != 0:
                return {
                    "success": True,
                    "warning": True,
                    "message": "Konfigurasi tersimpan, tetapi gagal restart AP otomatis. "
                               "Restart manual: sudo systemctl restart uap@0",
                }

            return {
                "success": True,
                "message": "Konfigurasi AP diperbarui. WiFi AP akan restart — "
                           "sambungkan ulang perangkat ke SSID baru.",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "Timeout saat menyimpan/restart AP"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Deteksi tipe koneksi: WiFi / LAN / keduanya
    # ------------------------------------------------------------------
    def connectivity(self, lan_iface: str = "eth0") -> Dict:
        """
        Deteksi cara Raspberry Pi terkoneksi ke jaringan: WiFi, LAN (kabel),
        atau keduanya. Memeriksa status carrier & IP per interface.

        Return:
          {
            success, primary: 'lan'|'wifi'|'none',
            lan:  {connected, ip},
            wifi: {connected, ssid, ip},
            message
          }
        """
        # --- LAN (eth0) ---
        lan_connected = False
        lan_ip = None
        lan_res = self._run(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION",
                             "device", "status"])
        if lan_res["ok"]:
            for line in lan_res["stdout"].splitlines():
                parts = self._split_escaped(line)
                if len(parts) >= 3 and parts[0] == lan_iface:
                    # STATE "connected" menandakan kabel terpasang & aktif
                    lan_connected = parts[2].startswith("connected")
                    break
        if lan_connected:
            ip_res = self._run(["-t", "-f", "IP4.ADDRESS", "device", "show", lan_iface])
            if ip_res["ok"]:
                for line in ip_res["stdout"].splitlines():
                    if ":" in line:
                        val = line.split(":", 1)[1].strip()
                        if val:
                            lan_ip = val.split("/")[0]
                            break

        # --- WiFi (wlan0) ---
        wifi_status = self.status()
        wifi_connected = wifi_status.get("connected", False)

        # --- Tentukan koneksi utama ---
        # LAN diprioritaskan sebagai default route bila keduanya aktif.
        if lan_connected:
            primary = "lan"
        elif wifi_connected:
            primary = "wifi"
        else:
            primary = "none"

        msg_map = {
            "lan": "Terhubung via kabel LAN",
            "wifi": f"Terhubung via WiFi ({wifi_status.get('ssid')})",
            "none": "Tidak ada koneksi jaringan",
        }

        return {
            "success": True,
            "primary": primary,
            "lan": {"connected": lan_connected, "ip": lan_ip, "interface": lan_iface},
            "wifi": {
                "connected": wifi_connected,
                "ssid": wifi_status.get("ssid"),
                "ip": wifi_status.get("ip"),
                "signal": wifi_status.get("signal", 0),
                "interface": self.client_iface,
            },
            "message": msg_map[primary],
        }

    # ------------------------------------------------------------------
    # Captive Portal — login otomatis ke WiFi kampus/institusi
    # ------------------------------------------------------------------
    # URL yang dipakai OS populer untuk deteksi captive portal
    _PROBE_URLS = [
        "http://clients3.google.com/generate_204",   # Android / Chrome OS
        "http://connectivitycheck.gstatic.com/generate_204",
        "http://www.msftconnecttest.com/connecttest.txt",  # Windows
        "http://captive.apple.com",                  # macOS / iOS
    ]

    def check_internet(self, timeout: int = 5) -> bool:
        """
        Cek apakah akses internet benar-benar tersedia (bukan hanya connect WiFi).
        Kirim request ke endpoint Google yang harusnya balas 204 No Content.
        Captive portal biasanya redirect → status bukan 204 → return False.
        """
        import urllib.request
        try:
            req = urllib.request.urlopen(
                "http://clients3.google.com/generate_204",
                timeout=timeout,
            )
            return req.status == 204
        except Exception:
            return False

    def detect_captive_portal_url(self, timeout: int = 8) -> Optional[str]:
        """
        Deteksi URL halaman login captive portal secara otomatis, seperti
        yang dilakukan Windows / macOS / Android.

        Teknik: kirim HTTP GET ke beberapa URL probe yang sudah dikenal.
        - Jika redirect → URL tujuan redirect adalah halaman login portal.
        - Jika respons bukan yang diharapkan (bukan 204/200 dengan konten tepat)
          → mungkin captive portal memodifikasi halaman → ambil URL final.

        Return: URL portal (str) jika terdeteksi, None jika internet normal / tidak tahu.
        """
        import urllib.request
        import urllib.error

        for probe_url in self._PROBE_URLS:
            try:
                # Nonaktifkan redirect otomatis agar bisa tangkap 302
                class _NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        return None  # tolak redirect → raise HTTPError

                opener = urllib.request.build_opener(_NoRedirect)
                resp = opener.open(probe_url, timeout=timeout)

                # Tidak ada redirect — cek apakah respons normal
                if probe_url.endswith("generate_204") and resp.status == 204:
                    return None  # internet normal
                if probe_url.endswith("connecttest.txt"):
                    body = resp.read(64).decode("utf-8", errors="ignore")
                    if "Microsoft Connect Test" in body:
                        return None  # internet normal
                # Konten tidak sesuai — portal mengubah isi halaman
                # Coba probe URL berikutnya untuk dapat redirect URL yang lebih jelas
                continue

            except urllib.error.HTTPError as e:
                # HTTP 3xx redirect: lokasi tujuan = halaman login portal
                if e.code in (301, 302, 303, 307, 308):
                    location = e.headers.get("Location", "")
                    if location and location.startswith("http"):
                        return location
                # HTTP lain (403, dll) dari portal — gunakan probe_url sebagai fallback
                if e.code in (200, 403, 401):
                    # Coba baca Location header
                    loc = e.headers.get("Location", "")
                    if loc and loc.startswith("http"):
                        return loc
                continue
            except Exception:
                continue

        # Semua probe tidak memberi redirect — internet mungkin normal atau
        # portal memakai teknik lain (DNS poisoning). Coba sekali lagi via
        # urllib dengan allow_redirect=True dan lihat URL akhir.
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://clients3.google.com/generate_204",
                headers={"User-Agent": "Mozilla/5.0 (Linux; Raspberry Pi)"},
            )
            resp = urllib.request.urlopen(req, timeout=timeout)
            final_url = resp.geturl()
            if "google.com" not in final_url and "gstatic.com" not in final_url:
                return final_url  # diarahkan ke domain lain = portal
        except Exception:
            pass

        return None

    def captive_login(self, url: str, username_field: str, password_field: str,
                      username: str, password: str,
                      extra_fields: Optional[Dict] = None) -> Dict:
        """
        Login ke captive portal kampus via HTTP POST.

        Langkah:
        1. GET halaman login untuk dapat cookie/token.
        2. POST form dengan username & password.
        3. Verifikasi internet sudah bisa diakses.

        Return: {success, message, status_code?}
        """
        import urllib.request
        import urllib.parse
        import urllib.error
        import http.cookiejar

        url = (url or "").strip()
        username = (username or "").strip()
        if not url:
            return {"success": False, "message": "URL captive portal belum diisi"}
        if not username:
            return {"success": False, "message": "Username belum diisi"}

        # Siapkan cookie jar agar session cookie dikirim saat POST
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [("User-Agent", "Mozilla/5.0 (Linux; Raspberry Pi)")]

        try:
            # 1. GET halaman login (ambil cookie/hidden token)
            opener.open(url, timeout=10)
        except Exception:
            pass  # lanjut meski GET gagal — beberapa portal langsung terima POST

        payload = {
            username_field or "username": username,
            password_field or "password": password,
        }
        if extra_fields:
            payload.update(extra_fields)

        data = urllib.parse.urlencode(payload).encode("utf-8")
        try:
            resp = opener.open(url, data=data, timeout=15)
            status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception as e:
            return {"success": False, "message": f"Gagal mengirim login: {e}"}

        # Beri waktu sesaat agar jaringan stabil lalu cek internet
        import time
        time.sleep(2)
        internet_ok = self.check_internet()

        if internet_ok:
            return {"success": True, "message": "Login berhasil! Internet sekarang aktif.", "status_code": status}

        if status in (200, 302, 303):
            return {
                "success": False,
                "message": (
                    f"Form terkirim (HTTP {status}) tapi internet belum aktif. "
                    "Periksa username/password atau URL portal."
                ),
                "status_code": status,
            }
        return {
            "success": False,
            "message": f"Login gagal (HTTP {status}). Periksa URL dan kredensial.",
            "status_code": status,
        }

    def access_addresses(self, web_port: int = 5000,
                         ap_ip: str = "192.168.50.1",
                         lan_iface: str = "eth0") -> Dict:
        """
        Rakit daftar alamat URL untuk mengakses antarmuka web, berdasarkan
        koneksi aktif (WiFi AP, WiFi/jaringan lokal, LAN kabel).

        Hanya alamat yang benar-benar aktif yang ikut dikembalikan, sehingga
        pengguna tahu URL mana yang bisa dipakai dari posisi jaringan mereka.
        """
        conn = self.connectivity(lan_iface=lan_iface)
        items = []

        # 1. WiFi AP (hotspot robot) — IP statis, selalu tersedia bila AP aktif
        items.append({
            "type": "ap",
            "label": "WiFi AP (hotspot robot)",
            "url": f"http://{ap_ip}:{web_port}",
            "note": "Sambungkan ke WiFi 'SolarPanelCleaner' lalu buka alamat ini",
        })

        # 2. WiFi client (jaringan lokal) — hanya bila terhubung & punya IP
        wifi = conn.get("wifi", {})
        if wifi.get("connected") and wifi.get("ip"):
            items.append({
                "type": "wifi",
                "label": "WiFi / Jaringan Lokal",
                "url": f"http://{wifi['ip']}:{web_port}",
                "note": f"Via router{(' ' + wifi['ssid']) if wifi.get('ssid') else ''}",
            })

        # 3. LAN kabel — hanya bila kabel terpasang & punya IP
        lan = conn.get("lan", {})
        if lan.get("connected") and lan.get("ip"):
            items.append({
                "type": "lan",
                "label": "LAN (kabel)",
                "url": f"http://{lan['ip']}:{web_port}",
                "note": "Via kabel ethernet",
            })

        return {"success": True, "addresses": items, "primary": conn.get("primary")}

