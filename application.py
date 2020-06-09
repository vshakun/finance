import os
import re

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, \
    request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, \
    InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


def format_float(f):
    return "${:,.2f}".format(f)


def get_stocks(user_id):
    rows = db.execute("""
        SELECT
            symbol,
            company,
            SUM(shares) -
            (
                SELECT COALESCE (SUM(shares), 0)
                FROM
                    sales
                WHERE
                    user_id=:user_id
                AND
                    sales.symbol=purchases.symbol
            ) AS shares
        FROM
            purchases
        WHERE
            user_id=:user_id
        GROUP BY
            symbol
        """, user_id=user_id)

    stocks_total = 0

    for row in rows:
        lookup_data = lookup(row["symbol"])
        price_per_share = lookup_data["price"]
        row["price_per_share"] = format_float(price_per_share)
        symbol_total = price_per_share * row["shares"]
        row["symbol_total"] = format_float(symbol_total)
        stocks_total += symbol_total
    return rows, stocks_total


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    user_id = session.get("user_id")
    stocks, stocks_total = get_stocks(user_id)
    rows = db.execute("SELECT cash FROM users WHERE id = :user_id",
                      user_id=user_id)
    user_balance = int(rows[0]["cash"])
    total = stocks_total + user_balance
    return render_template("index.html", stocks=stocks,
                           user_balance=format_float(user_balance), total=format_float(total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "GET":
        return render_template("buy.html")
    symbol = request.form.get("symbol")
    shares = request.form.get("shares")
    if symbol == "" or shares == "":
        return apology("All fields must be filled!", 400)
    try:
        share_count = int(shares)
    except:
        return apology("Must be an integer number!", 400)

    if share_count <= 0:
        return apology("You should enter the positive number of shares!", 400)

    lookup_data = lookup(symbol)

    if lookup_data is None:
        return apology("Not found!", 404)

    user_id = session.get("user_id")
    rows = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id=user_id)
    user_balance = int(rows[0]["cash"])
    purchase_amount = share_count * lookup_data["price"]
    if user_balance < purchase_amount:
        return apology("Not enough cash", 400)

    db.execute("""
        INSERT INTO
            purchases
            (

                user_id,
                symbol,
                company,
                shares,
                price_per_share,
                time
            )
        VALUES
        (

            :user_id,
            :symbol,
            :company,
            :shares,
            :price_per_share,
            CURRENT_TIMESTAMP
        )
        """, user_id=user_id, symbol=symbol, company=lookup_data["name"], shares=share_count,
               price_per_share=lookup_data["price"])
    db.execute("UPDATE users SET cash=cash - :purchase_amount WHERE id=:user_id", purchase_amount=purchase_amount,
               user_id=user_id)
    flash("Bought!")
    return redirect("/")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    user_id = session.get("user_id")
    rows = db.execute("""
        SELECT
            *
        FROM
        (
            SELECT
                symbol,
                shares,
                price_per_share,
                time
            FROM
                purchases
            WHERE
                user_id=:user_id
            UNION
            SELECT
                symbol,
                -shares AS shares,
                price_per_share,
                time
            FROM
                sales
            WHERE
                user_id=:user_id
        )
        ORDER BY
            time
        """, user_id=user_id)
    return render_template("history.html", rows=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "GET":
        return render_template("quote.html")

    symbol = request.form.get("symbol")
    lookup_data = lookup(symbol)

    if lookup_data is None:
        return apology("Not found", 404)

    return render_template("quoted.html", name=lookup_data["name"], symbol=lookup_data["symbol"],
                           price=lookup_data["price"])


@app.route("/register", methods=["GET", "POST"])
def register():
    # Forget any user_id
    session.clear()

    """Register user"""
    if request.method == "GET":
        return render_template("register.html")
    else:
        name = request.form.get("username")
        password = request.form.get("password")
        password_confirmation = request.form.get("password_confirmation")
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=name)

        if name == "" or password == "" or password_confirmation == "":
            return apology("All fields must be filled!")
        elif len(password) < 8:
            return apology("Make sure your password is at lest 8 letters!")
        elif re.search('[0-9]', password) is None:
            return apology("Make sure your password has a number in it")
        elif re.search('[A-Z]', password) is None:
            return apology("Make sure your password has a capital letter in it")
        elif re.search('[!@#$%^&*(){}[]:;\'"/|<>.,~`]', password) is None:
            return apology("Make sure your password has a special symbol in it")
        elif password != password_confirmation:
            return apology("The password and its confirmation do not match!")
        elif len(rows) == 1:
            return apology("The name is already exist!")

        password_hash = generate_password_hash(password)
        db.execute("INSERT INTO users (username, hash) VALUES (:name, :hash)", name=name, hash=password_hash)

        # Remember which user has logged in
        rows = db.execute("SELECT id FROM users WHERE username=:username", username=name)
        session["user_id"] = rows[0]["id"]

        flash("Registered!")
        return redirect("/")


def get_symbols(user_id):
    rows = db.execute("SELECT DISTINCT symbol FROM purchases WHERE user_id=:user_id GROUP BY symbol", user_id=user_id)
    symbols = []
    for row in rows:
        symbols.append(row["symbol"])
    return symbols


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    user_id = session.get("user_id")

    if request.method == "GET":
        symbols = get_symbols(user_id)
        return render_template("sell.html", symbols=symbols)

    user_id = session.get("user_id")
    symbol = request.form.get("symbol")
    lookup_data = lookup(symbol)
    company = lookup_data["name"]
    shares = request.form.get("shares")
    rows = db.execute("""
        SELECT
        (
            SELECT
                COALESCE (SUM(shares), 0)
            FROM
                purchases
            WHERE
                user_id=:user_id
            AND
                symbol=:symbol
        )
        -
        (
            SELECT
                COALESCE (SUM(shares), 0)
            FROM
                sales
            WHERE
                user_id=:user_id
            AND
                symbol=:symbol
        ) AS shares
        """, user_id=user_id, symbol=symbol)
    owned_shares = int(rows[0]["shares"])
    if shares == "":
        return apology("All fields must be filled!", 400)

    try:
        share_count = int(shares)
    except:
        return apology("Must be an integer number!", 400)

    if share_count <= 0:
        return apology("You should enter the positive number of shares!", 400)
    elif share_count > owned_shares:
        return apology("Not enough shares!", 400)

    sold_amount = share_count * lookup_data["price"]

    db.execute("""
        INSERT INTO
            sales
        (
            user_id,
            symbol,
            company,
            shares,
            price_per_share,
            time
        )
        VALUES
        (
            :user_id,
            :symbol,
            :company,
            :shares,
            :price_per_share,
            CURRENT_TIMESTAMP
        )
        """, user_id=user_id, symbol=symbol, company=company, shares=int(shares), price_per_share=lookup_data["price"])
    db.execute("UPDATE users SET cash=cash + :sold_amount WHERE id=:user_id", sold_amount=sold_amount, user_id=user_id)
    flash("Sold!")
    return redirect("/")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
