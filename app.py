"""
SnapLocal Main Web Application & REST API Server.
Commission-based hyperlocal photography & equipment rental marketplace.
Secure Role-Based Access Control: Customer, Service Provider, and Admin.
"""

import os
import uuid
from decimal import Decimal
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify, session,
    redirect, url_for, flash, abort
)
import database
import finance
from gateway import demo_gateway

app = Flask(__name__)
app.secret_key = os.environ.get("SNAPLOCAL_SECRET_KEY", "snaplocal-secure-marketplace-secret-key-2026-v2")

# Ensure database and migrations are initialized
database.init_db(seed=True)


# --- Authentication & Session Utilities ---

def get_current_user():
    """Returns currently authenticated user from session, or None if unauthenticated."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    conn = database.get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def login_user(user):
    """Sets secure session variables for the authenticated user."""
    session.clear()
    session['user_id'] = user['id']
    session['user_role'] = user['role']
    session['user_name'] = user['name']
    session['user_email'] = user['email']


def logout_user():
    """Clears all session variables."""
    session.clear()


def login_required(f):
    """Decorator requiring an authenticated session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth_role_select', next=request.path))
        return f(*args, **kwargs)
    return decorated_function


def role_required(allowed_roles):
    """Decorator requiring a specific user role."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                return redirect(url_for('auth_role_select', next=request.path))
            if user['role'] not in allowed_roles:
                return render_template(
                    'unauthorized.html',
                    message=f"Access Denied: This area requires an authorized {allowed_roles[0].capitalize()} account.",
                    allowed_roles=allowed_roles
                ), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def api_role_required(allowed_roles):
    """Decorator for JSON API endpoints requiring specific roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'error': 'Authentication required. Please log in.'}), 401
            if user['role'] not in allowed_roles:
                return jsonify({'error': f"Forbidden: Requires one of {allowed_roles} role."}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_platform_config():
    """Fetches latest commission and platform configuration."""
    conn = database.get_db()
    row = conn.execute("SELECT * FROM platform_config ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return dict(row)
    return {'commission_rate': '10.00', 'tax_rate': '0.00', 'currency_symbol': '₹'}


@app.context_processor
def inject_global_data():
    """Injects current user, authentication state, and platform config into Jinja templates."""
    current_u = get_current_user()
    return {
        'current_user': current_u,
        'is_authenticated': current_u is not None,
        'platform_config': get_platform_config(),
        'format_currency': finance.format_currency
    }


# --- Authentication & Role Selection Routes ---

@app.route('/login')
@app.route('/auth')
def auth_role_select():
    """
    Entry portal for role selection:
    Asks: "How would you like to continue?"
    Options: Customer, Service Provider, Admin login (restricted).
    """
    next_url = request.args.get('next', '')
    current_u = get_current_user()
    if current_u:
        if current_u['role'] == 'customer':
            return redirect(url_for('customer_dashboard'))
        elif current_u['role'] == 'provider':
            return redirect(url_for('provider_dashboard'))
        elif current_u['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))

    return render_template('auth_role_select.html', next_url=next_url)


@app.route('/auth/login/<role>', methods=['GET', 'POST'])
def role_login(role):
    """
    Dedicated login flow per role.
    Strictly verifies that user role in database matches the login endpoint.
    """
    if role not in ('customer', 'provider', 'admin'):
        abort(404)

    next_url = request.args.get('next', '')

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        conn = database.get_db()
        user = conn.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
        conn.close()

        if not user or not database.verify_password(user['password_hash'], password):
            flash("Invalid email or password. Please verify your credentials.", "error")
            return render_template('auth_login.html', role=role, next_url=next_url)

        # Enforce role matching: A customer cannot login through admin portal, and vice versa!
        if user['role'] != role:
            flash(f"Access Denied: This account is registered as a '{user['role'].capitalize()}', not a '{role.capitalize()}'. Please select the correct portal.", "error")
            return render_template('auth_login.html', role=role, next_url=next_url)

        # Login successful
        login_user(user)

        if next_url and next_url.startswith('/'):
            return redirect(next_url)

        if role == 'customer':
            return redirect(url_for('customer_dashboard'))
        elif role == 'provider':
            return redirect(url_for('provider_dashboard'))
        elif role == 'admin':
            return redirect(url_for('admin_dashboard'))

    return render_template('auth_login.html', role=role, next_url=next_url)


@app.route('/auth/register/<role>', methods=['GET', 'POST'])
def role_register(role):
    """
    Dedicated registration flow for Customer and Service Provider.
    Admin registration is explicitly forbidden through public routes!
    """
    if role == 'admin':
        abort(403, "Administrator accounts cannot be self-registered publicly.")

    if role not in ('customer', 'provider'):
        abort(404)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        phone = request.form.get('phone', '').strip()
        city = request.form.get('city', 'Bengaluru').strip()

        if not name or not email or not password:
            flash("Name, email, and password are required.", "error")
            return render_template('auth_register.html', role=role)

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template('auth_register.html', role=role)

        conn = database.get_db()
        existing = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
        if existing:
            conn.close()
            flash("An account with this email already exists. Please log in instead.", "error")
            return render_template('auth_register.html', role=role)

        # Generate avatar initials
        initials = "".join([part[0].upper() for part in name.split()[:2]]) or "U"
        pw_hash = database.hash_password(password)

        cursor = conn.cursor()
        # Strictly enforce role from URL; never allow form override
        cursor.execute("""
            INSERT INTO users (name, email, password_hash, role, phone, city, avatar_initials)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, email, pw_hash, role, phone, city, initials))
        user_id = cursor.lastrowid

        # If provider, optionally create their initial listing if details provided
        if role == 'provider':
            provider_category = request.form.get('provider_category', 'Weddings & Portraits')
            listing_type = request.form.get('listing_type', 'photographer_with_gear')
            base_rate = request.form.get('base_rate', '2000.00')
            gear_details = request.form.get('gear_details', 'Professional photography gear')
            rental_conditions = request.form.get('rental_conditions', '')

            try:
                rate_dec = finance.to_decimal(base_rate)
            except Exception:
                rate_dec = Decimal('2000.00')

            cursor.execute("""
                INSERT INTO listings (
                    provider_id, listing_type, title, tagline, category, base_rate,
                    rate_unit, gear_details, rental_conditions, location, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'per_session', ?, ?, ?, 'active')
            """, (
                user_id, listing_type, f"{name} - {provider_category} Services",
                f"Verified {provider_category} partner on SnapLocal",
                provider_category, str(rate_dec), gear_details, rental_conditions, city
            ))

        conn.commit()
        new_user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()

        # Automatically log in the newly registered user
        login_user(new_user)
        flash("Welcome to SnapLocal! Your account has been created successfully.", "success")

        if role == 'customer':
            return redirect(url_for('customer_dashboard'))
        else:
            return redirect(url_for('provider_dashboard'))

    return render_template('auth_register.html', role=role)


@app.route('/logout')
def logout():
    """Logs the user out and clears the session."""
    logout_user()
    flash("You have been securely logged out.", "info")
    return redirect(url_for('auth_role_select'))


# --- Public Marketplace & Discovery Routes ---

@app.route('/')
def home():
    """
    Marketplace discovery, search, package builder, and listings.
    Accessible to all users (customers, providers, visitors).
    """
    conn = database.get_db()
    # Optional search / filter params
    category_filter = request.args.get('category')
    type_filter = request.args.get('type')
    max_price = request.args.get('max_price')

    query = """
        SELECT l.*, u.name as provider_name, u.phone as provider_phone
        FROM listings l
        JOIN users u ON l.provider_id = u.id
        WHERE l.status = 'active'
    """
    params = []

    if category_filter:
        query += " AND l.category LIKE ?"
        params.append(f"%{category_filter}%")
    if type_filter:
        query += " AND l.listing_type = ?"
        params.append(type_filter)
    if max_price:
        try:
            max_p = float(max_price)
            query += " AND CAST(l.base_rate AS REAL) <= ?"
            params.append(max_p)
        except ValueError:
            pass

    query += " ORDER BY l.rating DESC"
    listings = [dict(r) for r in conn.execute(query, params).fetchall()]

    photographers_with_gear = [l for l in listings if l['listing_type'] == 'photographer_with_gear']
    photographers_only = [l for l in listings if l['listing_type'] == 'photographer_only']
    gear_rentals = [l for l in listings if l['listing_type'] == 'gear_rental']

    conn.close()
    return render_template(
        'index.html',
        photographers_with_gear=photographers_with_gear,
        photographers_only=photographers_only,
        gear_rentals=gear_rentals,
        all_listings=listings,
        category_filter=category_filter,
        type_filter=type_filter
    )


# --- Customer Dashboard & Protected Customer Actions ---

@app.route('/customer')
@role_required(['customer'])
def customer_dashboard():
    """
    Customer dashboard:
    - View their own bookings and current statuses.
    - Itemized price breakdown without exposing owner commission.
    - Demo checkout for accepted bookings.
    - Demo receipts.
    - Strict privacy: Customer can NEVER see other customers' bookings or provider payouts!
    """
    current_u = get_current_user()
    conn = database.get_db()

    # Fetch ONLY bookings belonging to this customer
    bookings_query = """
        SELECT b.id, b.booking_ref, b.booking_type, b.service_date, b.service_time,
               b.location_address, b.notes, b.photographer_fee, b.gear_fee, b.addons_fee,
               b.taxes_fee, b.total_customer_payment, b.booking_status, b.payment_status,
               b.created_at,
               p_list.title as photographer_title, p_user.name as photographer_name,
               g_list.title as gear_title, g_user.name as gear_provider_name,
               pay.transaction_ref, pay.payment_method, pay.created_at as payment_time
        FROM bookings b
        LEFT JOIN listings p_list ON b.photographer_listing_id = p_list.id
        LEFT JOIN users p_user ON p_list.provider_id = p_user.id
        LEFT JOIN listings g_list ON b.gear_listing_id = g_list.id
        LEFT JOIN users g_user ON g_list.provider_id = g_user.id
        LEFT JOIN payments pay ON b.id = pay.booking_id AND pay.status = 'Paid'
        WHERE b.customer_id = ?
        ORDER BY b.id DESC
    """
    bookings = [dict(r) for r in conn.execute(bookings_query, (current_u['id'],)).fetchall()]

    for b in bookings:
        addons = conn.execute("SELECT addon_key, title, price FROM booking_addons WHERE booking_id = ?", (b['id'],)).fetchall()
        b['addons'] = [dict(a) for a in addons]

    conn.close()
    return render_template('customer.html', bookings=bookings)


# --- Service Provider Dashboard & Actions ---

@app.route('/provider')
@role_required(['provider'])
def provider_dashboard():
    """
    Service Provider Dashboard:
    - Manage own listings and equipment details.
    - Add service descriptions, prices, rental conditions.
    - Set available dates and blocked time slots.
    - View booking requests for their own services.
    - Accept or reject requests.
    - Mark completed shoots.
    - View their own net earnings and payouts.
    - COMMISSION PRIVACY: Owner commission percentage, commission deduction,
      and platform revenue are strictly omitted from the provider interface!
    """
    current_u = get_current_user()
    conn = database.get_db()

    # Fetch provider's own listings
    p_listings = [dict(r) for r in conn.execute("SELECT * FROM listings WHERE provider_id = ? ORDER BY id DESC", (current_u['id'],)).fetchall()]
    listing_ids = [l['id'] for l in p_listings]

    bookings = []
    payout_records = []

    # Provider's own net financials (Zero double-counting; NO platform commission exposed)
    total_service_value = Decimal('0.00')
    net_earnings = Decimal('0.00')
    amount_pending_completion = Decimal('0.00')
    amount_eligible_payout = Decimal('0.00')
    amount_already_paid = Decimal('0.00')

    if listing_ids:
        placeholders = ','.join(['?'] * len(listing_ids))
        # Fetch only bookings for this provider's listings
        b_query = f"""
            SELECT DISTINCT b.id, b.booking_ref, b.booking_type, b.service_date, b.service_time,
                   b.location_address, b.notes, b.booking_status, b.payment_status, b.payout_status,
                   u.name as customer_name, u.phone as customer_phone, u.email as customer_email,
                   p_list.title as photographer_title,
                   g_list.title as gear_title,
                   pay.transaction_ref, pay.payment_method
            FROM bookings b
            JOIN users u ON b.customer_id = u.id
            LEFT JOIN listings p_list ON b.photographer_listing_id = p_list.id
            LEFT JOIN listings g_list ON b.gear_listing_id = g_list.id
            LEFT JOIN payments pay ON b.id = pay.booking_id AND pay.status = 'Paid'
            WHERE b.photographer_listing_id IN ({placeholders})
               OR b.gear_listing_id IN ({placeholders})
            ORDER BY b.id DESC
        """
        bookings = [dict(r) for r in conn.execute(b_query, listing_ids + listing_ids).fetchall()]

        for b in bookings:
            addons = conn.execute("SELECT addon_key, title, price FROM booking_addons WHERE booking_id = ?", (b['id'],)).fetchall()
            b['addons'] = [dict(a) for a in addons]

        # Fetch provider payout records (OMITTING owner commission deductions)
        p_query = """
            SELECT pr.id, pr.booking_id, pr.role_in_booking, pr.gross_amount,
                   pr.net_payable, pr.status, pr.payout_ref, pr.paid_at,
                   b.booking_ref, b.booking_status, b.payment_status, b.service_date,
                   u.name as customer_name
            FROM payout_records pr
            JOIN bookings b ON pr.booking_id = b.id
            JOIN users u ON b.customer_id = u.id
            WHERE pr.provider_id = ?
            ORDER BY pr.id DESC
        """
        payout_records = [dict(r) for r in conn.execute(p_query, (current_u['id'],)).fetchall()]

        for pr in payout_records:
            gross = finance.to_decimal(pr['gross_amount'])
            net = finance.to_decimal(pr['net_payable'])
            status = pr['status']

            total_service_value += gross

            if status in ('Pending', 'Payable', 'Paid'):
                net_earnings += net

            if status == 'Pending':
                amount_pending_completion += net
            elif status == 'Payable':
                amount_eligible_payout += net
            elif status == 'Paid':
                amount_already_paid += net

        # Fetch availability blocked dates
        for l in p_listings:
            blocked = conn.execute("SELECT * FROM listing_availability WHERE listing_id = ? ORDER BY blocked_date", (l['id'],)).fetchall()
            l['blocked_dates'] = [dict(b) for b in blocked]

    conn.close()

    metrics = {
        'total_service_value': str(total_service_value),
        'net_earnings': str(net_earnings),
        'amount_pending_completion': str(amount_pending_completion),
        'amount_eligible_payout': str(amount_eligible_payout),
        'amount_already_paid': str(amount_already_paid)
    }

    return render_template(
        'provider.html',
        listings=p_listings,
        bookings=bookings,
        payout_records=payout_records,
        metrics=metrics
    )


# --- Protected Owner / Administrator Dashboard ---

@app.route('/admin')
@role_required(['admin'])
def admin_dashboard():
    """
    Protected Owner / Admin Dashboard:
    - View and manage customers, service providers, listings, and bookings.
    - View platform-wide financial metrics (GMV vs Platform Commission Revenue).
    - Configure platform commission settings.
    - View payment and refund records.
    - Disburse provider payouts.
    - Moderate provider listings.
    """
    conn = database.get_db()

    # 1. Platform Financial Metrics
    paid_bookings = conn.execute("""
        SELECT total_customer_payment, commission_amount, eligible_booking_amount
        FROM bookings
        WHERE payment_status = 'Paid' AND booking_status != 'Cancelled'
    """).fetchall()

    total_booking_value = sum((finance.to_decimal(b['total_customer_payment']) for b in paid_bookings), finance.DECIMAL_ZERO)
    total_commission_earned = sum((finance.to_decimal(b['commission_amount']) for b in paid_bookings), finance.DECIMAL_ZERO)
    successful_paid_count = len(paid_bookings)
    avg_booking_amount = (total_booking_value / Decimal(successful_paid_count)).quantize(finance.CENT) if successful_paid_count > 0 else finance.DECIMAL_ZERO

    pending_payouts_rows = conn.execute("""
        SELECT net_payable FROM payout_records WHERE status IN ('Pending', 'Payable')
    """).fetchall()
    pending_provider_payouts = sum((finance.to_decimal(p['net_payable']) for p in pending_payouts_rows), finance.DECIMAL_ZERO)

    refund_rows = conn.execute("SELECT amount, commission_adjusted FROM refunds").fetchall()
    cancellation_refunds_total = sum((finance.to_decimal(r['amount']) for r in refund_rows), finance.DECIMAL_ZERO)

    metrics = {
        'total_booking_value': str(total_booking_value),
        'total_commission_earned': str(total_commission_earned),
        'successful_paid_count': successful_paid_count,
        'avg_booking_amount': str(avg_booking_amount),
        'pending_provider_payouts': str(pending_provider_payouts),
        'cancellation_refunds_total': str(cancellation_refunds_total)
    }

    # 2. All Bookings Audit
    all_bookings_query = """
        SELECT b.*,
               c.name as customer_name, c.email as customer_email,
               p_list.title as photographer_title, p_user.name as photographer_name,
               g_list.title as gear_title, g_user.name as gear_provider_name,
               pay.transaction_ref, pay.payment_method
        FROM bookings b
        JOIN users c ON b.customer_id = c.id
        LEFT JOIN listings p_list ON b.photographer_listing_id = p_list.id
        LEFT JOIN users p_user ON p_list.provider_id = p_user.id
        LEFT JOIN listings g_list ON b.gear_listing_id = g_list.id
        LEFT JOIN users g_user ON g_list.provider_id = g_user.id
        LEFT JOIN payments pay ON b.id = pay.booking_id AND pay.status = 'Paid'
        ORDER BY b.id DESC
    """
    bookings = [dict(r) for r in conn.execute(all_bookings_query).fetchall()]

    # 3. Provider Listings Moderation
    listings_query = """
        SELECT l.*, u.name as provider_name, u.email as provider_email, u.phone as provider_phone
        FROM listings l
        JOIN users u ON l.provider_id = u.id
        ORDER BY l.id DESC
    """
    listings = [dict(r) for r in conn.execute(listings_query).fetchall()]

    # 4. User Accounts Directory
    users = [dict(r) for r in conn.execute("SELECT id, name, email, role, phone, city, created_at FROM users ORDER BY role, id ASC").fetchall()]

    # 5. Payout Records
    payouts_query = """
        SELECT pr.*, u.name as provider_name, u.email as provider_email,
               b.booking_ref, b.booking_status, b.payment_status
        FROM payout_records pr
        JOIN users u ON pr.provider_id = u.id
        JOIN bookings b ON pr.booking_id = b.id
        ORDER BY pr.id DESC
    """
    payout_records = [dict(r) for r in conn.execute(payouts_query).fetchall()]

    # 6. Refunds
    refunds_query = """
        SELECT r.*, b.booking_ref, pay.transaction_ref
        FROM refunds r
        JOIN bookings b ON r.booking_id = b.id
        LEFT JOIN payments pay ON r.payment_id = pay.id
        ORDER BY r.id DESC
    """
    refunds = [dict(r) for r in conn.execute(refunds_query).fetchall()]

    # 7. Commission History
    comm_history = [dict(r) for r in conn.execute("""
        SELECT ch.*, u.name as changed_by_name
        FROM commission_history ch
        LEFT JOIN users u ON ch.changed_by = u.id
        ORDER BY ch.id DESC
    """).fetchall()]

    conn.close()

    return render_template(
        'admin.html',
        metrics=metrics,
        bookings=bookings,
        listings=listings,
        users=users,
        payout_records=payout_records,
        refunds=refunds,
        comm_history=comm_history
    )


# --- REST API Endpoints with Security & Ownership Verification ---

@app.route('/api/quote', methods=['POST'])
def get_quote():
    """
    Calculates live transparent price breakdown before booking.
    COMMISSION PRIVACY:
    - Customer receives ONLY customer-facing prices: photographer_fee, gear_fee,
      addons_fee, taxes_fee, total_customer_payment.
    - Owner commission and provider payout fields are strictly kept internal
      and never exposed to customers.
    """
    data = request.get_json() or {}
    p_listing_id = data.get('photographer_listing_id')
    g_listing_id = data.get('gear_listing_id')
    addons = data.get('addons', [])
    booking_type = data.get('booking_type', 'photographer_with_gear')

    conn = database.get_db()
    config = conn.execute("SELECT * FROM platform_config ORDER BY id DESC LIMIT 1").fetchone()
    comm_rate = config['commission_rate'] if config else '10.00'
    tax_rate = config['tax_rate'] if config else '0.00'

    p_fee = Decimal('0.00')
    g_fee = Decimal('0.00')

    if p_listing_id:
        l = conn.execute("SELECT base_rate FROM listings WHERE id = ?", (p_listing_id,)).fetchone()
        if l:
            p_fee = finance.to_decimal(l['base_rate'])

    if g_listing_id:
        l = conn.execute("SELECT base_rate FROM listings WHERE id = ?", (g_listing_id,)).fetchone()
        if l:
            g_fee = finance.to_decimal(l['base_rate'])

    conn.close()

    quote = finance.calculate_booking_quote(
        photographer_rate=p_fee,
        gear_rate=g_fee,
        addons=addons,
        tax_percentage=tax_rate,
        commission_percentage=comm_rate,
        booking_type=booking_type
    )

    # Check caller role: only admin may see owner commission in quotes
    current_u = get_current_user()
    if current_u and current_u['role'] == 'admin':
        return jsonify({'success': True, 'quote': quote})

    # Customer-facing sanitized quote (COMMISSION PRIVACY RULE)
    customer_quote = {
        'booking_type': quote['booking_type'],
        'photographer_fee': quote['photographer_fee'],
        'gear_fee': quote['gear_fee'],
        'addons_fee': quote['addons_fee'],
        'addons': quote['addons'],
        'taxes_fee': quote['taxes_fee'],
        'eligible_booking_amount': quote['eligible_booking_amount'],
        'total_customer_payment': quote['total_customer_payment']
    }
    return jsonify({'success': True, 'quote': customer_quote})


@app.route('/api/bookings/create', methods=['POST'])
@api_role_required(['customer'])
def create_booking():
    """
    Customer submits a booking request.
    Server validations:
    - Verifies customer role.
    - Double-booking prevention: rejects if photographer or gear is already booked for date/time.
    - Validates active status of listings.
    """
    current_u = get_current_user()
    data = request.get_json() or {}

    booking_type = data.get('booking_type', 'photographer_with_gear')
    p_listing_id = data.get('photographer_listing_id')
    g_listing_id = data.get('gear_listing_id')
    service_date = data.get('service_date', datetime.now().strftime('%Y-%m-%d'))
    service_time = data.get('service_time', '10:00 AM')
    location_address = data.get('location_address', '').strip() or 'Bengaluru'
    notes = data.get('notes', '').strip()
    addons = data.get('addons', [])

    conn = database.get_db()

    # 1. Double-booking check: Photographer
    if p_listing_id:
        p_conflict = conn.execute("""
            SELECT id, booking_ref FROM bookings
            WHERE photographer_listing_id = ?
              AND service_date = ?
              AND service_time = ?
              AND booking_status IN ('Pending', 'Accepted')
        """, (p_listing_id, service_date, service_time)).fetchone()
        if p_conflict:
            conn.close()
            return jsonify({
                'error': f"The selected photographer is already booked for {service_date} at {service_time}. Please select an alternate date or time slot."
            }), 409

    # 2. Double-booking check: Equipment rental
    if g_listing_id:
        g_conflict = conn.execute("""
            SELECT id, booking_ref FROM bookings
            WHERE gear_listing_id = ?
              AND service_date = ?
              AND service_time = ?
              AND booking_status IN ('Pending', 'Accepted')
        """, (g_listing_id, service_date, service_time)).fetchone()
        if g_conflict:
            conn.close()
            return jsonify({
                'error': f"The selected camera equipment is already reserved for {service_date} at {service_time}. Please select an alternate date or time slot."
            }), 409

    # 3. Provider manual availability blocked check
    for lid in [p_listing_id, g_listing_id]:
        if lid:
            blocked = conn.execute("""
                SELECT id, reason FROM listing_availability
                WHERE listing_id = ? AND blocked_date = ?
            """, (lid, service_date)).fetchone()
            if blocked:
                conn.close()
                return jsonify({
                    'error': f"The provider has marked {service_date} as unavailable ({blocked['reason'] or 'Reserved'}). Please select an alternate date."
                }), 409

    # 4. Fetch listings rates and verify active
    config = conn.execute("SELECT * FROM platform_config ORDER BY id DESC LIMIT 1").fetchone()
    comm_rate = config['commission_rate'] if config else '10.00'
    tax_rate = config['tax_rate'] if config else '0.00'

    p_fee = Decimal('0.00')
    g_fee = Decimal('0.00')

    if p_listing_id:
        l = conn.execute("SELECT base_rate FROM listings WHERE id = ? AND status = 'active'", (p_listing_id,)).fetchone()
        if not l:
            conn.close()
            return jsonify({'error': 'Selected photographer listing is not active'}), 400
        p_fee = finance.to_decimal(l['base_rate'])

    if g_listing_id:
        l = conn.execute("SELECT base_rate FROM listings WHERE id = ? AND status = 'active'", (g_listing_id,)).fetchone()
        if not l:
            conn.close()
            return jsonify({'error': 'Selected camera gear listing is not active'}), 400
        g_fee = finance.to_decimal(l['base_rate'])

    quote = finance.calculate_booking_quote(
        photographer_rate=p_fee,
        gear_rate=g_fee,
        addons=addons,
        tax_percentage=tax_rate,
        commission_percentage=comm_rate,
        booking_type=booking_type
    )

    booking_ref = f"SNAP-BK-{uuid.uuid4().hex[:6].upper()}"

    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bookings (
            booking_ref, booking_type, customer_id, photographer_listing_id, gear_listing_id,
            service_date, service_time, duration_units, location_address, notes,
            photographer_fee, gear_fee, addons_fee, taxes_fee,
            total_customer_payment, eligible_booking_amount,
            commission_rate_applied, commission_amount, provider_payable_amount,
            booking_status, payment_status, payout_status
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, 1, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            'Pending', 'Not Started', 'Not Eligible'
        )
    """, (
        booking_ref, booking_type, current_u['id'], p_listing_id, g_listing_id,
        service_date, service_time, location_address, notes,
        quote['photographer_fee'], quote['gear_fee'], quote['addons_fee'], quote['taxes_fee'],
        quote['total_customer_payment'], quote['eligible_booking_amount'],
        quote['commission_rate_applied'], quote['commission_amount'], quote['provider_payable_amount']
    ))
    booking_id = cursor.lastrowid

    for add in quote['addons']:
        cursor.execute("""
            INSERT INTO booking_addons (booking_id, addon_key, title, price)
            VALUES (?, ?, ?, ?)
        """, (booking_id, add['key'], add['title'], add['price']))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'booking_id': booking_id,
        'booking_ref': booking_ref,
        'message': f"Booking request {booking_ref} submitted successfully! Awaiting provider confirmation."
    })


@app.route('/api/bookings/<int:booking_id>/accept', methods=['POST'])
@api_role_required(['provider', 'admin'])
def accept_booking(booking_id):
    """
    Provider accepts a booking request.
    Ownership check: Only the provider assigned to the booking (or admin) can accept.
    """
    current_u = get_current_user()
    conn = database.get_db()
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        conn.close()
        return jsonify({'error': 'Booking not found'}), 404

    # Ownership check
    if current_u['role'] != 'admin':
        is_owner = False
        if booking['photographer_listing_id']:
            p = conn.execute("SELECT provider_id FROM listings WHERE id = ?", (booking['photographer_listing_id'],)).fetchone()
            if p and p['provider_id'] == current_u['id']:
                is_owner = True
        if booking['gear_listing_id']:
            g = conn.execute("SELECT provider_id FROM listings WHERE id = ?", (booking['gear_listing_id'],)).fetchone()
            if g and g['provider_id'] == current_u['id']:
                is_owner = True
        if not is_owner:
            conn.close()
            return jsonify({'error': 'Forbidden: You do not own the service listing for this booking.'}), 403

    if booking['booking_status'] != 'Pending':
        conn.close()
        return jsonify({'error': f"Cannot accept booking in {booking['booking_status']} status"}), 400

    conn.execute("UPDATE bookings SET booking_status = 'Accepted', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': f"Booking {booking['booking_ref']} accepted! Customer can now proceed to Demo Checkout."
    })


@app.route('/api/bookings/<int:booking_id>/reject', methods=['POST'])
@api_role_required(['provider', 'admin'])
def reject_booking(booking_id):
    """
    Provider rejects a booking request.
    Ownership check: Only assigned provider (or admin) can reject.
    """
    current_u = get_current_user()
    conn = database.get_db()
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        conn.close()
        return jsonify({'error': 'Booking not found'}), 404

    # Ownership check
    if current_u['role'] != 'admin':
        is_owner = False
        if booking['photographer_listing_id']:
            p = conn.execute("SELECT provider_id FROM listings WHERE id = ?", (booking['photographer_listing_id'],)).fetchone()
            if p and p['provider_id'] == current_u['id']:
                is_owner = True
        if booking['gear_listing_id']:
            g = conn.execute("SELECT provider_id FROM listings WHERE id = ?", (booking['gear_listing_id'],)).fetchone()
            if g and g['provider_id'] == current_u['id']:
                is_owner = True
        if not is_owner:
            conn.close()
            return jsonify({'error': 'Forbidden: You do not own the service listing for this booking.'}), 403

    if booking['booking_status'] != 'Pending':
        conn.close()
        return jsonify({'error': f"Cannot reject booking in {booking['booking_status']} status"}), 400

    conn.execute("UPDATE bookings SET booking_status = 'Rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': f"Booking {booking['booking_ref']} rejected."
    })


@app.route('/api/bookings/<int:booking_id>/checkout', methods=['POST'])
@api_role_required(['customer'])
def checkout_booking(booking_id):
    """
    Customer Demo Checkout with Idempotency Protection.
    Ownership check: Customer can only checkout their own booking.
    """
    current_u = get_current_user()
    data = request.get_json() or {}
    payment_method = data.get('payment_method', 'Demo UPI')
    idempotency_key = data.get('idempotency_key') or f"IDEMP-{booking_id}-{uuid.uuid4().hex[:8]}"

    conn = database.get_db()
    cursor = conn.cursor()

    # Idempotency check
    existing_payment = cursor.execute("SELECT * FROM payments WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    if existing_payment:
        conn.close()
        return jsonify({
            'success': True,
            'is_duplicate': True,
            'transaction_ref': existing_payment['transaction_ref'],
            'message': 'Duplicate request acknowledged: Payment already recorded.'
        })

    booking = cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        conn.close()
        return jsonify({'error': 'Booking not found'}), 404

    # Ownership check: Customer can only pay for their own booking
    if booking['customer_id'] != current_u['id']:
        conn.close()
        return jsonify({'error': 'Forbidden: You can only pay for your own bookings.'}), 403

    if booking['payment_status'] == 'Paid':
        conn.close()
        return jsonify({'error': 'Booking is already paid'}), 400

    if booking['booking_status'] not in ('Accepted', 'Pending'):
        conn.close()
        return jsonify({'error': f"Cannot pay for booking in {booking['booking_status']} status"}), 400

    # Call Demo Payment Gateway
    gw_result = demo_gateway.process_demo_payment(
        booking_id=booking_id,
        amount=booking['total_customer_payment'],
        payment_method=payment_method,
        idempotency_key=idempotency_key
    )

    if not gw_result.get('success'):
        conn.close()
        return jsonify({'error': gw_result.get('error', 'Payment failed')}), 400

    cursor.execute("""
        INSERT INTO payments (
            booking_id, transaction_ref, idempotency_key, amount, payment_method, status, is_demo, gateway_name
        ) VALUES (?, ?, ?, ?, ?, 'Paid', 1, ?)
    """, (
        booking_id,
        gw_result['transaction_ref'],
        idempotency_key,
        booking['total_customer_payment'],
        payment_method,
        gw_result['gateway_name']
    ))
    payment_id = cursor.lastrowid

    cursor.execute("""
        UPDATE bookings
        SET payment_status = 'Paid',
            booking_status = 'Accepted',
            payout_status = 'Pending',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (booking_id,))

    # Snapshot provider payout records (Held in Escrow)
    comm_rate = finance.to_decimal(booking['commission_rate_applied'])

    if booking['photographer_listing_id']:
        p_row = cursor.execute("SELECT provider_id FROM listings WHERE id = ?", (booking['photographer_listing_id'],)).fetchone()
        if p_row:
            p_gross = finance.to_decimal(booking['photographer_fee']) + finance.to_decimal(booking['addons_fee'])
            p_comm = (p_gross * (comm_rate / Decimal('100'))).quantize(finance.CENT)
            p_net = (p_gross - p_comm).quantize(finance.CENT)
            cursor.execute("""
                INSERT INTO payout_records (
                    booking_id, provider_id, role_in_booking, gross_amount,
                    commission_rate, commission_deducted, net_payable, status
                ) VALUES (?, ?, 'photographer', ?, ?, ?, ?, 'Pending')
            """, (booking_id, p_row['provider_id'], str(p_gross), str(comm_rate), str(p_comm), str(p_net)))

    if booking['gear_listing_id']:
        g_row = cursor.execute("SELECT provider_id FROM listings WHERE id = ?", (booking['gear_listing_id'],)).fetchone()
        if g_row:
            g_gross = finance.to_decimal(booking['gear_fee'])
            g_comm = (g_gross * (comm_rate / Decimal('100'))).quantize(finance.CENT)
            g_net = (g_gross - g_comm).quantize(finance.CENT)
            cursor.execute("""
                INSERT INTO payout_records (
                    booking_id, provider_id, role_in_booking, gross_amount,
                    commission_rate, commission_deducted, net_payable, status
                ) VALUES (?, ?, 'gear_provider', ?, ?, ?, ?, 'Pending')
            """, (booking_id, g_row['provider_id'], str(g_gross), str(comm_rate), str(g_comm), str(g_net)))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'transaction_ref': gw_result['transaction_ref'],
        'payment_id': payment_id,
        'amount': booking['total_customer_payment'],
        'message': f"Demo Payment of ₹{booking['total_customer_payment']} successful! Booking confirmed."
    })


@app.route('/api/bookings/<int:booking_id>/complete', methods=['POST'])
@api_role_required(['provider', 'admin'])
def complete_booking(booking_id):
    """
    Provider marks service completed.
    Transitions:
    - booking_status: 'Completed'
    - payout_status: 'Payable' (ready for payout disbursement)
    Ownership check: Provider must own the listing.
    """
    current_u = get_current_user()
    conn = database.get_db()
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        conn.close()
        return jsonify({'error': 'Booking not found'}), 404

    # Ownership check
    if current_u['role'] != 'admin':
        is_owner = False
        if booking['photographer_listing_id']:
            p = conn.execute("SELECT provider_id FROM listings WHERE id = ?", (booking['photographer_listing_id'],)).fetchone()
            if p and p['provider_id'] == current_u['id']:
                is_owner = True
        if booking['gear_listing_id']:
            g = conn.execute("SELECT provider_id FROM listings WHERE id = ?", (booking['gear_listing_id'],)).fetchone()
            if g and g['provider_id'] == current_u['id']:
                is_owner = True
        if not is_owner:
            conn.close()
            return jsonify({'error': 'Forbidden: You do not own the service listing for this booking.'}), 403

    if booking['payment_status'] != 'Paid':
        conn.close()
        return jsonify({'error': 'Cannot complete a booking that has not been paid'}), 400

    conn.execute("""
        UPDATE bookings
        SET booking_status = 'Completed',
            payout_status = 'Payable',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (booking_id,))

    conn.execute("""
        UPDATE payout_records
        SET status = 'Payable'
        WHERE booking_id = ? AND status = 'Pending'
    """, (booking_id,))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': f"Booking {booking['booking_ref']} marked as Completed! Provider earnings are now eligible for payout."
    })


@app.route('/api/bookings/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    """
    Cancels a booking.
    Ownership check: Customer can cancel their own booking, or admin can cancel.
    If already paid, processes a simulated refund and reverses provider payouts.
    """
    current_u = get_current_user()
    data = request.get_json() or {}
    reason = data.get('reason', 'Customer requested cancellation')

    conn = database.get_db()
    cursor = conn.cursor()

    booking = cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        conn.close()
        return jsonify({'error': 'Booking not found'}), 404

    # Ownership check
    if current_u['role'] != 'admin' and booking['customer_id'] != current_u['id']:
        conn.close()
        return jsonify({'error': 'Forbidden: You cannot cancel another customer\'s booking.'}), 403

    if booking['booking_status'] in ('Completed', 'Cancelled'):
        conn.close()
        return jsonify({'error': f"Cannot cancel booking with status {booking['booking_status']}"}), 400

    if booking['payment_status'] == 'Paid':
        payment = cursor.execute("SELECT * FROM payments WHERE booking_id = ? AND status = 'Paid'", (booking_id,)).fetchone()
        refund_res = demo_gateway.process_refund(
            booking_id=booking_id,
            payment_id=payment['id'] if payment else 0,
            amount=booking['total_customer_payment'],
            reason=reason
        )

        cursor.execute("""
            INSERT INTO refunds (
                booking_id, payment_id, refund_ref, amount, commission_adjusted, reason, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'Processed')
        """, (
            booking_id,
            payment['id'] if payment else None,
            refund_res['refund_ref'],
            booking['total_customer_payment'],
            booking['commission_amount'],
            reason
        ))

        if payment:
            cursor.execute("UPDATE payments SET status = 'Refunded' WHERE id = ?", (payment['id'],))

        cursor.execute("UPDATE payout_records SET status = 'Reversed' WHERE booking_id = ?", (booking_id,))
        cursor.execute("""
            UPDATE bookings
            SET booking_status = 'Cancelled',
                payment_status = 'Refunded',
                payout_status = 'Reversed',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (booking_id,))
    else:
        cursor.execute("""
            UPDATE bookings
            SET booking_status = 'Cancelled',
                payout_status = 'Not Eligible',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (booking_id,))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': f"Booking {booking['booking_ref']} cancelled and refund processed (if paid)."
    })


# --- Provider Listings & Availability Management APIs ---

@app.route('/api/provider/listings/create', methods=['POST'])
@api_role_required(['provider'])
def provider_create_listing():
    """
    Provider creates a new service or camera gear rental listing.
    Supports title, category, type, price, gear details, and rental conditions.
    """
    current_u = get_current_user()
    data = request.get_json() or {}

    title = data.get('title', '').strip()
    category = data.get('category', 'Weddings & Portraits').strip()
    listing_type = data.get('listing_type', 'photographer_with_gear')
    base_rate = data.get('base_rate', '2000.00')
    rate_unit = data.get('rate_unit', 'per_session')
    gear_details = data.get('gear_details', '').strip()
    rental_conditions = data.get('rental_conditions', '').strip()
    location = data.get('location', current_u.get('city', 'Bengaluru')).strip()
    tagline = data.get('tagline', '').strip()

    if not title:
        return jsonify({'error': 'Listing title is required'}), 400

    try:
        dec_rate = finance.to_decimal(base_rate)
        if dec_rate <= finance.DECIMAL_ZERO:
            return jsonify({'error': 'Rate must be greater than zero'}), 400
    except Exception:
        return jsonify({'error': 'Invalid base rate'}), 400

    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO listings (
            provider_id, listing_type, title, tagline, category, base_rate,
            rate_unit, gear_details, rental_conditions, location, status,
            image_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', '/static/images/hero.jpg')
    """, (
        current_u['id'], listing_type, title, tagline, category, str(dec_rate),
        rate_unit, gear_details, rental_conditions, location
    ))
    listing_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'listing_id': listing_id,
        'message': f"Listing '{title}' created successfully!"
    })


@app.route('/api/provider/listings/<int:listing_id>/availability', methods=['POST'])
@api_role_required(['provider'])
def set_listing_availability(listing_id):
    """
    Provider manages unavailable/blocked dates and time slots for their listing.
    Ownership check: Provider must own the listing.
    """
    current_u = get_current_user()
    data = request.get_json() or {}
    blocked_date = data.get('blocked_date')
    blocked_time = data.get('blocked_time', 'All Day')
    reason = data.get('reason', 'Provider Busy')
    action = data.get('action', 'block') # 'block' or 'unblock'

    if not blocked_date:
        return jsonify({'error': 'Date is required'}), 400

    conn = database.get_db()
    cursor = conn.cursor()

    # Ownership check
    listing = cursor.execute("SELECT provider_id FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not listing or listing['provider_id'] != current_u['id']:
        conn.close()
        return jsonify({'error': 'Forbidden: You do not own this listing'}), 403

    if action == 'unblock':
        cursor.execute("DELETE FROM listing_availability WHERE listing_id = ? AND blocked_date = ?", (listing_id, blocked_date))
        msg = f"Date {blocked_date} is now available for bookings."
    else:
        cursor.execute("""
            INSERT INTO listing_availability (listing_id, blocked_date, blocked_time, reason)
            VALUES (?, ?, ?, ?)
        """, (listing_id, blocked_date, blocked_time, reason))
        msg = f"Date {blocked_date} marked as unavailable."

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': msg})


# --- Admin Management APIs ---

@app.route('/api/payouts/<int:payout_id>/disburse', methods=['POST'])
@api_role_required(['admin'])
def disburse_payout(payout_id):
    """Admin disburses eligible payout to provider. Transitions payout status to 'Paid'."""
    conn = database.get_db()
    cursor = conn.cursor()
    payout = cursor.execute("SELECT * FROM payout_records WHERE id = ?", (payout_id,)).fetchone()
    if not payout:
        conn.close()
        return jsonify({'error': 'Payout record not found'}), 404

    if payout['status'] != 'Payable':
        conn.close()
        return jsonify({'error': f"Payout cannot be disbursed while in '{payout['status']}' status. Booking must be Completed first."}), 400

    payout_ref = f"PO-DEMO-{uuid.uuid4().hex[:6].upper()}"
    cursor.execute("""
        UPDATE payout_records
        SET status = 'Paid',
            payout_ref = ?,
            paid_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (payout_ref, payout_id))

    booking_id = payout['booking_id']
    unpaid = cursor.execute("SELECT COUNT(*) FROM payout_records WHERE booking_id = ? AND status != 'Paid'", (booking_id,)).fetchone()[0]
    if unpaid == 0:
        cursor.execute("UPDATE bookings SET payout_status = 'Paid', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (booking_id,))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'payout_ref': payout_ref,
        'message': f"Payout of ₹{payout['net_payable']} disbursed successfully to provider (Ref: {payout_ref})."
    })


@app.route('/api/admin/commission', methods=['POST'])
@api_role_required(['admin'])
def update_commission():
    """
    Admin updates default platform commission percentage.
    Changes apply strictly to future bookings; historical snapshot rates remain unaffected!
    """
    current_u = get_current_user()
    data = request.get_json() or {}
    new_rate_str = data.get('commission_rate')
    reason = data.get('reason', 'Admin updated platform fee')

    try:
        new_rate = finance.to_decimal(new_rate_str)
        if new_rate < Decimal('0.00') or new_rate > Decimal('50.00'):
            return jsonify({'error': 'Commission rate must be between 0.00% and 50.00%'}), 400
    except Exception:
        return jsonify({'error': 'Invalid commission rate'}), 400

    conn = database.get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO platform_config (commission_rate, tax_rate, updated_by, notes)
        VALUES (?, '0.00', ?, ?)
    """, (str(new_rate), current_u['id'], reason))

    cursor.execute("""
        INSERT INTO commission_history (rate_percentage, changed_by, reason)
        VALUES (?, ?, ?)
    """, (str(new_rate), current_u['id'], reason))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'commission_rate': str(new_rate),
        'message': f"Platform default commission updated to {new_rate}%. Future bookings will use this rate; all historical bookings retain their original snapshotted rate."
    })


@app.route('/api/admin/listing/<int:listing_id>/toggle', methods=['POST'])
@api_role_required(['admin'])
def toggle_listing(listing_id):
    """Admin toggles active/deactivated state on provider listings."""
    conn = database.get_db()
    cursor = conn.cursor()
    listing = cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not listing:
        conn.close()
        return jsonify({'error': 'Listing not found'}), 404

    new_status = 'deactivated' if listing['status'] == 'active' else 'active'
    cursor.execute("UPDATE listings SET status = ? WHERE id = ?", (new_status, listing_id))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'status': new_status,
        'message': f"Listing '{listing['title']}' is now {new_status.upper()}."
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"SnapLocal Server running on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
