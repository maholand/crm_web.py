# crm_web.py
from flask import Flask, render_template_string, request, redirect, url_for, send_file, session
import sqlite3
import os
import base64
from io import BytesIO
from datetime import datetime, timedelta
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "ugur_akademi_2025_secure_key"  # Güvenlik için sabit ama gizli tut
DB = "crm.db"

# === 1. VERİTABANI BAŞLATMA ===
def init_db():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT,
            company TEXT,
            birth_date DATE,
            notes TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            lesson_count INTEGER NOT NULL,
            price REAL NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            package_id INTEGER,
            sale_date DATE NOT NULL,
            total_amount REAL NOT NULL,
            amount_paid REAL DEFAULT 0,
            is_paid BOOLEAN DEFAULT 0,
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(package_id) REFERENCES packages(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lessons_used (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER,
            lesson_number INTEGER,
            used_date DATE,
            FOREIGN KEY(sale_id) REFERENCES sales(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lesson_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER,
            lesson_number INTEGER,
            scheduled_date DATE,
            status TEXT DEFAULT 'Planlandı'
        )
    ''')

    # Varsayılan paketler
    cursor.execute("SELECT COUNT(*) FROM packages")
    if cursor.fetchone()[0] == 0:
        packages = [("8 Ders", 8, 1600), ("10 Ders", 10, 1900), ("12 Ders", 12, 2160), ("16 Ders", 16, 2720)]
        cursor.executemany("INSERT INTO packages (name, lesson_count, price) VALUES (?, ?, ?)", packages)

    conn.commit()
    conn.close()

# === 2. GİRİŞ KONTROLÜ ===
def login_required(f):
    def wrapper(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == "admin" and password == "12345":  # Basit kimlik doğrulama
            session['logged_in'] = True
            return redirect(url_for("index"))
        else:
            return "<p style='color:red; text-align:center; margin-top:50px;'>❌ Geçersiz giriş!</p>", 401
    return '''
    <style>
        body { font-family: Arial, sans-serif; background: #f0f2f5; }
        .login-box { width: 350px; margin: 100px auto; padding: 30px; border-radius: 12px; 
                     background: white; box-shadow: 0 4px 12px rgba(0,0,0,0.1); text-align: center; }
        input[type="text"], input[type="password"] { width: 100%; padding: 12px; margin: 10px 0;
                                                    border: 1px solid #ccc; border-radius: 6px; font-size: 14px; }
        button { background: #007BFF; color: white; padding: 12px; width: 100%; border: none; 
                 border-radius: 6px; font-size: 16px; cursor: pointer; }
        button:hover { background: #0056b3; }
        h2 { margin-bottom: 20px; color: #333; }
    </style>
    <div class="login-box">
        <h2>🔐 UGUR CRM Girişi</h2>
        <form method="post">
            <input type="text" name="username" placeholder="Kullanıcı Adı" required><br>
            <input type="password" name="password" placeholder="Şifre" required><br>
            <button type="submit">Giriş Yap</button>
        </form>
    </div>
    '''

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

# === 3. ANA SAYFA ve ROUTELAR ===
@app.route("/")
@login_required
def index():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    # Müşteriler
    cursor.execute("SELECT * FROM customers ORDER BY name")
    customers = cursor.fetchall()

    # Paketler
    cursor.execute("SELECT * FROM packages")
    packages = cursor.fetchall()

    # Seçilen müşteri varsa satışlarını yükle
    customer_id = request.args.get("customer_id")
    selected_customer = None
    sales = []
    if customer_id:
        cursor.execute("SELECT * FROM customers WHERE id=?", (customer_id,))
        selected_customer = cursor.fetchone()
        cursor.execute("""
            SELECT s.*, p.name as package_name 
            FROM sales s
            JOIN packages p ON s.package_id = p.id
            WHERE s.customer_id=?
            ORDER BY s.sale_date DESC
        """, (customer_id,))
        cols = [desc[0] for desc in cursor.description]
        sales_data = cursor.fetchall()
        sales = [dict(zip(cols, row)) for row in sales_data]

    conn.close()

    return render_template_string(TEMPLATE,
        customers=customers,
        packages=packages,
        selected_customer=selected_customer,
        sales=sales,
        today=datetime.now().strftime("%Y-%m-%d"),
        schedules=get_schedules(),
        all_sales_with_names=get_all_sales_with_names(),
        graph_url=generate_chart()
    )

@app.route("/add_customer", methods=["POST"])
@login_required
def add_customer():
    data = request.form
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    try:
        if data.get("customer_id"):
            cursor.execute("""
                UPDATE customers SET name=?, email=?, phone=?, company=?, birth_date=?, notes=?
                WHERE id=?
            """, (data['name'], data['email'], data['phone'], data['company'], data['birth_date'], data['notes'], data['customer_id']))
        else:
            cursor.execute("""
                INSERT INTO customers (name, email, phone, company, birth_date, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (data['name'], data['email'], data['phone'], data['company'], data['birth_date'], data['notes']))
        conn.commit()
    except sqlite3.IntegrityError:
        return "❌ Bu e-posta adresi zaten kayıtlı!", 400
    finally:
        conn.close()
    return redirect(url_for("index") + (f"?customer_id={data['customer_id']}" if data.get("customer_id") else ""))

@app.route("/clear")
@login_required
def clear():
    return redirect(url_for("index"))

@app.route("/add_sale", methods=["POST"])
@login_required
def add_sale():
    data = request.form
    is_paid = bool(data.get("is_paid"))
    amount_paid = float(data.get("amount_paid") or 0)

    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sales (customer_id, package_id, sale_date, total_amount, amount_paid, is_paid)
        VALUES (?, ?, ?, (SELECT price FROM packages WHERE id=?), ?, ?)
    """, (data['customer_id'], data['package_id'], data['sale_date'], data['package_id'], amount_paid, is_paid))
    conn.commit()
    conn.close()
    return redirect(f"/?customer_id={data['customer_id']}")

@app.route("/api/sales")
@login_required
def api_sales():
    customer_id = request.args.get("customer_id")
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.id, p.name as package_name, s.sale_date 
        FROM sales s
        JOIN packages p ON s.package_id = p.id
        WHERE s.customer_id=?
    """, (customer_id,))
    rows = cursor.fetchall()
    result = [{"id": r[0], "package_name": r[1], "sale_date": r[2]} for r in rows]
    conn.close()
    return result

@app.route("/schedule_lesson", methods=["POST"])
@login_required
def schedule_lesson():
    data = request.form
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO lesson_schedule (sale_id, lesson_number, scheduled_date, status)
        VALUES (?, ?, ?, 'Planlandı')
    """, (data['sale_id'], data['lesson_number'], data['scheduled_date']))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

@app.route("/mark_done/<int:sid>")
@login_required
def mark_done(sid):
    update_status(sid, "Gerçekleşti")
    return redirect(url_for("index"))

@app.route("/cancel/<int:sid>")
@login_required
def cancel(sid):
    update_status(sid, "İptal")
    return redirect(url_for("index"))

def update_status(schedule_id, status):
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("UPDATE lesson_schedule SET status=? WHERE id=?", (status, schedule_id))
    conn.commit()
    conn.close()

def get_schedules():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ls.id, ls.lesson_number, ls.scheduled_date, ls.status, c.name as customer_name
        FROM lesson_schedule ls
        JOIN sales s ON ls.sale_id = s.id
        JOIN customers c ON s.customer_id = c.id
        ORDER BY ls.scheduled_date DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(['id', 'lesson_number', 'scheduled_date', 'status', 'customer_name'], r)) for r in rows]

def get_all_sales_with_names():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.id, c.name as customer_name, p.name as package_name
        FROM sales s
        JOIN customers c ON s.customer_id = c.id
        JOIN packages p ON s.package_id = p.id
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(['id', 'customer_name', 'package_name'], r)) for r in rows]

@app.route("/pdf_report", methods=["POST"])
@login_required
def pdf_report():
    report_type = request.form["report_type"]
    obj_id = request.form["id"]
    filename = f"{report_type}_rapor_{obj_id}.pdf"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "CRM RAPORU", ln=True, align="C")
    pdf.ln(10)

    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    if report_type == "customer":
        cursor.execute("SELECT * FROM customers WHERE id=?", (obj_id,))
        cust = cursor.fetchone()
        if cust:
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, f"Müşteri: {cust[1]}", ln=True)
            pdf.set_font("Arial", "", 12)
            pdf.cell(0, 8, f"E-posta: {cust[2]}", ln=True)
            pdf.cell(0, 8, f"Telefon: {cust[3]}", ln=True)
            pdf.cell(0, 8, f"Şirket: {cust[4]}", ln=True)
            pdf.cell(0, 8, f"Doğum: {cust[5] or 'Belirtilmemiş'}", ln=True)
            pdf.multi_cell(0, 8, f"Notlar: {cust[6] or 'Yok'}")

            pdf.ln(10)
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Satış Geçmişi", ln=True)
            cursor.execute("""
                SELECT p.name, s.sale_date, s.total_amount, s.amount_paid, s.is_paid
                FROM sales s
                JOIN packages p ON s.package_id = p.id
                WHERE s.customer_id = ?
            """, (obj_id,))
            sales = cursor.fetchall()
            for sale in sales:
                status = "Ödendi" if sale[4] else "Bekliyor"
                pdf.cell(0, 8, f"{sale[0]} - {sale[1]} - {sale[2]:.2f}₺ ({status})", ln=True)
    else:
        cursor.execute("""
            SELECT s.*, c.name, p.name, p.lesson_count
            FROM sales s
            JOIN customers c ON s.customer_id = c.id
            JOIN packages p ON s.package_id = p.id
            WHERE s.id = ?
        """, (obj_id,))
        sale = cursor.fetchone()
        if sale:
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, f"Satış Raporu #{sale[0]}", ln=True)
            pdf.set_font("Arial", "", 12)
            pdf.cell(0, 8, f"Müşteri: {sale[7]}", ln=True)
            pdf.cell(0, 8, f"Paket: {sale[8]} ({sale[9]} ders)", ln=True)
            pdf.cell(0, 8, f"Tarih: {sale[3]}", ln=True)
            pdf.cell(0, 8, f"Tutar: {sale[5]:.2f} ₺", ln=True)
            pdf.cell(0, 8, f"Ödenen: {sale[4]:.2f} ₺", ln=True)
            pdf.cell(0, 8, f"Durum: {'Ödendi' if sale[6] else 'Bekliyor'}", ln=True)

            cursor.execute("""
                SELECT lesson_number, scheduled_date, status 
                FROM lesson_schedule 
                WHERE sale_id = ? ORDER BY scheduled_date
            """, (obj_id,))
            schedule = cursor.fetchall()
            pdf.ln(10)
            pdf.set_font("Arial", "B", 14)
            pdf.cell(0, 10, "Ders Planı", ln=True)
            for row in schedule:
                pdf.cell(0, 8, f"Ders {row[0]}: {row[1]} - {row[2]}", ln=True)
    conn.close()

    pdf.output(filename)
    return send_file(filename, as_attachment=True)

def generate_chart():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    months = []
    paid = []
    pending = []

    today = datetime.now()
    for i in range(11, -1, -1):
        d = today.replace(year=(today.year - 1 if today.month <= i else today.year),
                          month=((today.month - i - 1) % 12 + 1)).replace(day=1)
        start = d.strftime("%Y-%m-01")
        next_month = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month.strftime("%Y-%m-%d")
        months.append(d.strftime("%b '%y"))

        cursor.execute("""
            SELECT COALESCE(SUM(total_amount),0), COALESCE(SUM(amount_paid),0)
            FROM sales WHERE sale_date BETWEEN ? AND ?
        """, (start, end))
        total, paid_amt = cursor.fetchone()
        paid.append(paid_amt)
        pending.append(total - paid_amt)
    conn.close()

    fig, ax = plt.subplots(figsize=(10, 4))
    x = range(12)
    ax.bar(x, paid, label='Ödenen', color='#4CAF50', width=0.4)
    ax.bar([i + 0.4 for i in x], pending, label='Bekleyen', color='#FF9800', width=0.4)
    ax.set_xticks([i + 0.2 for i in x])
    ax.set_xticklabels(months)
    ax.legend()
    ax.set_title("Aylık Satış Analizi")
    ax.set_ylabel("Tutar (₺)")

    img = BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()
    plt.close()
    return f"data:image/png;base64,{plot_url}"

# === HTML ŞABLONU (TÜM ARAYÜZ BURADA) ===
TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>UGUR CRM</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap @5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js "></script>
    <style>
        body { background: #f4f6f9; font-family: Arial, sans-serif; }
        .navbar { background: #2c3e50; }
        .card { box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .tab-content { margin-top: 20px; }
        .form-label { font-weight: bold; }
        footer { margin-top: 50px; text-align: center; color: #7f8c8d; }
    </style>
</head>
<body>

<nav class="navbar navbar-dark">
    <div class="container-fluid">
        <span class="navbar-brand">📊 UGUR WEB CRM</span>
        <a href="/logout" class="btn btn-outline-light btn-sm">Çıkış</a>
    </div>
</nav>

<div class="container mt-4">
    <ul class="nav nav-tabs" id="crmTab">
        <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#musteri">Müşteri & Satış</a></li>
        <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#takvim">Ders Takvimi</a></li>
        <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#rapor">Raporlama</a></li>
        <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#analiz">Analitik</a></li>
    </ul>

    <div class="tab-content">

<!-- MÜŞTERİ & SATIŞ -->
<div class="tab-pane fade show active" id="musteri">
    <div class="row mt-3">
        <div class="col-md-5">
            <div class="card">
                <div class="card-header bg-primary text-white">Müşteri Ekle/Düzenle</div>
                <div class="card-body">
                    <form method="post" action="/add_customer">
                        <input type="hidden" name="customer_id" value="{{ customer.id if customer else '' }}">
                        <div class="mb-3">
                            <label class="form-label">Ad Soyad *</label>
                            <input type="text" name="name" class="form-control" value="{{ customer.name if customer else '' }}" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">E-posta *</label>
                            <input type="email" name="email" class="form-control" value="{{ customer.email if customer else '' }}" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Telefon</label>
                            <input type="text" name="phone" class="form-control" value="{{ customer.phone if customer else '' }}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Şirket</label>
                            <input type="text" name="company" class="form-control" value="{{ customer.company if customer else '' }}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Doğum Tarihi</label>
                            <input type="date" name="birth_date" class="form-control" value="{{ customer.birth_date if customer else '' }}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Notlar</label>
                            <textarea name="notes" class="form-control" rows="3">{{ customer.notes if customer else '' }}</textarea>
                        </div>
                        <button type="submit" class="btn btn-success">💾 Kaydet</button>
                        {% if customer %}<a href="/clear" class="btn btn-secondary">Yeni Ekle</a>{% endif %}
                    </form>
                </div>
            </div>
        </div>

        <div class="col-md-7">
            <div class="card">
                <div class="card-header bg-success text-white">Satış Yap</div>
                <div class="card-body">
                    <form method="post" action="/add_sale">
                        <div class="mb-3">
                            <label class="form-label">Müşteri Seç</label>
                            <select name="customer_id" class="form-select" onchange="this.form.submit()" required>
                                <option value="">-- Seçin --</option>
                                {% for c in customers %}
                                <option value="{{ c[0] }}" {% if selected_customer and selected_customer[0]==c[0] %}selected{% endif %}>{{ c[1] }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </form>

                    {% if selected_customer %}
                    <form method="post" action="/add_sale">
                        <input type="hidden" name="customer_id" value="{{ selected_customer[0] }}">
                        <div class="mb-3">
                            <label class="form-label">Paket</label>
                            <select name="package_id" class="form-select" required>
                                {% for p in packages %}
                                <option value="{{ p[0] }}">{{ p[1] }} ({{ "%.2f"|format(p[3]) }} ₺)</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Tarih</label>
                            <input type="date" name="sale_date" class="form-control" value="{{ today }}" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Ödenen Miktar (₺)</label>
                            <input type="number" step="0.01" name="amount_paid" class="form-control" placeholder="0.00">
                        </div>
                        <div class="mb-3 form-check">
                            <input type="checkbox" name="is_paid" class="form-check-input" id="is_paid">
                            <label class="form-check-label" for="is_paid">Tam Ödendi</label>
                        </div>
                        <button type="submit" class="btn btn-primary">➕ Satışı Ekle</button>
                    </form>
                    {% endif %}

                    <!-- Satış Listesi -->
                    {% if sales %}
                    <hr>
                    <h5>Son Satışlar</h5>
                    <table class="table table-sm">
                        <thead><tr><th>Paket</th><th>Tarih</th><th>Tutar</th><th>Ödenen</th><th>Durum</th></tr></thead>
                        <tbody>
                        {% for s in sales %}
                        <tr>
                            <td>{{ s.package_name }}</td>
                            <td>{{ s.sale_date }}</td>
                            <td>{{ "%.2f"|format(s.total_amount) }} ₺</td>
                            <td>{{ "%.2f"|format(s.amount_paid) }} ₺</td>
                            <td><span class="badge bg-{% if s.is_paid %}success{% else %}warning text-dark{% endif %}">
                                {% if s.is_paid %}Ödendi{% else %}Bekliyor{% endif %}
                            </span></td>
                        </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
</div>

<!-- DERS TAKVİMİ -->
<div class="tab-pane fade" id="takvim">
    <h4 class="mt-3">📅 Ders Planlayıcı</h4>
    <form method="post" action="/schedule_lesson" class="row g-3">
        <div class="col-md-3">
            <label class="form-label">Müşteri</label>
            <select name="customer_id" class="form-select" id="cust_select" onchange="loadSales(this.value)">
                <option value="">-- Seçin --</option>
                {% for c in customers %}
                <option value="{{ c[0] }}">{{ c[1] }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="col-md-3">
            <label class="form-label">Satış</label>
            <select name="sale_id" class="form-select" id="sale_select">
                <option value="">Önce müşteri seçin</option>
            </select>
        </div>
        <div class="col-md-2">
            <label class="form-label">Ders No</label>
            <input type="number" name="lesson_number" class="form-control" min="1" max="16" required>
        </div>
        <div class="col-md-2">
            <label class="form-label">Tarih</label>
            <input type="date" name="scheduled_date" class="form-control" required>
        </div>
        <div class="col-md-2 d-flex align-items-end">
            <button type="submit" class="btn btn-primary w-100">Planla</button>
        </div>
    </form>

    <!-- Planlanan Dersler -->
    <h5 class="mt-4">Planlanan Dersler</h5>
    <table class="table">
        <thead><tr><th>Müşteri</th><th>Ders</th><th>Tarih</th><th>Durum</th><th>İşlem</th></tr></thead>
        <tbody>
        {% for s in schedules %}
        <tr>
            <td>{{ s.customer_name }}</td>
            <td>{{ s.lesson_number }}</td>
            <td>{{ s.scheduled_date }}</td>
            <td><span class="badge bg-{% if s.status=='Gerçekleşti' %}success{% elif s.status=='İptal' %}danger{% else %}primary{% endif %}">
                {{ s.status }}
            </span></td>
            <td>
                <a href="/mark_done/{{ s.id }}" class="btn btn-sm btn-success">✓</a>
                <a href="/cancel/{{ s.id }}" class="btn btn-sm btn-danger">×</a>
            </td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
</div>

<!-- RAPORLAMA -->
<div class="tab-pane fade" id="rapor">
    <h4 class="mt-3">📄 PDF Rapor Oluştur</h4>
    <div class="row">
        <div class="col-md-6">
            <div class="card">
                <div class="card-body">
                    <h5>Müşteri Raporu</h5>
                    <form action="/pdf_report" method="post">
                        <input type="hidden" name="report_type" value="customer">
                        <select name="id" class="form-select mb-2" required>
                            <option value="">-- Müşteri Seçin --</option>
                            {% for c in customers %}
                            <option value="{{ c[0] }}">{{ c[1] }}</option>
                            {% endfor %}
                        </select>
                        <button type="submit" class="btn btn-info">📥 PDF İndir</button>
                    </form>
                </div>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card">
                <div class="card-body">
                    <h5>Satış Raporu</h5>
                    <form action="/pdf_report" method="post">
                        <input type="hidden" name="report_type" value="sale">
                        <select name="id" class="form-select mb-2" required>
                            <option value="">-- Satış Seçin --</option>
                            {% for s in all_sales_with_names %}
                            <option value="{{ s.id }}">{{ s.customer_name }} - {{ s.package_name }}</option>
                            {% endfor %}
                        </select>
                        <button type="submit" class="btn btn-info">📥 PDF İndir</button>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- ANALİTİK -->
<div class="tab-pane fade" id="analiz">
    <h4 class="mt-3">📊 Aylık Satış Analizi</h4>
    <img src="{{ graph_url }}" class="img-fluid" alt="Satış Grafiği">
</div>

    </div>
</div>

<footer class="mt-5 mb-3">
    <p>&copy; 2025 Uğur Akademi CRM | Web Sürümü</p>
</footer>

<script>
function loadSales(custId) {
    const saleSelect = document.getElementById('sale_select');
    saleSelect.innerHTML = '<option value="">Yükleniyor...</option>';
    if (!custId) return;

    fetch(`/api/sales?customer_id=` + custId)
      .then(res => res.json())
      .then(data => {
        saleSelect.innerHTML = '';
        data.forEach(s => {
          const opt = document.createElement('option');
          opt.value = s.id;
          opt.textContent = s.package_name + ' (' + s.sale_date + ')';
          saleSelect.appendChild(opt);
        });
      });
}
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap @5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# === 4. SUNUCUYU BAŞLAT ===
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))  # Render için PORT desteği
    app.run(host="0.0.0.0", port=port, debug=False)
