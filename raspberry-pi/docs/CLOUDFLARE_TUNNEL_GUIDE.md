# Cloudflare Tunnel Guide - Remote Access

Setup akses remote yang **aman dan mudah** menggunakan Cloudflare Tunnel (gratis).

## 🎯 Keuntungan Cloudflare Tunnel

✅ **Tidak perlu port forwarding** di router  
✅ **Tidak perlu IP public static**  
✅ **HTTPS otomatis** (SSL/TLS gratis)  
✅ **Aman** - tidak expose port ke internet  
✅ **Gratis** - Cloudflare Zero Trust free tier  
✅ **Mudah setup** - script otomatis  
✅ **Auto-reconnect** - jika koneksi putus  

---

## 📋 Prerequisites

### 1. **Cloudflare Account (Gratis)**
Daftar di: https://dash.cloudflare.com/sign-up

### 2. **Domain Name**
Pilihan:
- **Punya domain sendiri** (misal: `example.com`)
- **Gunakan subdomain gratis** dari Cloudflare (misal: `solarpanel.pages.dev`)
- **Beli domain murah** (misal: di Cloudflare Registrar, Namecheap, dll)

### 3. **Domain di Cloudflare**
Jika punya domain, tambahkan ke Cloudflare:
1. Login ke Cloudflare Dashboard
2. Klik "Add a Site"
3. Masukkan domain Anda
4. Ikuti instruksi untuk ubah nameserver

---

## 🚀 Cara Setup

### **Step 1: Jalankan Script Setup**
```bash
cd ~/wipevision/raspberry-pi
sudo bash setup_cloudflare_tunnel.sh
```

### **Step 2: Authenticate**
Script akan membuka browser untuk login Cloudflare.

**Jika via SSH:**
1. Copy URL yang muncul di terminal
2. Paste di browser di komputer Anda
3. Login dan authorize

### **Step 3: Buat Tunnel**
```
Enter tunnel name: solar-panel-cleaner
```

### **Step 4: Masukkan Domain**
```
Enter your domain: solarpanel.example.com
```

Atau gunakan subdomain:
```
Enter your domain: panel.example.com
```

### **Step 5: Selesai!**
Tunnel otomatis jalan dan bisa diakses via:
```
https://solarpanel.example.com
```

---

## 🌐 Cara Akses

### **Dari Mana Saja (Internet):**
```
https://solarpanel.example.com
```

✅ **HTTPS otomatis** (SSL/TLS)  
✅ **Tidak perlu port** (`:5000` tidak perlu)  
✅ **Aman** (encrypted)  

### **Dari Local Network (Tetap Bisa):**
```
http://192.168.1.9:5000/
```

### **Dari WiFi AP (Tetap Bisa):**
```
http://192.168.4.1:5000/
```

**Semua cara akses tetap berfungsi!**

---

## 🔧 Management Commands

### **Cek Status Tunnel:**
```bash
sudo systemctl status cloudflared
```

### **View Logs:**
```bash
sudo journalctl -u cloudflared -f
```

### **Restart Tunnel:**
```bash
sudo systemctl restart cloudflared
```

### **Stop Tunnel:**
```bash
sudo systemctl stop cloudflared
```

### **List Tunnels:**
```bash
cloudflared tunnel list
```

### **Tunnel Info:**
```bash
cloudflared tunnel info solar-panel-cleaner
```

---

## 🔐 Keamanan

### **1. Cloudflare Access (Optional - Recommended)**

Tambahkan authentication layer:

1. Login ke Cloudflare Dashboard
2. Pilih domain Anda
3. Klik "Zero Trust" → "Access" → "Applications"
4. Klik "Add an application"
5. Pilih "Self-hosted"
6. Konfigurasi:
   - **Application name:** Solar Panel Cleaner
   - **Subdomain:** solarpanel
   - **Domain:** example.com
7. Tambahkan policy:
   - **Rule name:** Allow specific emails
   - **Action:** Allow
   - **Include:** Emails → masukkan email Anda
8. Save

Sekarang hanya email yang diizinkan yang bisa akses!

### **2. Rate Limiting**

Cloudflare otomatis protect dari DDoS dan brute force.

### **3. Firewall Rules**

Tambahkan firewall rules di Cloudflare Dashboard jika perlu.

---

## 🐛 Troubleshooting

### **Tunnel tidak connect:**
```bash
# Cek status
sudo systemctl status cloudflared

# Cek logs
sudo journalctl -u cloudflared -n 50

# Restart
sudo systemctl restart cloudflared
```

### **Domain tidak bisa diakses:**
```bash
# Cek DNS record
nslookup solarpanel.example.com

# Cek tunnel route
cloudflared tunnel route dns list
```

### **Error "tunnel credentials file not found":**
```bash
# Cek file credentials
ls -la ~/.cloudflared/

# Re-authenticate
cloudflared tunnel login
```

### **Service tidak auto-start setelah reboot:**
```bash
# Enable service
sudo systemctl enable cloudflared

# Check status
sudo systemctl is-enabled cloudflared
```

---

## 🗑️ Cara Remove

### **Remove Tunnel:**
```bash
sudo bash remove_cloudflare_tunnel.sh
```

### **Manual Removal:**
```bash
# Stop service
sudo systemctl stop cloudflared
sudo systemctl disable cloudflared

# Remove service file
sudo rm /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload

# Delete tunnel
cloudflared tunnel delete solar-panel-cleaner

# Remove binary
sudo rm /usr/local/bin/cloudflared

# Remove config
rm -rf ~/.cloudflared
```

---

## 📊 Perbandingan dengan Port Forwarding

| Feature | Cloudflare Tunnel | Port Forwarding |
|---------|-------------------|-----------------|
| Setup | ✅ Mudah (script) | ⚠️ Manual (router) |
| Port Forwarding | ❌ Tidak perlu | ✅ Perlu |
| Static IP | ❌ Tidak perlu | ✅ Perlu |
| HTTPS/SSL | ✅ Otomatis gratis | ⚠️ Manual (Let's Encrypt) |
| Keamanan | ✅ Tinggi (Cloudflare) | ⚠️ Tergantung config |
| DDoS Protection | ✅ Gratis | ❌ Tidak ada |
| Biaya | ✅ Gratis | ✅ Gratis |
| Kecepatan | ✅ Cepat (CDN) | ✅ Direct |

**Rekomendasi:** Gunakan Cloudflare Tunnel untuk production!

---

## 🎯 Use Cases

### **Use Case 1: Remote Monitoring**
```
Raspberry Pi di lapangan
↓
Cloudflare Tunnel aktif
↓
Akses dari kantor/rumah
↓
https://solarpanel.example.com
```

### **Use Case 2: Demo/Presentasi**
```
Raspberry Pi di lab
↓
Share link ke audience
↓
https://solarpanel.example.com
↓
Audience bisa akses dari device mereka
```

### **Use Case 3: Multi-Site Monitoring**
```
Raspberry Pi 1 → https://site1.example.com
Raspberry Pi 2 → https://site2.example.com
Raspberry Pi 3 → https://site3.example.com
↓
Monitor semua dari satu dashboard
```

---

## 💡 Tips

### **1. Gunakan Subdomain**
Lebih mudah manage:
- `panel1.example.com` → Site 1
- `panel2.example.com` → Site 2
- `panel3.example.com` → Site 3

### **2. Enable Cloudflare Analytics**
Gratis, bisa lihat:
- Jumlah visitor
- Bandwidth usage
- Request per second
- Geographic distribution

### **3. Gunakan Cloudflare Access**
Tambahkan authentication untuk keamanan extra.

### **4. Setup Notifications**
Cloudflare bisa kirim notifikasi jika tunnel down.

---

## 📝 Catatan

- Tunnel otomatis reconnect jika koneksi putus
- Cloudflare free tier cukup untuk 1-10 sites
- Bandwidth unlimited (tidak ada limit)
- Latency minimal (Cloudflare CDN global)
- Support HTTP/2 dan WebSocket

---

## ✅ Checklist Setup

- [ ] Cloudflare account created
- [ ] Domain added to Cloudflare
- [ ] Script `setup_cloudflare_tunnel.sh` executed
- [ ] Tunnel authenticated
- [ ] Domain configured
- [ ] Service running (`systemctl status cloudflared`)
- [ ] Domain accessible via HTTPS
- [ ] (Optional) Cloudflare Access configured

---

Author: Muhammad Ridho Assidiqi  
Institution: Universitas Gadjah Mada
