-- ============================================================
-- schema.sql — Sistem Layanan Pelanggan Ticketing
-- Database: SQLite 3  |  PRAGMA foreign_keys = ON wajib aktif
-- Entitas: User (superclass), Ticket, Message, Rating, AuditLog
-- Kategori disimpan di tabel master agar bisa dikelola Admin
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- 1. TABEL USER  (superclass; role membedakan Customer /
--                 Karyawan / Admin sesuai domain model Bab 6)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user (
    user_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nomor_identitas   TEXT    NOT NULL UNIQUE,  -- ADM-001, KRY-001, CST-001, dll.
    nama              TEXT    NOT NULL,
    email             TEXT    NOT NULL UNIQUE,
    password          TEXT    NOT NULL,          -- pbkdf2 hash (Werkzeug)
    role              TEXT    NOT NULL           -- 'admin' | 'karyawan' | 'customer'
                      CHECK (role IN ('admin', 'karyawan', 'customer')),
    aktif             INTEGER NOT NULL DEFAULT 1 -- 1=aktif, 0=nonaktif (BR-03)
                      CHECK (aktif IN (0, 1)),
    dibuat_pada       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- 2. TABEL KATEGORI  (master data; dikelola Admin)
--    kode  : kode unik singkat, mis. KAT-001  (BR-01 analog)
--    kuota : batas maks tiket dalam kategori ini, harus > 0
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kategori (
    kategori_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kode        TEXT    NOT NULL UNIQUE,
    nama        TEXT    NOT NULL UNIQUE,
    deskripsi   TEXT,
    kuota       INTEGER NOT NULL DEFAULT 50
                CHECK (kuota > 0),
    dibuat_pada DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- 3. TABEL TIKET
--    - customer_id  : FK ke user (role='customer')
--    - karyawan_id  : FK ke user (role='karyawan'), NULL saat Open
--    - admin_id     : FK ke user (role='admin') yang men-assign
--    Status life-cycle: Open → Assigned → In Progress → Waiting → Closed  (BR-02)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tiket (
    tiket_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    nomor_unik  TEXT    NOT NULL UNIQUE,   -- format TKT-YYYYMMDD-XXXX
    judul       TEXT    NOT NULL,          -- wajib (BR-01, UC-02)
    deskripsi   TEXT    NOT NULL,          -- wajib (BR-01)
    kategori_id INTEGER NOT NULL
                REFERENCES kategori(kategori_id),
    prioritas   TEXT    NOT NULL DEFAULT 'Rendah'
                CHECK (prioritas IN ('Tinggi', 'Sedang', 'Rendah')),
    status      TEXT    NOT NULL DEFAULT 'Open'
                CHECK (status IN ('Open', 'Assigned', 'In Progress', 'Waiting', 'Closed')),
    customer_id INTEGER NOT NULL
                REFERENCES user(user_id),
    karyawan_id INTEGER
                REFERENCES user(user_id),  -- NULL sampai di-assign
    admin_id    INTEGER
                REFERENCES user(user_id),  -- NULL sampai di-assign
    dibuat_pada DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    diperbarui  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- 4. TABEL PESAN  (komposisi 1–0..* ke tiket; BR-05)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pesan (
    pesan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    tiket_id    INTEGER NOT NULL
                REFERENCES tiket(tiket_id) ON DELETE CASCADE,
    pengirim_id INTEGER NOT NULL
                REFERENCES user(user_id),
    isi         TEXT    NOT NULL,
    dikirim_pada DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- 5. TABEL RATING  (asosiasi 1–0..1 ke tiket; BR-04)
--    Hanya Customer pemilik, hanya bila status Closed
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rating (
    rating_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tiket_id       INTEGER NOT NULL UNIQUE   -- maks 1 rating per tiket
                   REFERENCES tiket(tiket_id) ON DELETE CASCADE,
    customer_id    INTEGER NOT NULL
                   REFERENCES user(user_id),
    skor_bintang   INTEGER NOT NULL
                   CHECK (skor_bintang BETWEEN 1 AND 5),
    ulasan         TEXT,
    dinilai_pada   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- 6. TABEL AUDIT LOG  (NFR-02: rekam setiap perubahan status)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    tiket_id     INTEGER NOT NULL
                 REFERENCES tiket(tiket_id) ON DELETE CASCADE,
    aktor_id     INTEGER NOT NULL
                 REFERENCES user(user_id),
    status_lama  TEXT,
    status_baru  TEXT    NOT NULL,
    catatan      TEXT,
    dicatat_pada DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- INDEX untuk query umum
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_tiket_status      ON tiket(status);
CREATE INDEX IF NOT EXISTS idx_tiket_customer    ON tiket(customer_id);
CREATE INDEX IF NOT EXISTS idx_tiket_karyawan    ON tiket(karyawan_id);
CREATE INDEX IF NOT EXISTS idx_pesan_tiket       ON pesan(tiket_id);
CREATE INDEX IF NOT EXISTS idx_audit_tiket       ON audit_log(tiket_id);

