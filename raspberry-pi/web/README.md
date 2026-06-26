# Web Interface - Solar Panel Cleaner

## 📁 Struktur Folder

```
web/
├── static/                 # Static files (CSS, JS, images)
│   ├── css/
│   │   └── main.css       # Main stylesheet
│   ├── js/
│   │   ├── main.js        # Main JavaScript (dashboard)
│   │   └── testing.js     # Testing page JavaScript
│   ├── logo-ugm.png       # UGM logo
│   └── README.md
│
├── templates/              # HTML templates (Jinja2)
│   ├── base.html          # Base template (header, nav, footer)
│   ├── dashboard.html     # Main dashboard page
│   └── testing.html       # System testing page
│
├── server.py              # Flask web server
└── README.md              # This file
```

## 🎨 Refactoring yang Dilakukan

### Sebelum (Monolithic)
- ❌ Semua CSS, JS, dan HTML dalam satu file `index.html`
- ❌ Sulit untuk maintenance
- ❌ Tidak ada halaman testing
- ❌ Code duplication

### Sesudah (Modular)
- ✅ CSS terpisah di `static/css/main.css`
- ✅ JavaScript terpisah di `static/js/`
- ✅ HTML menggunakan template inheritance (Jinja2)
- ✅ Halaman testing terpisah
- ✅ Mudah untuk maintenance dan development

## 📄 Halaman yang Tersedia

### 1. Dashboard (`/`)
**File:** `templates/dashboard.html`

Fitur:
- Preview kamera real-time
- Setup zona deteksi (drag & drop)
- Status sistem (ESP32, cleaning, dll)
- Konfigurasi pembersihan
- Manual trigger cleaning
- Capture & analisis

### 2. System Testing (`/testing`)
**File:** `templates/testing.html`

Fitur:
- Test koneksi ESP32
- Test hardware (motor, pump, limit switch, encoder)
- Test kamera dan YOLO
- Test komunikasi serial
- Emergency stop button
- Test log display
- Run all tests (automated)

## 🔌 API Endpoints

### Dashboard APIs
```
GET  /                      - Dashboard page
GET  /api/status            - Get system status
GET  /api/preview           - Get camera preview (base64)
GET  /api/zones             - Get configured zones
POST /api/zones             - Save zones
GET  /api/config            - Get cleaning config
POST /api/config            - Save cleaning config
POST /api/capture           - Manual capture & detection
POST /api/trigger           - Manual trigger cleaning
POST /api/stop              - Stop cleaning
```

### Testing APIs
```
GET  /testing                           - Testing page
GET  /api/test/esp32/connection         - Test ESP32 connection
POST /api/test/esp32/motor_wiper        - Test motor wiper
POST /api/test/esp32/motor_brush        - Test motor brush
POST /api/test/esp32/pump               - Test water pump
GET  /api/test/esp32/limit_switches     - Test limit switches
GET  /api/test/esp32/encoder            - Test encoder
POST /api/test/esp32/cleaning_cycle     - Test cleaning cycle
GET  /api/test/camera                   - Test camera
GET  /api/test/yolo                     - Test YOLO model
POST /api/test/detection                - Test detection
GET  /api/test/serial                   - Test serial comm
GET  /api/test/config                   - Test configuration
POST /api/emergency_stop                - Emergency stop
```

## 🎯 Cara Menggunakan

### Development
```bash
# Install dependencies
pip install flask flask-cors opencv-python

# Run server
cd raspberry-pi
python main.py

# Access web interface
# Dashboard: http://localhost:5000/
# Testing:   http://localhost:5000/testing
```

### Production
```bash
# Use gunicorn for production
pip install gunicorn

# Run with gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 web.server:app
```

## 🔧 Customization

### Menambah Halaman Baru

1. **Buat template HTML:**
```html
<!-- templates/new_page.html -->
{% extends "base.html" %}

{% block title %}New Page{% endblock %}

{% block content %}
<h1>New Page Content</h1>
{% endblock %}
```

2. **Tambah route di server.py:**
```python
@app.route('/new-page')
def new_page():
    return render_template('new_page.html', active_page='new-page')
```

3. **Tambah tab di base.html:**
```html
<button class="nav-tab {% if active_page == 'new-page' %}active{% endif %}" 
        onclick="window.location.href='/new-page'">
    New Page
</button>
```

### Menambah CSS Custom

Tambahkan di `static/css/main.css` atau buat file CSS baru:
```css
/* static/css/custom.css */
.my-custom-class {
    color: #003d7a;
}
```

Lalu include di template:
```html
{% block extra_css %}
<link rel="stylesheet" href="/static/css/custom.css">
{% endblock %}
```

### Menambah JavaScript Custom

Tambahkan di `static/js/main.js` atau buat file JS baru:
```javascript
// static/js/custom.js
function myCustomFunction() {
    console.log('Custom function');
}
```

Lalu include di template:
```html
{% block extra_js %}
<script src="/static/js/custom.js"></script>
{% endblock %}
```

## 🎨 Styling Guide

### Color Palette
```css
Primary Blue:   #003d7a  /* UGM Blue */
Secondary Gold: #f4b41a  /* UGM Gold */
Success Green:  #28a745
Danger Red:     #dc3545
Warning Yellow: #ffc107
Gray:           #6c757d
Light Gray:     #f5f5f5
```

### Typography
```css
Font Family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif
Heading:     28px, 600 weight
Subtitle:    14px
Body:        14px
Small:       11-13px
```

### Responsive Breakpoints
```css
Mobile:  max-width: 768px
Tablet:  769px - 1024px
Desktop: 1025px+
```

## 📱 Mobile Responsive

Web interface sudah responsive untuk mobile:
- Grid layout berubah menjadi single column
- Video preview full width
- Touch-friendly buttons
- Optimized font sizes

## 🔒 Security Notes

1. **CORS:** Enabled untuk development, disable untuk production
2. **Input Validation:** Semua input dari user di-validate
3. **Error Handling:** Semua error di-catch dan di-log
4. **Authentication:** Belum ada, tambahkan jika perlu

## 🐛 Troubleshooting

### CSS tidak load
```bash
# Clear browser cache
Ctrl + Shift + R (Chrome/Firefox)

# Check file path
ls raspberry-pi/web/static/css/main.css
```

### JavaScript error
```bash
# Check browser console
F12 -> Console tab

# Check file path
ls raspberry-pi/web/static/js/main.js
```

### Template not found
```bash
# Check template path
ls raspberry-pi/web/templates/

# Check Flask template folder config
# Should be: templates/ (relative to server.py)
```

## 📚 Resources

- [Flask Documentation](https://flask.palletsprojects.com/)
- [Jinja2 Templates](https://jinja.palletsprojects.com/)
- [Bootstrap (if needed)](https://getbootstrap.com/)
- [Chart.js (for graphs)](https://www.chartjs.org/)

## 🚀 Future Improvements

- [ ] Add authentication (login/logout)
- [ ] Add real-time graphs (Chart.js)
- [ ] Add data logging and history
- [ ] Add export data (CSV/JSON)
- [ ] Add dark mode toggle
- [ ] Add multi-language support
- [ ] Add WebSocket for real-time updates
- [ ] Add mobile app (PWA)

---

**Last Updated:** 2025-01-20  
**Version:** 2.0  
**Author:** Muhammad Ridho Assidiqi
