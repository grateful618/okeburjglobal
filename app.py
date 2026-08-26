import sqlite3
import os

import cloudinary
import cloudinary.uploader

from dotenv import load_dotenv

from flask import Flask, render_template, request, redirect, session,Response,url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)

@app.template_filter("image_url")
def image_url(image):
    if image.startswith("http://") or image.startswith("https://"):
        return image
    return url_for("static", filename="images/" + image)

UPLOAD_FOLDER = "static/images"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

app.secret_key = os.environ["SECRET_KEY"]

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET")
)


def init_db():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()

    # ORDERS TABLE
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            item TEXT
        )
    ''')

    # PRODUCTS TABLE
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price INTEGER,
            image TEXT
        )
    ''')
    
    
    try:
        c.execute("ALTER TABLE products ADD COLUMN sizes TEXT")
    except:
        pass
        
        
    try:
        c.execute("ALTER TABLE products ADD COLUMN category TEXT")
    except:
        pass    
        
        


    # ADMINS TABLE
    c.execute("""
       CREATE TABLE IF NOT EXISTS admins (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           username TEXT UNIQUE NOT NULL,
           password TEXT NOT NULL
    )
""")

    # Create the first admin if none exists
    c.execute("SELECT COUNT(*) FROM admins")
    count = c.fetchone()[0]

    if count == 0:
        admin_hash = generate_password_hash("1234")
        c.execute(
            "INSERT INTO admins (username, password) VALUES (?, ?)",
            ("admin", admin_hash)
        )

    conn.commit()
    conn.close()

init_db()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = sqlite3.connect("orders.db")
        c = conn.cursor()

        c.execute(
            "SELECT password FROM admins WHERE username = ?",
            (username,)
        )
        admin = c.fetchone()

        conn.close()

        if admin and check_password_hash(admin[0], password):
            session["admin"] = True
            return redirect("/admin")
            
        else:
            return "lnvalid login"
           
            
    return render_template("login.html")
            
     
# menu data
@app.route("/menu")
def menu_page():
    query = request.args.get("q")
    category = request.args.get("category")

    conn = sqlite3.connect('orders.db')
    c = conn.cursor()

    if query:
        c.execute(
        "SELECT * FROM products WHERE name LIKE ?",
        ('%' + query + '%',)
    )
    
    elif category:
    
        c.execute(
        "SELECT * FROM products WHERE category = ?",
        (category,)
    )
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

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/login")

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

        conn = sqlite3.connect("orders.db")
        c = conn.cursor()

        c.execute(
            "SELECT password FROM admins WHERE username = ?",
            ("admin",)
        )

        admin = c.fetchone()

        if not admin or not check_password_hash(admin[0], current_password):
            conn.close()
            return render_template(
                "change_password.html",
                error="Current password is incorrect."
            )

        new_hash = generate_password_hash(new_password)

        c.execute(
            "UPDATE admins SET password = ? WHERE username = ?",
            (new_hash, "admin")
        )

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

    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("SELECT id, name, price, image FROM products")
    products = c.fetchall()
    conn.close()

    return render_template("admin.html", products=products)

@app.route("/delete_product/<int:product_id>")
def delete_product(product_id):
    if not session.get("admin"):
        return redirect("/login")
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

    return redirect("/admin")
    
@app.route("/edit_product/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    if not session.get("admin"):
        return redirect("/login")
    conn = sqlite3.connect('orders.db')
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

@app.route("/add_product", methods=["GET", "POST"])
def add_product():
    if not session.get("admin"):
        return redirect("/login")
    if request.method == "POST":
        name = request.form["name"]
        price = request.form["price"]
        category = request.form["category"]
        image = request.files["image"]
        sizes = request.form.get('sizes', '')   # ✅ safe
        
        upload_result = cloudinary.uploader.upload(
            image,
            folder="okeburjglobal/products"
        )

        image_url = upload_result["secure_url"]
        
        
        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        
        c.execute(
            """
            INSERT INTO products (name, price, image, sizes, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, price, image_url, sizes, category)
        )
                  
        conn.commit()
        conn.close()

        return redirect("/admin")

    return render_template("add_product.html")

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()

    c.execute("SELECT id, name, price, image, sizes FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()

    conn.close()

    if not product:
        return "Product not found", 404

    return render_template("product.html", product=product)
@app.route("/sitemap.xml")
def sitemap():
    conn = sqlite3.connect("orders.db")
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
        urls.append(f"{base_url}/product/{product[0]}")

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



@app.route("/")
def home():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()

    # ALL products for carousel
    c.execute("SELECT id, name, price, image FROM products ORDER BY id DESC")
    all_products = c.fetchall()

    # FEATURED (only 6)
    c.execute("SELECT id, name, price, image FROM products ORDER BY id DESC LIMIT 12")
    featured = c.fetchall()

    conn.close()

    return render_template("home.html", products=featured, all_products=all_products)


@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        name = request.form["name"]
        phone = request.form["phone"]
        item = request.form["item"]

        # find product details
        product = next((p for p in menu if p["name"] == item), None)

        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        c.execute("""
            INSERT INTO orders (name, phone, item)
            VALUES (?, ?, ?)
        """, (name, phone, item))

        conn.commit()
        conn.close()

        return redirect("/menu")

    return render_template("order.html", menu=menu)
@app.route("/success")
def success():
    return render_template("success.html")

@app.route("/dashboard")
def dashboard():
    if not session.get("admin"):
        return redirect("/login")

    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("SELECT name, phone, item FROM orders")
    orders = c.fetchall()
    conn.close()

    return render_template("dashboard.html", orders=orders)

def import_products():
    print("=== PRODUCT IMPORT STARTING ===")

    if not os.path.exists("products_backup.json"):
        print("ERROR: products_backup.json NOT FOUND")
        return

    print("products_backup.json FOUND")

    conn = sqlite3.connect("orders.db")
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM products")
    count = c.fetchone()[0]

    print(f"Current products in database: {count}")

    if count == 0:
        import json

        with open("products_backup.json", "r", encoding="utf-8") as f:
            products = json.load(f)

        print(f"Backup contains {len(products)} products")

        for product in products:
            c.execute("""
                INSERT INTO products
                (id, name, price, image, sizes, category)
                VALUES (?, ?, ?, ?, ?, ?)
            """, product)

        conn.commit()

        c.execute("SELECT COUNT(*) FROM products")
        new_count = c.fetchone()[0]

        print(f"SUCCESS: Database now contains {new_count} products")

    else:
        print(f"IMPORT SKIPPED: Database already contains {count} products")

    conn.close()

    print("=== PRODUCT IMPORT FINISHED ===")


import_products()

@app.route("/reset_admin")
def reset_admin():
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    new_hash = generate_password_hash("10423")
    
    c.execute("SELECT id FROM admins WHERE username = 'admin'")
    row = c.fetchone()
    
    if row:
        c.execute("UPDATE admins SET password = ? WHERE username = 'admin'", (new_hash,))
        message = "Admin password updated for existing user."
    else:
        c.execute("INSERT INTO admins (username, password) VALUES ('admin', ?)", (new_hash,))
        message = "Admin user created."
        
    conn.commit()
    conn.close()
    return f"Success! {message} Password set to: 10423"

if __name__ == "__main__":
    app.run(debug=True)
