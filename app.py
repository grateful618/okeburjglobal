import os
import json
import sqlite3
import urllib.parse as urlparse

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

from flask import Flask, render_template, request, redirect, session, Response, url_for
from werkzeug.security import generate_password_hash, check_password_hash

# Try importing psycopg2 for PostgreSQL on Render
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


load_dotenv()

app = Flask(__name__)

@app.template_filter("image_url")
def image_url(image):
    if image and (image.startswith("http://") or image.startswith("https://")):
        return image
    return url_for("static", filename="images/" + str(image or ""))

UPLOAD_FOLDER = "static/images"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret-key")

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET")
)

# Grab DATABASE_URL from Render environment
DATABASE_URL = os.environ.get("DATABASE_URL")


class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, vars=None):
        if isinstance(query, str):
            # Unconditionally translate SQLite '?' placeholders to PostgreSQL '%s'
            query = query.replace('?', '%s')

        if vars is not None:
            if not isinstance(vars, (tuple, list, dict)):
                vars = (vars,)
            return self.cursor.execute(query, vars)
        else:
            return self.cursor.execute(query)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()



class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        orig_execute = cur.execute

        def execute_wrapper(query, vars=None, *args, **kwargs):
            if isinstance(query, str):
                query = query.replace('?', '%s')
            if vars is not None:
                return orig_execute(query, vars, *args, **kwargs)
            return orig_execute(query, *args, **kwargs)

        cur.execute = execute_wrapper
        return cur

    def commit(self):
        return self.conn.commit()

    def close(self):
        return self.conn.close()


def get_db_connection():
    if DATABASE_URL and psycopg2:
        db_url = DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(db_url, sslmode='require')
        return PostgresConnectionWrapper(conn)
    else:
        conn = sqlite3.connect("orders.db")
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    is_postgres = bool(DATABASE_URL and psycopg2)
    param = "%s" if is_postgres else "?"

    # ADMINS TABLE
    if is_postgres:
        c.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
    else:
        c.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

    # Seed default admin if missing using dynamic parameter syntax
    c.execute(f"SELECT id FROM admins WHERE username = {param}", ("admin",))
    if not c.fetchone():
        c.execute(
            f"INSERT INTO admins (username, password) VALUES ({param}, {param})",
            ("admin", generate_password_hash("10423"))
        )

    # ORDERS TABLE
    if is_postgres:
        c.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                name TEXT,
                phone TEXT,
                item TEXT
            )
        ''')
    else:
        c.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                phone TEXT,
                item TEXT
            )
        ''')

    # PRODUCTS TABLE
    if is_postgres:
        c.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT,
                price INTEGER,
                image TEXT,
                sizes TEXT,
                category TEXT
            )
        ''')
    else:
        c.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                price INTEGER,
                image TEXT,
                sizes TEXT,
                category TEXT
            )
        ''')

    conn.commit()
    conn.close()

def import_products():
    if not os.path.exists("products_backup.json"):
        return

    conn = get_db_connection()
    c = conn.cursor()

    with open("products_backup.json", "r", encoding="utf-8") as f:
        products = json.load(f)

    for p in products:
        p_id = p[0]
        c.execute("SELECT COUNT(*) as count FROM products WHERE id = ?", (p_id,))
        row = c.fetchone()
        count = row['count'] if isinstance(row, dict) else row[0]
        
        if count == 0:
            c.execute("""
                INSERT INTO products (id, name, price, image, sizes, category)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (p[0], p[1], p[2], p[3], p[4] if len(p) > 4 else '', p[5] if len(p) > 5 else ''))

    conn.commit()
    conn.close()


# Initialize database once during startup
init_db()
import_products()


@app.route("/")
def home():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id, name, price, image FROM products ORDER BY id DESC")
    all_products = c.fetchall()

    c.execute("SELECT id, name, price, image FROM products ORDER BY id DESC LIMIT 12")
    featured = c.fetchall()

    conn.close()

    return render_template("home.html", products=featured, all_products=all_products)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT password FROM admins WHERE username = ?", (username,))
        admin = c.fetchone()
        conn.close()

        if admin and check_password_hash(admin["password"], password):
            session["admin"] = True
            return redirect("/admin")
        else:
            return "Invalid login credentials", 401

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/login")


@app.route("/menu")
def menu_page():
    query = request.args.get("q")
    category = request.args.get("category")

    conn = get_db_connection()
    c = conn.cursor()

    if query:
        c.execute("SELECT * FROM products WHERE name LIKE ?", ('%' + query + '%',))
    elif category:
        c.execute("SELECT * FROM products WHERE category = ?", (category,))
    else:
        c.execute("SELECT * FROM products")

    products = c.fetchall()
    conn.close()

    return render_template("menu.html", products=products, query=query)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if not session.get("admin"):
        return redirect("/login")

    if request.method == "POST":
        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            return render_template(
                "change_password.html",
                error="New passwords do not match."
            )

        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT password FROM admins WHERE username = ?", ("admin",))
        admin = c.fetchone()

        if not admin or not check_password_hash(admin["password"], current_password):
            conn.close()
            return render_template(
                "change_password.html",
                error="Current password is incorrect."
            )

        new_hash = generate_password_hash(new_password)
        c.execute("UPDATE admins SET password = ? WHERE username = ?", (new_hash, "admin"))

        conn.commit()
        conn.close()

        return render_template(
            "change_password.html",
            message="Password changed successfully!"
        )

    return render_template("change_password.html")


@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, price, image, sizes, category FROM products ORDER BY id DESC")
    products = c.fetchall()
    conn.close()

    return render_template("admin.html", products=products)


@app.route("/delete_product/<int:product_id>")
def delete_product(product_id):
    if not session.get("admin"):
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

    return redirect("/admin")


@app.route("/edit_product/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    if not session.get("admin"):
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()

    if request.method == "POST":
        name = request.form["name"]
        price = request.form["price"]
        image = request.form["image"]

        c.execute("""
            UPDATE products
            SET name = ?, price = ?, image = ?
            WHERE id = ?
        """, (name, price, image, product_id))

        conn.commit()
        conn.close()

        return redirect("/admin")

    c.execute("SELECT id, name, price, image FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    conn.close()

    return render_template("edit_product.html", product=product)


@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if not session.get("admin"):
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form.get('name', 'Unnamed Product').strip()
        
        # Safely convert price string to integer
        raw_price = request.form.get('price', '0')
        try:
            price = int(str(raw_price).replace(',', '').replace('₦', '').strip())
        except (ValueError, TypeError):
            price = 0

        image = request.form.get('image', '').strip()
        sizes = request.form.get('sizes', '').strip()
        category = request.form.get('category', '').strip()

        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO products (name, price, image, sizes, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, price, image, sizes, category)
        )
        conn.commit()
        conn.close()

        return redirect(url_for('admin'))

    return render_template('add_product.html')

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id, name, price, image, sizes FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    conn.close()

    if not product:
        return "Product not found", 404

    return render_template("product.html", product=product)


@app.route("/order", methods=["GET", "POST"])
def order():
    conn = get_db_connection()
    c = conn.cursor()

    if request.method == "POST":
        name = request.form["name"]
        phone = request.form["phone"]
        item = request.form["item"]

        c.execute("""
            INSERT INTO orders (name, phone, item)
            VALUES (?, ?, ?)
        """, (name, phone, item))

        conn.commit()
        conn.close()

        return redirect("/menu")

    c.execute("SELECT name FROM products")
    products = c.fetchall()
    conn.close()

    return render_template("order.html", products=products)


@app.route("/success")
def success():
    return render_template("success.html")


@app.route("/dashboard")
def dashboard():
    if not session.get("admin"):
        return redirect("/login")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT name, phone, item FROM orders")
    orders = c.fetchall()
    conn.close()

    return render_template("dashboard.html", orders=orders)


@app.route("/sync_now")
def sync_now():
    if not session.get("admin"):
        return redirect("/login")

    import_products()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, image FROM products ORDER BY id DESC LIMIT 10")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return {"message": "Database sync executed!", "latest_10_products": rows}
    
with app.app_context():
    try:
        db.create_all()
        
        # Check if products table is empty before running heavy import
        from app import Product, import_products  # adjust model name if different
        
        if Product.query.count() == 0:
            print("Database is empty. Importing products from JSON...")
            import_products()
            print("Import complete!")
        else:
            print("Products already exist. Skipping import.")
            
    except Exception as e:
        print(f"Startup initialization note: {e}")    


@app.route("/sitemap.xml")
def sitemap():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id FROM products")
    product_ids = c.fetchall()
    conn.close()

    base_url = "https://okeburjglobal-1.onrender.com"

    urls = [
        f"{base_url}/",
        f"{base_url}/menu",
        f"{base_url}/about",
        f"{base_url}/contact"
    ]

    for product in product_ids:
        urls.append(f"{base_url}/product/{product['id']}")

    sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>'
    sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'

    for url in urls:
        sitemap_xml += f"<url><loc>{url}</loc></url>"

    sitemap_xml += "</urlset>"

    return Response(sitemap_xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    robots_txt = """User-agent: *
Allow: /

Disallow: /admin
Disallow: /login
Disallow: /logout
Disallow: /dashboard
Disallow: /change_password
Disallow: /add_product
Disallow: /edit_product/
Disallow: /delete_product/
Disallow: /order

Sitemap: https://okeburjglobal-1.onrender.com/sitemap.xml
"""
    return Response(robots_txt, mimetype="text/plain")
    
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"Startup DB Init Warning: {e}")    
    
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)