# Autentikasi Web UI - Admin vs View-only

Web UI sekarang punya dua tingkat akses:

| Peran          | Bisa lihat (dashboard, status, preview, report) | Bisa aksi (trigger, testing, stop, ganti WiFi, config) |
| -------------- | :--------------------------------------------: | :----------------------------------------------------: |
| **Admin**      |                      ✅                         |                          ✅                            |
| **View-only**  |                      ✅                         |                          ❌                            |

- **View-only** = siapa pun yang membuka web tanpa login (mis. penonton demo, dosen penguji).
- **Admin** = Anda, setelah login.

## Akses per Halaman

| Halaman                  | View-only | Admin |
| ------------------------ | :-------: | :---: |
| Dashboard (`/`)          |    ✅     |  ✅   |
| Performance (`/performance`) | ✅    |  ✅   |
| Report (`/report`)       |    ✅     |  ✅   |
| **System Testing** (`/testing`)  | ❌ | ✅   |
| **Settings** (`/settings`)       | ❌ | ✅   |

- Tab **System Testing** & **Settings** disembunyikan dari navbar untuk view-only.
- Bila view-only membuka URL `/testing` atau `/settings` langsung, otomatis
  dialihkan (redirect) ke Dashboard.
- Settings disembunyikan karena menampilkan info sensitif (password WiFi AP,
  daftar jaringan). Testing disembunyikan karena khusus menggerakkan hardware.

## Akun Default

- Username: `taridho`
- Password: `2026`

> Password disimpan dalam bentuk **hash** (werkzeug scrypt) di
> `config/settings.yaml`, bukan plaintext.

## Cara Pakai

1. Buka web UI. Secara default berstatus **View-only** (badge "👁 View-only" di kanan atas).
2. Klik **Login** → masukkan `taridho` / `2026` → **Masuk**.
3. Badge berubah jadi "🔓 taridho" dan semua tombol aksi aktif.
4. Klik **Logout** untuk kembali ke mode view-only.

Sesi login bertahan 12 jam (bisa diubah via `auth.session_hours`).

## Cara Kerja (Teknis)

- Proteksi diterapkan di **backend** lewat `before_request`:
  - Semua request **GET/HEAD** → diizinkan (view-only untuk semua).
  - Semua request **POST/PUT/DELETE/PATCH** → wajib sesi admin, kalau tidak
    dijawab **401** `{auth_required: true}`.
  - Ini otomatis melindungi **semua** endpoint aksi, termasuk yang ditambahkan
    di masa depan — tidak perlu menandai satu per satu.
- Di **frontend** (`auth.js`), `fetch` dibungkus agar respons 401 otomatis
  memunculkan modal login + toast, tanpa mengubah kode tiap tombol.

## Ganti Username / Password

1. Buat hash password baru:
   ```bash
   python -c "from werkzeug.security import generate_password_hash as g; print(g('PasswordBaru'))"
   ```
2. Edit `config/settings.yaml` bagian `auth`:
   ```yaml
   auth:
     admin_username: namabaru
     admin_password_hash: "scrypt:..."   # tempel hash dari langkah 1
   ```
3. Restart aplikasi.

## Ganti Secret Key (disarankan untuk produksi)

`secret_key` dipakai menandatangani cookie sesi. Ganti dengan nilai acak:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Tempel ke `auth.secret_key` di `settings.yaml`.

## Menonaktifkan Auth

Set `auth.enabled: false` di `settings.yaml` bila ingin semua orang bisa
mengakses semua fitur (mis. saat development lokal).

## Catatan Keamanan

- Auth ini mencegah **perubahan tak sengaja** oleh pengunjung dan memberi
  kontrol akses dasar. Untuk keamanan penuh saat diekspos ke internet,
  kombinasikan dengan HTTPS (mis. via Cloudflare Tunnel) dan jangan
  menonaktifkan auth.
- Cookie sesi memakai tanda tangan secret_key — pastikan secret_key tidak
  bocor ke publik (jangan commit nilai produksi ke repo publik).

---

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
