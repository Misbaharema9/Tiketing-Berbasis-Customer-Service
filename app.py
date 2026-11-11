import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

import click
from flask import (Flask, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

# ================================================================
# Inisialisasi aplikasi
# ================================================================
app = Flask(__name__)
app.config.update(
    DATABASE=os.path.join(app.instance_path, 'ticketing.db'),
    SECRET_KEY=os.environ.get('SECRET_KEY', 'kunci-rahasia-ticketing-rpl2'),
    # NFR-03: sesi berakhir setelah 30 menit tidak aktif
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)
os.makedirs(app.instance_path, exist_ok=True)


# ================================================================
# Helpers database
# ================================================================
def get_db() -> sqlite3.Connection:
    """Buka (atau kembalikan) koneksi SQLite yang terikat pada request saat ini."""
    if 'db' not in g:
        g.db = sqlite3.connect(
            app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def close_db(exception=None) -> None:
    """Tutup koneksi di akhir setiap request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


app.teardown_appcontext(close_db)


# ================================================================
# Decorator: login_required
# ================================================================
def login_required(f):
    """Redirect ke halaman login jika pengguna belum login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Silakan login terlebih dahulu.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ================================================================
# Decorator: role_required
# ================================================================
def role_required(*roles):
    """
    Decorator factory — hanya izinkan role yang disebutkan.

    Contoh pemakaian:
        @role_required('admin')
        @role_required('admin', 'karyawan')
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                flash('Silakan login terlebih dahulu.', 'warning')
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('Anda tidak memiliki izin untuk mengakses halaman ini.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ================================================================
# CLI: flask --app app init-db
# ================================================================
@app.cli.command('init-db')
def init_db_command():
    """Reset seluruh database dan isi ulang dengan data contoh."""
    db = get_db()

    # Hapus tabel lama (child dulu agar FK tidak protes)
    db.executescript('''
        PRAGMA foreign_keys = OFF;
        DROP TABLE IF EXISTS audit_log;
        DROP TABLE IF EXISTS rating;
        DROP TABLE IF EXISTS pesan;
        DROP TABLE IF EXISTS tiket;
        DROP TABLE IF EXISTS kategori;
        DROP TABLE IF EXISTS user;
        PRAGMA foreign_keys = ON;
    ''')

    # Buat ulang dari schema.sql
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, encoding='utf-8') as f:
        db.executescript(f.read())

    pw = generate_password_hash('rahasia123')

    # 5 kategori tiket — (kode, nama, deskripsi, kuota)
    kategori_data = [
        ('KAT-001', 'Gangguan Teknis',  'Masalah koneksi, perangkat, atau sistem tidak berjalan', 50),
        ('KAT-002', 'Pertanyaan Umum',  'Pertanyaan seputar layanan, kebijakan, atau prosedur',   100),
        ('KAT-003', 'Permintaan Fitur', 'Usulan penambahan atau perubahan fitur layanan',          30),
        ('KAT-004', 'Keluhan Layanan',  'Ketidakpuasan terhadap kualitas atau respons layanan',    75),
        ('KAT-005', 'Darurat',          'Insiden kritis yang memerlukan penanganan segera',         20),
    ]
    db.executemany(
        'INSERT INTO kategori (kode, nama, deskripsi, kuota) VALUES (?, ?, ?, ?)',
        kategori_data,
    )

    # 1 admin + 2 karyawan + 3 customer
    # kolom: (nomor_identitas, nama, email, password, role, aktif)
    user_data = [
        ('ADM-001', 'Admin Sistem',       'admin@ticketing.id',   pw, 'admin',    1),
        ('KRY-001', 'Budi Santoso',       'budi@ticketing.id',    pw, 'karyawan', 1),
        ('KRY-002', 'Citra Dewi',         'citra@ticketing.id',   pw, 'karyawan', 1),
        ('CST-001', 'Aldi',               'aldi@mhs.id',          pw, 'customer', 1),
        ('CST-002', 'Aldo Pandufirangga', 'aldo@mhs.id',          pw, 'customer', 1),
        ('CST-003', 'Rini Susanti',       'rini@mhs.id',          pw, 'customer', 1),
    ]
    db.executemany(
        '''INSERT INTO user (nomor_identitas, nama, email, password, role, aktif)
           VALUES (?, ?, ?, ?, ?, ?)''',
        user_data,
    )
    db.commit()

    click.echo('[init-db] Tabel berhasil dibuat ulang dari schema.sql.')
    click.echo('[init-db] Data contoh berhasil dimasukkan:')
    click.echo('           • 5 kategori tiket')
    click.echo('           • 1 admin  (ADM-001)')
    click.echo('           • 2 karyawan  (KRY-001, KRY-002)')
    click.echo('           • 3 customer  (CST-001, CST-002, CST-003)')
    click.echo(f'           • Database : {app.config["DATABASE"]}')
    click.echo('           • Password semua akun: rahasia123')


# ================================================================
# Route: Beranda  — redirect ke dashboard jika sudah login
# ================================================================
@app.route('/')
def beranda():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    flash('Selamat datang di Sistem Layanan Pelanggan Ticketing!', 'info')
    return render_template('index.html')


# ================================================================
# Route: Login
# ================================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    # Sudah login → langsung ke dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        nomor_identitas = request.form.get('nomor_identitas', '').strip()
        password        = request.form.get('password', '')

        db   = get_db()
        user = db.execute(
            'SELECT * FROM user WHERE nomor_identitas = ? AND aktif = 1',
            (nomor_identitas,)
        ).fetchone()

        # Cek keberadaan user DAN kecocokan password
        if user is None or not check_password_hash(user['password'], password):
            flash('Nomor identitas atau password salah.', 'danger')
            # Kembalikan form dengan nomor_identitas yang sudah diketik
            return render_template('auth/login.html',
                                   nomor_identitas=nomor_identitas)

        # Login berhasil — simpan ke session
        session.clear()
        session.permanent = True          # aktifkan PERMANENT_SESSION_LIFETIME
        session['user_id']         = user['user_id']
        session['nama']            = user['nama']
        session['role']            = user['role']
        session['nomor_identitas'] = user['nomor_identitas']

        flash(f'Selamat datang, {user["nama"]}!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('auth/login.html')


# ================================================================
# Route: Logout
# ================================================================
@app.route('/logout')
@login_required
def logout():
    nama = session.get('nama', 'Pengguna')
    session.clear()
    flash(f'{nama} berhasil keluar dari sistem.', 'info')
    return redirect(url_for('login'))


# ================================================================
# Route: Dashboard — router utama berdasarkan role
# ================================================================
@app.route('/dashboard')
@login_required
def dashboard():
    role = session.get('role')
    if role == 'admin':
        return redirect(url_for('dashboard_admin'))
    elif role == 'karyawan':
        return redirect(url_for('dashboard_karyawan'))
    else:
        return redirect(url_for('dashboard_customer'))


# ----------------------------------------------------------------
# Dashboard Admin
# ----------------------------------------------------------------
@app.route('/dashboard/admin')
@role_required('admin')
def dashboard_admin():
    db = get_db()

    # Statistik ringkasan
    stats = {
        'total_tiket':  db.execute('SELECT COUNT(*) FROM tiket').fetchone()[0],
        'open':         db.execute("SELECT COUNT(*) FROM tiket WHERE status='Open'").fetchone()[0],
        'assigned':     db.execute("SELECT COUNT(*) FROM tiket WHERE status='Assigned'").fetchone()[0],
        'in_progress':  db.execute("SELECT COUNT(*) FROM tiket WHERE status='In Progress'").fetchone()[0],
        'waiting':      db.execute("SELECT COUNT(*) FROM tiket WHERE status='Waiting'").fetchone()[0],
        'closed':       db.execute("SELECT COUNT(*) FROM tiket WHERE status='Closed'").fetchone()[0],
        'total_user':   db.execute('SELECT COUNT(*) FROM user').fetchone()[0],
        'karyawan':     db.execute("SELECT COUNT(*) FROM user WHERE role='karyawan'").fetchone()[0],
        'customer':     db.execute("SELECT COUNT(*) FROM user WHERE role='customer'").fetchone()[0],
    }

    # 10 tiket terbaru
    tiket_terbaru = db.execute('''
        SELECT t.tiket_id, t.nomor_unik, t.judul, t.prioritas, t.status,
               t.dibuat_pada, uc.nama AS nama_customer, k.nama AS nama_kategori
        FROM   tiket t
        JOIN   user uc     ON t.customer_id  = uc.user_id
        JOIN   kategori k  ON t.kategori_id  = k.kategori_id
        ORDER  BY t.dibuat_pada DESC
        LIMIT  10
    ''').fetchall()

    return render_template('dashboard/admin.html',
                           stats=stats, tiket_terbaru=tiket_terbaru)


# ----------------------------------------------------------------
# Dashboard Karyawan
# ----------------------------------------------------------------
@app.route('/dashboard/karyawan')
@role_required('karyawan')
def dashboard_karyawan():
    db  = get_db()
    uid = session['user_id']

    _ORDER = "ORDER BY CASE t.prioritas WHEN 'Tinggi' THEN 1 WHEN 'Sedang' THEN 2 ELSE 3 END, t.dibuat_pada ASC"

    # 1. Tiket Baru masuk (Open) yang belum diambil siapapun
    tiket_masuk = db.execute(f'''
        SELECT t.tiket_id, t.nomor_unik, t.judul, t.prioritas, t.status,
               t.dibuat_pada, uc.nama AS nama_customer, k.nama AS nama_kategori
        FROM   tiket t
        JOIN   user uc    ON t.customer_id = uc.user_id
        JOIN   kategori k ON t.kategori_id = k.kategori_id
        WHERE  t.status = 'Open' AND t.karyawan_id IS NULL
        {_ORDER}
    ''').fetchall()

    # 2. Tiket yang sedang ditangani oleh karyawan ini (belum Closed)
    tiket_saya = db.execute(f'''
        SELECT t.tiket_id, t.nomor_unik, t.judul, t.prioritas, t.status,
               t.dibuat_pada, uc.nama AS nama_customer, k.nama AS nama_kategori
        FROM   tiket t
        JOIN   user uc    ON t.customer_id = uc.user_id
        JOIN   kategori k ON t.kategori_id = k.kategori_id
        WHERE  t.karyawan_id = ? AND t.status != 'Closed'
        {_ORDER}
    ''', (uid,)).fetchall()

    stats = {
        'open':        len(tiket_masuk),
        'assigned':    db.execute(
            "SELECT COUNT(*) FROM tiket WHERE karyawan_id=? AND status='Assigned'", (uid,)
        ).fetchone()[0],
        'in_progress': db.execute(
            "SELECT COUNT(*) FROM tiket WHERE karyawan_id=? AND status='In Progress'", (uid,)
        ).fetchone()[0],
        'waiting':     db.execute(
            "SELECT COUNT(*) FROM tiket WHERE karyawan_id=? AND status='Waiting'", (uid,)
        ).fetchone()[0],
        'closed':      db.execute(
            "SELECT COUNT(*) FROM tiket WHERE karyawan_id=? AND status='Closed'", (uid,)
        ).fetchone()[0],
    }

    return render_template('dashboard/karyawan.html',
                           tiket_masuk=tiket_masuk, tiket_saya=tiket_saya, stats=stats)


# ----------------------------------------------------------------
# Dashboard Customer
# ----------------------------------------------------------------
@app.route('/dashboard/customer')
@role_required('customer')
def dashboard_customer():
    db  = get_db()
    uid = session['user_id']

    tiket_saya = db.execute('''
        SELECT t.tiket_id, t.nomor_unik, t.judul, t.prioritas, t.status,
               t.dibuat_pada, k.nama AS nama_kategori
        FROM   tiket t
        JOIN   kategori k ON t.kategori_id = k.kategori_id
        WHERE  t.customer_id = ?
        ORDER  BY t.dibuat_pada DESC
    ''', (uid,)).fetchall()

    stats = {
        'total':       len(tiket_saya),
        'open':        sum(1 for t in tiket_saya if t['status'] == 'Open'),
        'in_progress': sum(1 for t in tiket_saya
                          if t['status'] in ('Assigned', 'In Progress', 'Waiting')),
        'closed':      sum(1 for t in tiket_saya if t['status'] == 'Closed'),
    }

    return render_template('dashboard/customer.html',
                           tiket_saya=tiket_saya, stats=stats)


# ================================================================
# Helper validasi form Kategori
# ================================================================
def _validasi_kategori(form, exclude_id=None):
    """
    Validasi input form kategori.
    exclude_id: lewati cek duplikat untuk baris dengan id ini (mode ubah).
    Kembalikan (data_bersih, errors_dict).
    """
    errors = {}
    kode      = form.get('kode', '').strip().upper()
    nama      = form.get('nama', '').strip()
    deskripsi = form.get('deskripsi', '').strip()
    kuota_raw = form.get('kuota', '').strip()

    # --- Validasi kode ---
    if not kode:
        errors['kode'] = 'Kode kategori wajib diisi.'
    elif len(kode) > 20:
        errors['kode'] = 'Kode maksimal 20 karakter.'
    else:
        existing = get_db().execute(
            'SELECT kategori_id FROM kategori WHERE kode = ?', (kode,)
        ).fetchone()
        if existing and existing['kategori_id'] != exclude_id:
            errors['kode'] = f'Kode "{kode}" sudah dipakai kategori lain.'

    # --- Validasi nama ---
    if not nama:
        errors['nama'] = 'Nama kategori wajib diisi.'

    # --- Validasi kuota (harus angka bulat > 0) ---
    kuota = None
    if not kuota_raw:
        errors['kuota'] = 'Kuota wajib diisi.'
    else:
        try:
            kuota = int(kuota_raw)
            if kuota <= 0:
                errors['kuota'] = 'Kuota harus lebih dari 0 (angka positif).'
        except ValueError:
            errors['kuota'] = 'Kuota harus berupa angka bulat.'

    data = {
        'kode':      kode,
        'nama':      nama,
        'deskripsi': deskripsi,
        'kuota':     kuota if kuota is not None else kuota_raw,
    }
    return data, errors


# ================================================================
# CRUD Kategori Tiket  (Admin)
# GET  /admin/kategori              — daftar
# GET  /admin/kategori/tambah       — form tambah
# POST /admin/kategori/tambah       — simpan baru
# GET  /admin/kategori/<id>/ubah    — form edit
# POST /admin/kategori/<id>/ubah    — simpan perubahan
# POST /admin/kategori/<id>/hapus   — hapus
# ================================================================

@app.route('/admin/kategori')
@role_required('admin')
def admin_kategori():
    """Daftar semua kategori tiket + jumlah tiket terkait."""
    rows = get_db().execute('''
        SELECT  k.*,
                COUNT(t.tiket_id) AS jumlah_tiket
        FROM    kategori k
        LEFT JOIN tiket t ON t.kategori_id = k.kategori_id
        GROUP BY k.kategori_id
        ORDER BY k.kode
    ''').fetchall()
    return render_template('admin/kategori/index.html', rows=rows)


@app.route('/admin/kategori/tambah', methods=['GET', 'POST'])
@role_required('admin')
def admin_kategori_tambah():
    """Form tambah kategori baru."""
    errors = {}
    data   = {'kode': '', 'nama': '', 'deskripsi': '', 'kuota': ''}

    if request.method == 'POST':
        data, errors = _validasi_kategori(request.form)
        if not errors:
            get_db().execute(
                'INSERT INTO kategori (kode, nama, deskripsi, kuota) VALUES (?, ?, ?, ?)',
                (data['kode'], data['nama'], data['deskripsi'], data['kuota'])
            )
            get_db().commit()
            flash(f'Kategori "{data["nama"]}" berhasil ditambahkan.', 'success')
            return redirect(url_for('admin_kategori'))

    return render_template('admin/kategori/form.html',
                           judul='Tambah Kategori',
                           data=data, errors=errors,
                           form_action=url_for('admin_kategori_tambah'))


@app.route('/admin/kategori/<int:kategori_id>/ubah', methods=['GET', 'POST'])
@role_required('admin')
def admin_kategori_ubah(kategori_id):
    """Form edit kategori yang sudah ada."""
    db  = get_db()
    row = db.execute(
        'SELECT * FROM kategori WHERE kategori_id = ?', (kategori_id,)
    ).fetchone()
    if row is None:
        flash('Kategori tidak ditemukan.', 'danger')
        return redirect(url_for('admin_kategori'))

    errors = {}
    # Isi awal form dari data database
    data = {
        'kode':      row['kode'],
        'nama':      row['nama'],
        'deskripsi': row['deskripsi'] or '',
        'kuota':     row['kuota'],
    }

    if request.method == 'POST':
        data, errors = _validasi_kategori(request.form, exclude_id=kategori_id)
        if not errors:
            db.execute(
                '''UPDATE kategori
                   SET kode=?, nama=?, deskripsi=?, kuota=?
                   WHERE kategori_id=?''',
                (data['kode'], data['nama'], data['deskripsi'],
                 data['kuota'], kategori_id)
            )
            db.commit()
            flash(f'Kategori "{data["nama"]}" berhasil diperbarui.', 'success')
            return redirect(url_for('admin_kategori'))

    return render_template('admin/kategori/form.html',
                           judul='Ubah Kategori',
                           data=data, errors=errors,
                           form_action=url_for('admin_kategori_ubah',
                                               kategori_id=kategori_id))


@app.route('/admin/kategori/<int:kategori_id>/hapus', methods=['POST'])
@role_required('admin')
def admin_kategori_hapus(kategori_id):
    """Hapus kategori (hanya jika tidak ada tiket terkait)."""
    db  = get_db()
    row = db.execute(
        'SELECT * FROM kategori WHERE kategori_id = ?', (kategori_id,)
    ).fetchone()
    if row is None:
        flash('Kategori tidak ditemukan.', 'danger')
        return redirect(url_for('admin_kategori'))

    # Cek FK — tolak jika masih ada tiket dalam kategori ini
    n_tiket = db.execute(
        'SELECT COUNT(*) FROM tiket WHERE kategori_id = ?', (kategori_id,)
    ).fetchone()[0]
    if n_tiket > 0:
        flash(
            f'Kategori "{row["nama"]}" tidak dapat dihapus karena masih '
            f'memiliki {n_tiket} tiket terkait.', 'danger'
        )
        return redirect(url_for('admin_kategori'))

    db.execute('DELETE FROM kategori WHERE kategori_id = ?', (kategori_id,))
    db.commit()
    flash(f'Kategori "{row["nama"]}" berhasil dihapus.', 'success')
    return redirect(url_for('admin_kategori'))


# ================================================================
# Helper — Nomor tiket & validasi pengajuan
# ================================================================

def generate_nomor_tiket() -> str:
    """Generate nomor tiket unik: TKT-YYYYMMDD-XXXX."""
    db    = get_db()
    today = datetime.now().strftime('%Y%m%d')
    n     = db.execute(
        "SELECT COUNT(*) FROM tiket WHERE nomor_unik LIKE ?",
        (f'TKT-{today}-%',)
    ).fetchone()[0]
    nomor = f'TKT-{today}-{n + 1:04d}'
    # Pastikan benar-benar unik (edge case: tiket dihapus lalu count-nya turun)
    while db.execute(
        'SELECT 1 FROM tiket WHERE nomor_unik = ?', (nomor,)
    ).fetchone():
        n    += 1
        nomor = f'TKT-{today}-{n + 1:04d}'
    return nomor


def _validasi_tiket_baru(form):
    """
    Validasi form pengajuan tiket baru.
    Kembalikan (data_bersih, errors_dict).
    """
    errors   = {}
    db       = get_db()

    judul     = form.get('judul', '').strip()
    deskripsi = form.get('deskripsi', '').strip()
    kat_raw   = form.get('kategori_id', '').strip()
    prioritas = form.get('prioritas', '').strip()

    # --- Judul (BR-01, UC-02: wajib diisi) ---
    if not judul:
        errors['judul'] = 'Judul tiket wajib diisi.'

    # --- Deskripsi (BR-01: wajib diisi) ---
    if not deskripsi:
        errors['deskripsi'] = 'Deskripsi wajib diisi.'

    # --- Kategori & kuota ---
    kategori = None
    if not kat_raw or not kat_raw.isdigit():
        errors['kategori_id'] = 'Pilih kategori yang valid.'
    else:
        kategori = db.execute(
            'SELECT * FROM kategori WHERE kategori_id = ?', (int(kat_raw),)
        ).fetchone()
        if kategori is None:
            errors['kategori_id'] = 'Kategori tidak ditemukan.'
        else:
            terpakai = db.execute(
                'SELECT COUNT(*) FROM tiket WHERE kategori_id = ?',
                (kategori['kategori_id'],)
            ).fetchone()[0]
            if terpakai >= kategori['kuota']:
                errors['kategori_id'] = (
                    f'Kategori "{kategori["nama"]}" telah mencapai kuota penuh '
                    f'({terpakai}/{kategori["kuota"]} tiket).'
                )

    # --- Prioritas ---
    if not prioritas:
        prioritas = 'Rendah'
    if kategori and 'darurat' in kategori['nama'].lower():
        prioritas = 'Tinggi'
    elif prioritas not in ('Tinggi', 'Sedang', 'Rendah'):
        prioritas = 'Rendah'

    data = {
        'judul':       judul,
        'deskripsi':   deskripsi,
        'kategori_id': int(kat_raw) if (kat_raw and kat_raw.isdigit()) else '',
        'prioritas':   prioritas,
    }
    return data, errors


# ================================================================
# Route: Customer — Ajukan tiket baru
# ================================================================
@app.route('/tiket/ajukan', methods=['GET', 'POST'])
@role_required('customer')
def tiket_ajukan():
    db        = get_db()
    kategoris = db.execute('''
        SELECT  k.*,
                COUNT(t.tiket_id) AS terpakai
        FROM    kategori k
        LEFT JOIN tiket t ON t.kategori_id = k.kategori_id
        GROUP BY k.kategori_id
        ORDER BY k.kode
    ''').fetchall()

    errors = {}
    data   = {'judul': '', 'deskripsi': '', 'kategori_id': '', 'prioritas': 'Rendah'}

    if request.method == 'POST':
        data, errors = _validasi_tiket_baru(request.form)
        if not errors:
            nomor = generate_nomor_tiket()
            cur = db.execute('''
                INSERT INTO tiket
                    (nomor_unik, judul, deskripsi, kategori_id,
                     prioritas, status, customer_id)
                VALUES (?, ?, ?, ?, ?, 'Open', ?)
            ''', (nomor, data['judul'], data['deskripsi'],
                  data['kategori_id'], data['prioritas'], session['user_id']))
            tiket_id = cur.lastrowid

            # Masukkan deskripsi masalah sebagai pesan pertama dalam percakapan
            db.execute('''
                INSERT INTO pesan (tiket_id, pengirim_id, isi)
                VALUES (?, ?, ?)
            ''', (tiket_id, session['user_id'], data['deskripsi']))

            # Catat audit log (NFR-02)
            db.execute('''
                INSERT INTO audit_log (tiket_id, aktor_id, status_lama, status_baru, catatan)
                VALUES (?, ?, NULL, 'Open', 'Tiket diajukan oleh customer')
            ''', (tiket_id, session['user_id']))

            db.commit()
            flash(
                f'Tiket {nomor} berhasil diajukan! Customer Service kami akan segera merespons.',
                'success'
            )
            return redirect(url_for('dashboard_customer'))

    return render_template('tiket/ajukan.html',
                           kategoris=kategoris, data=data, errors=errors)


# ================================================================
# Route: Admin — Daftar semua tiket (filterable by status)
# ================================================================
@app.route('/admin/tiket')
@role_required('admin')
def admin_tiket():
    db     = get_db()
    status = request.args.get('status', '')

    _ORDER = "ORDER BY CASE t.prioritas WHEN 'Tinggi' THEN 1 WHEN 'Sedang' THEN 2 ELSE 3 END, t.dibuat_pada ASC"
    _SELECT = '''
        SELECT  t.tiket_id, t.nomor_unik, t.judul,
                t.prioritas, t.status, t.dibuat_pada,
                uc.nama  AS nama_customer,
                k.nama   AS nama_kategori,
                kr.nama  AS nama_karyawan
        FROM    tiket t
        JOIN    user uc      ON t.customer_id = uc.user_id
        JOIN    kategori k   ON t.kategori_id = k.kategori_id
        LEFT JOIN user kr    ON t.karyawan_id = kr.user_id
    '''
    STATUSES = ('Open', 'Assigned', 'In Progress', 'Waiting', 'Closed')

    if status in STATUSES:
        rows = db.execute(
            f'{_SELECT} WHERE t.status = ? {_ORDER}', (status,)
        ).fetchall()
    else:
        status = ''
        rows   = db.execute(f'{_SELECT} {_ORDER}').fetchall()

    # Hitung tiket per status untuk badge tab filter
    counts = {s: db.execute(
        'SELECT COUNT(*) FROM tiket WHERE status = ?', (s,)
    ).fetchone()[0] for s in STATUSES}
    counts['all'] = sum(counts.values())

    return render_template('tiket/daftar_admin.html',
                           rows=rows, status_filter=status, counts=counts,
                           STATUSES=STATUSES)


# ================================================================
# Route: Admin — Pantau detail tiket & percakapan CS - Mahasiswa
# ================================================================
@app.route('/admin/tiket/<int:tiket_id>', methods=['GET', 'POST'])
@role_required('admin')
def admin_detail_tiket(tiket_id):
    db = get_db()

    # Detail tiket lengkap
    tiket = db.execute('''
        SELECT  t.*, uc.nama AS nama_customer, uc.email AS email_customer, uc.nomor_identitas AS nim_customer,
                k.nama AS nama_kategori,
                kr.nama AS nama_karyawan, kr.nomor_identitas AS nip_karyawan
        FROM    tiket t
        JOIN    user uc      ON t.customer_id = uc.user_id
        JOIN    kategori k   ON t.kategori_id = k.kategori_id
        LEFT JOIN user kr    ON t.karyawan_id = kr.user_id
        WHERE   t.tiket_id = ?
    ''', (tiket_id,)).fetchone()

    if tiket is None:
        flash('Tiket tidak ditemukan.', 'danger')
        return redirect(url_for('admin_tiket'))

    # Seluruh percakapan antara CS dan Mahasiswa
    pesans = db.execute('''
        SELECT  p.*, u.nama AS nama_pengirim, u.role AS role_pengirim, u.nomor_identitas
        FROM    pesan p
        JOIN    user u ON p.pengirim_id = u.user_id
        WHERE   p.tiket_id = ?
        ORDER BY p.dikirim_pada ASC
    ''', (tiket_id,)).fetchall()

    # Audit log perubahan status tiket
    logs = db.execute('''
        SELECT  a.*, u.nama AS nama_aktor, u.role AS role_aktor
        FROM    audit_log a
        JOIN    user u ON a.aktor_id = u.user_id
        WHERE   a.tiket_id = ?
        ORDER BY a.dicatat_pada DESC
    ''', (tiket_id,)).fetchall()

    # Daftar CS aktif untuk assign/reassign
    karyawan_list = db.execute('''
        SELECT user_id, nama, nomor_identitas FROM user WHERE role = 'karyawan' AND aktif = 1 ORDER BY nama
    ''').fetchall()

    if request.method == 'POST':
        aksi = request.form.get('aksi', '')
        # Admin kirim pesan supervisi / catatan admin
        if aksi == 'balas':
            isi = request.form.get('isi', '').strip()
            if not isi:
                flash('Pesan tidak boleh kosong.', 'warning')
            else:
                db.execute('''
                    INSERT INTO pesan (tiket_id, pengirim_id, isi)
                    VALUES (?, ?, ?)
                ''', (tiket_id, session['user_id'], f"[Catatan Admin] {isi}"))
                db.commit()
                flash('Pesan supervisi admin berhasil ditambahkan ke percakapan.', 'success')
                return redirect(url_for('admin_detail_tiket', tiket_id=tiket_id))

        # Admin alokasikan tiket ke staf CS
        elif aksi == 'assign':
            karyawan_id = request.form.get('karyawan_id')
            if karyawan_id and karyawan_id.isdigit():
                db.execute('''
                    UPDATE tiket SET karyawan_id = ?, status = 'Assigned', diperbarui = CURRENT_TIMESTAMP
                    WHERE tiket_id = ?
                ''', (int(karyawan_id), tiket_id))
                db.execute('''
                    INSERT INTO audit_log (tiket_id, aktor_id, status_lama, status_baru, catatan)
                    VALUES (?, ?, ?, 'Assigned', ?)
                ''', (tiket_id, session['user_id'], tiket['status'], f"Dialokasikan ke CS oleh Admin {session['nama']}"))
                db.commit()
                flash('Tiket berhasil dialokasikan ke staf Customer Service.', 'success')
                return redirect(url_for('admin_detail_tiket', tiket_id=tiket_id))

        # Admin ubah status tiket
        elif aksi == 'ubah_status':
            status_baru = request.form.get('status_baru')
            VALID = ('Open', 'Assigned', 'In Progress', 'Waiting', 'Closed')
            if status_baru in VALID and status_baru != tiket['status']:
                db.execute('''
                    UPDATE tiket SET status = ?, diperbarui = CURRENT_TIMESTAMP WHERE tiket_id = ?
                ''', (status_baru, tiket_id))
                db.execute('''
                    INSERT INTO audit_log (tiket_id, aktor_id, status_lama, status_baru, catatan)
                    VALUES (?, ?, ?, ?, ?)
                ''', (tiket_id, session['user_id'], tiket['status'], status_baru, f"Status diubah oleh Admin {session['nama']}"))
                db.commit()
                flash(f'Status tiket berhasil diubah menjadi {status_baru}.', 'success')
                return redirect(url_for('admin_detail_tiket', tiket_id=tiket_id))

    return render_template('tiket/detail_admin.html',
                           tiket=tiket, pesans=pesans, logs=logs, karyawan_list=karyawan_list)


# ================================================================
# Route: Karyawan — Antrian tiket (open + tiket saya)
# ================================================================
@app.route('/karyawan/antrian')
@role_required('karyawan')
def karyawan_antrian():
    db  = get_db()
    uid = session['user_id']
    _ORDER = "ORDER BY CASE t.prioritas WHEN 'Tinggi' THEN 1 WHEN 'Sedang' THEN 2 ELSE 3 END, t.dibuat_pada ASC"
    _JOIN  = '''
        JOIN    user uc    ON t.customer_id = uc.user_id
        JOIN    kategori k ON t.kategori_id = k.kategori_id
    '''

    # Tiket Open yang belum di-assign ke siapapun (antrian global)
    antrian_open = db.execute(f'''
        SELECT  t.tiket_id, t.nomor_unik, t.judul,
                t.prioritas, t.status, t.dibuat_pada,
                uc.nama AS nama_customer,
                k.nama  AS nama_kategori
        FROM    tiket t {_JOIN}
        WHERE   t.status = 'Open' AND t.karyawan_id IS NULL
        {_ORDER}
    ''').fetchall()

    # Tiket yang di-assign ke karyawan ini dan belum Closed
    tiket_saya = db.execute(f'''
        SELECT  t.tiket_id, t.nomor_unik, t.judul,
                t.prioritas, t.status, t.dibuat_pada,
                uc.nama AS nama_customer,
                k.nama  AS nama_kategori
        FROM    tiket t {_JOIN}
        WHERE   t.karyawan_id = ? AND t.status != 'Closed'
        {_ORDER}
    ''', (uid,)).fetchall()

    return render_template('tiket/antrian_karyawan.html',
                           antrian_open=antrian_open, tiket_saya=tiket_saya)


# ================================================================
# Route: Karyawan — Ambil tiket dari antrian (self-assign)
# ================================================================
@app.route('/karyawan/ambil/<int:tiket_id>', methods=['POST'])
@role_required('karyawan')
def karyawan_ambil_tiket(tiket_id):
    db  = get_db()
    uid = session['user_id']

    tiket = db.execute(
        'SELECT * FROM tiket WHERE tiket_id = ?', (tiket_id,)
    ).fetchone()

    if tiket is None:
        flash('Tiket tidak ditemukan.', 'danger')
        return redirect(url_for('karyawan_antrian'))

    if tiket['status'] != 'Open' or tiket['karyawan_id'] is not None:
        flash('Tiket ini sudah diambil atau tidak berstatus Open.', 'warning')
        return redirect(url_for('karyawan_antrian'))

    # Assign ke karyawan ini + ubah status → Assigned
    db.execute('''
        UPDATE tiket
        SET    karyawan_id = ?, status = 'Assigned', diperbarui = CURRENT_TIMESTAMP
        WHERE  tiket_id = ?
    ''', (uid, tiket_id))

    # Catat di audit log (NFR-02)
    db.execute('''
        INSERT INTO audit_log (tiket_id, aktor_id, status_lama, status_baru, catatan)
        VALUES (?, ?, 'Open', 'Assigned', ?)
    ''', (tiket_id, uid, f'Diambil oleh {session["nama"]}'))

    db.commit()
    flash(f'Tiket {tiket["nomor_unik"]} berhasil diambil! Silakan tangani.', 'success')
    return redirect(url_for('karyawan_detail_tiket', tiket_id=tiket_id))


# ================================================================
# Route: Karyawan — Detail tiket & balas pesan
# ================================================================
@app.route('/karyawan/tiket/<int:tiket_id>', methods=['GET', 'POST'])
@role_required('karyawan')
def karyawan_detail_tiket(tiket_id):
    db  = get_db()
    uid = session['user_id']

    tiket = db.execute('''
        SELECT  t.*, uc.nama AS nama_customer, k.nama AS nama_kategori
        FROM    tiket t
        JOIN    user uc    ON t.customer_id = uc.user_id
        JOIN    kategori k ON t.kategori_id = k.kategori_id
        WHERE   t.tiket_id = ? AND t.karyawan_id = ?
    ''', (tiket_id, uid)).fetchone()

    if tiket is None:
        flash('Tiket tidak ditemukan atau bukan milik Anda.', 'danger')
        return redirect(url_for('karyawan_antrian'))

    # Ambil semua pesan
    pesans = db.execute('''
        SELECT  p.*, u.nama AS nama_pengirim, u.role AS role_pengirim
        FROM    pesan p
        JOIN    user u ON p.pengirim_id = u.user_id
        WHERE   p.tiket_id = ?
        ORDER BY p.dikirim_pada ASC
    ''', (tiket_id,)).fetchall()

    if request.method == 'POST':
        aksi = request.form.get('aksi', '')

        # --- Kirim balasan ---
        if aksi == 'balas':
            isi = request.form.get('isi', '').strip()
            if not isi:
                flash('Pesan balasan tidak boleh kosong.', 'warning')
            else:
                db.execute('''
                    INSERT INTO pesan (tiket_id, pengirim_id, isi)
                    VALUES (?, ?, ?)
                ''', (tiket_id, uid, isi))

                # Otomatis ubah status → In Progress jika masih Assigned
                if tiket['status'] == 'Assigned':
                    db.execute('''
                        UPDATE tiket SET status = 'In Progress', diperbarui = CURRENT_TIMESTAMP
                        WHERE tiket_id = ?
                    ''', (tiket_id,))
                    db.execute('''
                        INSERT INTO audit_log (tiket_id, aktor_id, status_lama, status_baru, catatan)
                        VALUES (?, ?, 'Assigned', 'In Progress', 'Karyawan mulai merespons')
                    ''', (tiket_id, uid))

                db.commit()
                flash('Balasan berhasil dikirim.', 'success')
                return redirect(url_for('karyawan_detail_tiket', tiket_id=tiket_id))

        # --- Ubah status tiket ---
        elif aksi == 'ubah_status':
            status_baru = request.form.get('status_baru', '')
            VALID = ('In Progress', 'Waiting', 'Closed')
            if status_baru not in VALID:
                flash('Status tidak valid.', 'danger')
            elif status_baru == tiket['status']:
                flash(f'Status sudah {status_baru}.', 'info')
            else:
                db.execute('''
                    UPDATE tiket SET status = ?, diperbarui = CURRENT_TIMESTAMP
                    WHERE tiket_id = ?
                ''', (status_baru, tiket_id))
                db.execute('''
                    INSERT INTO audit_log (tiket_id, aktor_id, status_lama, status_baru, catatan)
                    VALUES (?, ?, ?, ?, ?)
                ''', (tiket_id, uid, tiket['status'], status_baru,
                      f'Status diubah oleh {session["nama"]}'))
                db.commit()
                flash(f'Status tiket diubah menjadi {status_baru}.', 'success')
                return redirect(url_for('karyawan_detail_tiket', tiket_id=tiket_id))

    return render_template('tiket/detail_karyawan.html',
                           tiket=tiket, pesans=pesans)


# ================================================================
# Route: Customer — Detail tiket & kirim pesan
# ================================================================
@app.route('/tiket/<int:tiket_id>', methods=['GET', 'POST'])
@role_required('customer')
def customer_detail_tiket(tiket_id):
    db  = get_db()
    uid = session['user_id']

    tiket = db.execute('''
        SELECT  t.*, k.nama AS nama_kategori,
                kr.nama AS nama_karyawan
        FROM    tiket t
        JOIN    kategori k   ON t.kategori_id = k.kategori_id
        LEFT JOIN user kr    ON t.karyawan_id = kr.user_id
        WHERE   t.tiket_id = ? AND t.customer_id = ?
    ''', (tiket_id, uid)).fetchone()

    if tiket is None:
        flash('Tiket tidak ditemukan.', 'danger')
        return redirect(url_for('dashboard_customer'))

    pesans = db.execute('''
        SELECT  p.*, u.nama AS nama_pengirim, u.role AS role_pengirim
        FROM    pesan p
        JOIN    user u ON p.pengirim_id = u.user_id
        WHERE   p.tiket_id = ?
        ORDER BY p.dikirim_pada ASC
    ''', (tiket_id,)).fetchall()

    if request.method == 'POST':
        isi = request.form.get('isi', '').strip()
        if not isi:
            flash('Pesan tidak boleh kosong.', 'warning')
        elif tiket['status'] == 'Closed':
            flash('Tiket sudah ditutup, tidak bisa mengirim pesan.', 'warning')
        else:
            db.execute('''
                INSERT INTO pesan (tiket_id, pengirim_id, isi)
                VALUES (?, ?, ?)
            ''', (tiket_id, uid, isi))
            db.commit()
            flash('Pesan berhasil dikirim.', 'success')
            return redirect(url_for('customer_detail_tiket', tiket_id=tiket_id))

    return render_template('tiket/detail_customer.html',
                           tiket=tiket, pesans=pesans)


# ================================================================
# Entry point
# ================================================================
if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
