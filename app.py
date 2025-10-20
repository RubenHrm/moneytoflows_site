\
#!/usr/bin/env python3
# app.py - MoneyToFlows site (Flask)
import os
import sqlite3
from datetime import datetime
from flask import Flask, g, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import secrets

# Config
DATABASE = os.getenv("DATABASE", "db.sqlite3")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@RUBENHRM777")
ACHAT_LINK = os.getenv("ACHAT_LINK", "https://sgzxfbtn.mychariow.shop/prd_8ind83")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Pack Formations Business 2026")
SEUIL_RECOMPENSE = int(os.getenv("SEUIL_RECOMPENSE", "5"))
REWARD_PER_REF = float(os.getenv("REWARD_PER_REF", "1000.0"))
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))

app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET_KEY)

# DB helpers
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    c = db.cursor()
    c.executescript(\"\"\"
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        email TEXT,
        country TEXT,
        mobile TEXT,
        provider TEXT,
        ref_code TEXT UNIQUE,
        referrer_code TEXT,
        purchases INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_code TEXT,
        referred_user_id INTEGER,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        reference TEXT,
        validated INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        provider TEXT,
        mobile_number TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    );
    \"\"\")
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# Utilities
def generate_ref_code(user_id: int):
    return f"{user_id:x}{secrets.token_hex(3)}"

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Accès admin requis", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

# Routes
@app.route("/")
def index():
    return render_template("index.html", product=PRODUCT_NAME, achat_link=ACHAT_LINK)

@app.route("/register", methods=["GET", "POST"])
def register():
    ref = request.args.get("ref")
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        email = request.form.get("email")
        country = request.form.get("country")
        mobile = request.form.get("mobile")
        provider = request.form.get("provider")
        db = get_db()
        try:
            db.execute("INSERT INTO users (username, password, email, country, mobile, provider, referrer_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (username, generate_password_hash(password), email, country, mobile, provider, request.form.get("referrer_code") or None, datetime.utcnow().isoformat()))
            db.commit()
            row = query_db("SELECT id FROM users WHERE username=?", (username,), one=True)
            user_id = row["id"]
            ref_code = generate_ref_code(user_id)
            db.execute("UPDATE users SET ref_code=? WHERE id=?", (ref_code, user_id))
            db.commit()
            r = request.form.get("referrer_code")
            if r:
                db.execute("INSERT INTO referrals (referrer_code, referred_user_id, created_at) VALUES (?, ?, ?)", (r, user_id, datetime.utcnow().isoformat()))
                db.commit()
            flash("Inscription réussie. Connecte-toi.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Nom d'utilisateur déjà utilisé", "danger")
    return render_template("register.html", ref=ref)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        pw = request.form["password"]
        user = query_db("SELECT * FROM users WHERE username=?", (username,), one=True)
        if user and check_password_hash(user["password"], pw):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            is_admin = (str(user["username"]).lower() == ADMIN_USERNAME.lstrip("@").lower())
            session["is_admin"] = is_admin
            flash("Connecté.", "success")
            return redirect(url_for("dashboard"))
        flash("Identifiants incorrects", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    user = query_db("SELECT * FROM users WHERE id=?", (uid,), one=True)
    code = user["ref_code"]
    total_referrals = query_db("SELECT COUNT(*) as c FROM referrals WHERE referrer_code=?", (code,), one=True)["c"]
    buyers_row = query_db(\"\"\"SELECT COUNT(*) as c FROM referrals r
                       JOIN users u ON r.referred_user_id = u.id
                       WHERE r.referrer_code=? AND u.purchases>0\"\"\", (code,), one=True)
    buyers = buyers_row["c"] if buyers_row else 0
    amount = buyers * REWARD_PER_REF
    base_url = request.url_root.rstrip("/")
    ref_link = f"{base_url}/register?ref={code}"
    return render_template("dashboard.html", user=user, total_referrals=total_referrals, buyers=buyers, amount=amount, ref_link=ref_link, threshold=SEUIL_RECOMPENSE)

@app.route("/profile")
@login_required
def profile():
    uid = session["user_id"]
    user = query_db("SELECT * FROM users WHERE id=?", (uid,), one=True)
    return render_template("profile.html", user=user)

@app.route("/referral")
@login_required
def referral():
    uid = session["user_id"]
    user = query_db("SELECT * FROM users WHERE id=?", (uid,), one=True)
    base_url = request.url_root.rstrip("/")
    return render_template("referral.html", code=user["ref_code"], link=f"{base_url}/register?ref={user['ref_code']}")

@app.route("/confirm_purchase", methods=["GET", "POST"])
@login_required
def confirm_purchase():
    if request.method == "POST":
        ref = request.form["reference"].strip()
        uid = session["user_id"]
        db = get_db()
        db.execute("INSERT INTO purchases (user_id, reference, validated, created_at) VALUES (?, ?, 0, ?)", (uid, ref, datetime.utcnow().isoformat()))
        db.commit()
        flash("Référence envoyée à l'admin pour validation.", "info")
        return redirect(url_for("dashboard"))
    return render_template("confirm_purchase.html")

@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    uid = session["user_id"]
    user = query_db("SELECT * FROM users WHERE id=?", (uid,), one=True)
    code = user["ref_code"]
    buyers_row = query_db(\"\"\"SELECT COUNT(*) as c FROM referrals r
                       JOIN users u ON r.referred_user_id = u.id
                       WHERE r.referrer_code=? AND u.purchases>0\"\"\", (code,), one=True)
    buyers = buyers_row["c"] if buyers_row else 0
    if buyers < SEUIL_RECOMPENSE:
        flash(f"Tu as {buyers} filleuls acheteurs. Il en faut {SEUIL_RECOMPENSE} pour retirer.", "warning")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        provider = request.form["provider"]
        mobile = request.form["mobile"].strip()
        db = get_db()
        db.execute("INSERT INTO withdrawals (user_id, provider, mobile_number, status, created_at) VALUES (?, ?, ?, 'pending', ?)", (uid, provider, mobile, datetime.utcnow().isoformat()))
        db.commit()
        flash("Demande de retrait envoyée à l'admin.", "success")
        return redirect(url_for("dashboard"))
    providers = ["MTN MoMo", "Airtel Money", "Orange Money", "Moov Money", "Wave"]
    return render_template("withdraw.html", buyers=buyers, providers=providers)

@app.route("/admin")
@login_required
@admin_required
def admin_index():
    users = query_db("SELECT * FROM users ORDER BY created_at DESC")
    pending = query_db("SELECT p.id, p.user_id, p.reference, p.validated, p.created_at, u.username FROM purchases p JOIN users u ON p.user_id=u.id WHERE p.validated=0")
    withdrawals = query_db("SELECT w.id, w.user_id, w.provider, w.mobile_number, w.status, w.created_at, u.username FROM withdrawals w JOIN users u ON w.user_id=u.id WHERE w.status!='validated'")
    return render_template("admin.html", users=users, pending=pending, withdrawals=withdrawals)

@app.route("/admin/validate_purchase/<int:purchase_id>", methods=["POST"])
@login_required
@admin_required
def validate_purchase(purchase_id):
    db = get_db()
    db.execute("UPDATE purchases SET validated=1 WHERE id=?", (purchase_id,))
    user_id = query_db("SELECT user_id FROM purchases WHERE id=?", (purchase_id,), one=True)["user_id"]
    db.execute("UPDATE users SET purchases = purchases + 1 WHERE id=?", (user_id,))
    db.commit()
    flash("Achat validé.", "success")
    return redirect(url_for("admin_index"))

@app.route("/admin/validate_withdraw/<int:wid>", methods=["POST"])
@login_required
@admin_required
def validate_withdraw(wid):
    db = get_db()
    db.execute("UPDATE withdrawals SET status='validated' WHERE id=?", (wid,))
    db.commit()
    flash("Retrait validé.", "success")
    return redirect(url_for("admin_index"))

@app.route("/admin/refuse_withdraw/<int:wid>", methods=["POST"])
@login_required
@admin_required
def refuse_withdraw(wid):
    db = get_db()
    db.execute("UPDATE withdrawals SET status='refused' WHERE id=?", (wid,))
    db.commit()
    flash("Retrait refusé.", "info")
    return redirect(url_for("admin_index"))

@app.route("/init")
def init():
    init_db()
    return "DB initialized"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
