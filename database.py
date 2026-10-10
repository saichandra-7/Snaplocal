"""
SnapLocal Database Architecture & Migration Engine.
SQLite database with strict Decimal representation (TEXT/VARCHAR) to prevent float issues.
Complete with schema initialization, index creation, and rich seed data.
"""

import sqlite3
import os
from decimal import Decimal
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import finance

DB_FILE = os.path.join(os.path.dirname(__file__), "snaplocal.db")


def hash_password(password: str) -> str:
    """Hash password using Werkzeug standard hashing."""
    return generate_password_hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Safely check password against hash, supporting migration from plaintext."""
    if not stored_hash or not password:
        return False
    if stored_hash.startswith(('scrypt:', 'pbkdf2:')):
        return check_password_hash(stored_hash, password)
    # Fallback for unmigrated legacy plaintext seed
    return stored_hash == password


def get_db():
    """Returns a sqlite3 connection with Row factory enabled."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(seed=True):
    """Initializes tables, indices, and baseline configuration."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
    -- 1. Users Table (Roles: customer, provider, admin)
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('customer', 'provider', 'admin')),
        phone TEXT,
        city TEXT DEFAULT 'Bengaluru',
        avatar_initials TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 2. Platform Commission Configuration Table
    CREATE TABLE IF NOT EXISTS platform_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commission_rate TEXT NOT NULL DEFAULT '10.00',
        tax_rate TEXT NOT NULL DEFAULT '0.00',
        currency_symbol TEXT DEFAULT '₹',
        updated_by INTEGER REFERENCES users(id),
        notes TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 3. Commission Configuration Audit History
    CREATE TABLE IF NOT EXISTS commission_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rate_percentage TEXT NOT NULL,
        changed_by INTEGER REFERENCES users(id),
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 4. Provider Listings (Photographers & Rental Gear)
    CREATE TABLE IF NOT EXISTS listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER NOT NULL REFERENCES users(id),
        listing_type TEXT NOT NULL CHECK(listing_type IN ('photographer_with_gear', 'photographer_only', 'gear_rental')),
        title TEXT NOT NULL,
        tagline TEXT,
        category TEXT NOT NULL,
        base_rate TEXT NOT NULL,
        rate_unit TEXT NOT NULL DEFAULT 'per_session',
        gear_details TEXT,
        experience_years INTEGER DEFAULT 5,
        location TEXT NOT NULL,
        rating REAL DEFAULT 4.9,
        reviews_count INTEGER DEFAULT 35,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'deactivated')),
        image_url TEXT,
        rental_conditions TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 5. Bookings Table (Separate status fields for Booking, Payment, Payout)
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_ref TEXT UNIQUE NOT NULL,
        booking_type TEXT NOT NULL CHECK(booking_type IN ('photographer_with_gear', 'photographer_only', 'gear_rental', 'photographer_plus_rented_gear')),
        customer_id INTEGER NOT NULL REFERENCES users(id),
        photographer_listing_id INTEGER REFERENCES listings(id),
        gear_listing_id INTEGER REFERENCES listings(id),
        service_date TEXT NOT NULL,
        service_time TEXT NOT NULL,
        duration_units INTEGER NOT NULL DEFAULT 1,
        location_address TEXT NOT NULL,
        notes TEXT,
        -- Decimal-safe financial fields (stored as exact 2-decimal string)
        photographer_fee TEXT NOT NULL DEFAULT '0.00',
        gear_fee TEXT NOT NULL DEFAULT '0.00',
        addons_fee TEXT NOT NULL DEFAULT '0.00',
        taxes_fee TEXT NOT NULL DEFAULT '0.00',
        total_customer_payment TEXT NOT NULL,
        eligible_booking_amount TEXT NOT NULL,
        -- Historical snapshot fields (never mutate when admin changes default commission!)
        commission_rate_applied TEXT NOT NULL,
        commission_amount TEXT NOT NULL,
        provider_payable_amount TEXT NOT NULL,
        -- Strict distinct statuses
        booking_status TEXT NOT NULL DEFAULT 'Pending' CHECK(booking_status IN ('Pending', 'Accepted', 'Rejected', 'Cancelled', 'Completed')),
        payment_status TEXT NOT NULL DEFAULT 'Not Started' CHECK(payment_status IN ('Not Started', 'Pending', 'Paid', 'Failed', 'Refunded')),
        payout_status TEXT NOT NULL DEFAULT 'Not Eligible' CHECK(payout_status IN ('Not Eligible', 'Pending', 'Payable', 'Paid', 'Reversed')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 6. Booking Addons
    CREATE TABLE IF NOT EXISTS booking_addons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
        addon_key TEXT NOT NULL,
        title TEXT NOT NULL,
        price TEXT NOT NULL
    );

    -- 7. Payments Table (Idempotent demo transactions)
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL REFERENCES bookings(id),
        transaction_ref TEXT UNIQUE NOT NULL,
        idempotency_key TEXT UNIQUE NOT NULL,
        amount TEXT NOT NULL,
        payment_method TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('Not Started', 'Pending', 'Paid', 'Failed', 'Refunded')),
        is_demo INTEGER NOT NULL DEFAULT 1,
        gateway_name TEXT NOT NULL DEFAULT 'SnapLocal Demo Sandbox Gateway',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 8. Provider Payout Records (Supports 1 or 2 providers per booking)
    CREATE TABLE IF NOT EXISTS payout_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL REFERENCES bookings(id),
        provider_id INTEGER NOT NULL REFERENCES users(id),
        role_in_booking TEXT NOT NULL, -- 'photographer' or 'gear_provider'
        gross_amount TEXT NOT NULL,
        commission_rate TEXT NOT NULL,
        commission_deducted TEXT NOT NULL,
        net_payable TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('Not Eligible', 'Pending', 'Payable', 'Paid', 'Reversed')),
        payout_ref TEXT,
        paid_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 9. Refunds Table
    CREATE TABLE IF NOT EXISTS refunds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL REFERENCES bookings(id),
        payment_id INTEGER REFERENCES payments(id),
        refund_ref TEXT UNIQUE NOT NULL,
        amount TEXT NOT NULL,
        commission_adjusted TEXT NOT NULL,
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'Processed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- 10. Listing Availability & Time Slots
    CREATE TABLE IF NOT EXISTS listing_availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
        blocked_date TEXT NOT NULL,
        blocked_time TEXT,
        reason TEXT DEFAULT 'Reserved',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Performance Indices
    CREATE INDEX IF NOT EXISTS idx_bookings_customer ON bookings(customer_id);
    CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(booking_status);
    CREATE INDEX IF NOT EXISTS idx_bookings_payment ON bookings(payment_status);
    CREATE INDEX IF NOT EXISTS idx_payouts_provider ON payout_records(provider_id);
    CREATE INDEX IF NOT EXISTS idx_payments_booking ON payments(booking_id);
    CREATE INDEX IF NOT EXISTS idx_avail_listing ON listing_availability(listing_id, blocked_date);
    """)

    conn.commit()

    # Migrate any legacy plaintext passwords to secure hashes
    cursor.execute("SELECT id, password_hash FROM users")
    for row in cursor.fetchall():
        p_hash = row['password_hash']
        if not p_hash.startswith(('scrypt:', 'pbkdf2:')):
            cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(p_hash), row['id']))
    conn.commit()

    # Migrate listings table to add rental_conditions if missing
    try:
        cursor.execute("ALTER TABLE listings ADD COLUMN rental_conditions TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Seed baseline platform config if empty
    cursor.execute("SELECT COUNT(*) FROM platform_config")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO platform_config (commission_rate, tax_rate, currency_symbol, notes)
            VALUES ('10.00', '0.00', '₹', 'Initial platform default commission (10.00%)')
        """)
        conn.commit()

    if seed:
        seed_data(conn)

    conn.close()


def seed_data(conn):
    """Populates realistic users, listings, and full-lifecycle bookings."""
    cursor = conn.cursor()

    # Check if users already seeded
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] > 0:
        return

    # 1. Users with secure password hashing
    users_data = [
        # Admin
        ('Vikram Malhotra', 'admin@snaplocal.com', hash_password('admin123'), 'admin', '+91 98450 11001', 'Bengaluru', 'VM'),
        # Customers
        ('Rohan Patel', 'rohan@gmail.com', hash_password('customer123'), 'customer', '+91 99800 22002', 'Indiranagar, Bengaluru', 'RP'),
        ('Sneha Reddy', 'sneha@gmail.com', hash_password('customer123'), 'customer', '+91 97411 33003', 'Koramangala, Bengaluru', 'SR'),
        # Providers
        ('Arjun Sharma', 'arjun.lens@snaplocal.com', hash_password('provider123'), 'provider', '+91 98200 44004', 'Indiranagar, Bengaluru', 'AS'),
        ('Karan Kapoor', 'karan.shooter@snaplocal.com', hash_password('provider123'), 'provider', '+91 97100 55005', 'Koramangala, Bengaluru', 'KK'),
        ('Priya Nair (GearHub)', 'priya.gear@snaplocal.com', hash_password('provider123'), 'provider', '+91 96320 66006', 'HSR Layout, Bengaluru', 'PN'),
        ('Ananya Roy', 'ananya.cine@snaplocal.com', hash_password('provider123'), 'provider', '+91 95430 77007', 'Whitefield, Bengaluru', 'AR')
    ]

    cursor.executemany("""
        INSERT INTO users (name, email, password_hash, role, phone, city, avatar_initials)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, users_data)
    conn.commit()

    # Fetch user IDs
    cursor.execute("SELECT id, email FROM users")
    user_map = {row['email']: row['id'] for row in cursor.fetchall()}

    # 2. Listings
    listings_data = [
        # Listing 1: Type 1 - Photographer with own camera
        (
            user_map['arjun.lens@snaplocal.com'],
            'photographer_with_gear',
            'Arjun Sharma - Candid Portrait & Wedding Specialist',
            'Award-winning wedding and portrait photographer equipped with flagship full-frame kit',
            'Weddings & Portraits',
            '2500.00',
            'per_session',
            'Sony A7 IV + 24-70mm f/2.8 GM II + 85mm f/1.4 Art + Godox V1 On-Camera Flash',
            6,
            'Indiranagar, Bengaluru',
            4.95,
            48,
            'active',
            '/static/images/hero.jpg'
        ),
        # Listing 2: Type 2 - Photographer without camera (operator/shooter only)
        (
            user_map['karan.shooter@snaplocal.com'],
            'photographer_only',
            'Karan Kapoor - Freelance Camera Operator & Event Shooter',
            'Skilled freelance cameraman. Bring your own cameras/lenses or rent separately on SnapLocal!',
            'Events & Fashion',
            '1500.00',
            'per_session',
            'Shooter only (Operator certified on Sony Alpha, Canon Cinema EOS, RED, and Blackmagic)',
            4,
            'Koramangala, Bengaluru',
            4.85,
            32,
            'active',
            '/static/images/hero.jpg'
        ),
        # Listing 3: Type 3 - Gear Rental Only
        (
            user_map['priya.gear@snaplocal.com'],
            'gear_rental',
            'GearHub - Sony FX3 Cinema Line + 24-70 GM Bundle',
            'Full cinema production kit including 4K120p FX3, 24-70mm f/2.8 GM, 3x batteries, CFexpress',
            'Cinema & Video Gear',
            '2200.00',
            'per_day',
            'Sony FX3 + 24-70mm GM + 160GB CFexpress Type A + Tilta Cage + 3x NP-FZ100 Batteries',
            7,
            'HSR Layout, Bengaluru',
            5.0,
            72,
            'active',
            '/static/images/gear.jpg'
        ),
        # Listing 4: Type 3 - Gear Rental Only
        (
            user_map['priya.gear@snaplocal.com'],
            'gear_rental',
            'GearHub - Canon EOS R5 + RF 85mm f/1.2L Studio Prime',
            'Legendary 45MP high-resolution camera paired with the sharpest portrait prime lens',
            'Portrait & Studio Gear',
            '1800.00',
            'per_day',
            'Canon EOS R5 body + Canon RF 85mm f/1.2L USM + Profoto B10X Location Lighting Kit',
            7,
            'HSR Layout, Bengaluru',
            4.9,
            39,
            'active',
            '/static/images/gear.jpg'
        ),
        # Listing 5: Type 1 - Photographer with gear
        (
            user_map['ananya.cine@snaplocal.com'],
            'photographer_with_gear',
            'Ananya Roy - Commercial Architecture & Aerial Cinematography',
            'FAA/DGCA certified drone pilot and commercial videographer with 4K HDR deliverables',
            'Commercial & Aerial',
            '3200.00',
            'per_session',
            'DJI Mavic 3 Pro Cine + Hasselblad Dual Camera + Blackmagic 6K Pro + DJI RS3 Gimbal',
            5,
            'Whitefield, Bengaluru',
            4.98,
            54,
            'active',
            '/static/images/hero.jpg'
        )
    ]

    cursor.executemany("""
        INSERT INTO listings (
            provider_id, listing_type, title, tagline, category, base_rate,
            rate_unit, gear_details, experience_years, location, rating, reviews_count, status, image_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, listings_data)
    conn.commit()

    # Fetch listings
    cursor.execute("SELECT id, title, provider_id, base_rate FROM listings")
    listings_list = cursor.fetchall()
    l_map = {row['title']: row['id'] for row in listings_list}

    # 3. Create realistic sample bookings demonstrating every state and booking type!
    # Sample 1: Booking Type 1 (Photographer with gear) -> Completed & Paid
    # Example from prompt: ₹2,000 -> 10% commission ₹200 -> Provider payable ₹1,800
    q1 = finance.calculate_booking_quote(
        photographer_rate='2000.00',
        gear_rate='0.00',
        addons=None,
        tax_percentage='0.00',
        commission_percentage='10.00',
        booking_type='photographer_with_gear'
    )

    cursor.execute("""
        INSERT INTO bookings (
            booking_ref, booking_type, customer_id, photographer_listing_id,
            service_date, service_time, duration_units, location_address, notes,
            photographer_fee, gear_fee, addons_fee, taxes_fee,
            total_customer_payment, eligible_booking_amount,
            commission_rate_applied, commission_amount, provider_payable_amount,
            booking_status, payment_status, payout_status, created_at
        ) VALUES (
            'SNAP-BK-1001', 'photographer_with_gear', ?, ?,
            '2026-10-05', '10:00 AM', 1, 'Koramangala 4th Block, Bengaluru',
            'Family anniversary celebration photos',
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            'Completed', 'Paid', 'Payable',
            datetime('now', '-4 days')
        )
    """, (
        user_map['rohan@gmail.com'],
        l_map['Arjun Sharma - Candid Portrait & Wedding Specialist'],
        q1['photographer_fee'], q1['gear_fee'], q1['addons_fee'], q1['taxes_fee'],
        q1['total_customer_payment'], q1['eligible_booking_amount'],
        q1['commission_rate_applied'], q1['commission_amount'], q1['provider_payable_amount']
    ))
    bk1_id = cursor.lastrowid

    # Add Payment for BK-1001
    cursor.execute("""
        INSERT INTO payments (
            booking_id, transaction_ref, idempotency_key, amount, payment_method, status, is_demo, gateway_name
        ) VALUES (
            ?, 'TXN-DEMO-784102', 'IDEMP-SNAP-1001', '2000.00', 'Demo UPI', 'Paid', 1, 'SnapLocal Demo Sandbox Gateway'
        )
    """, (bk1_id,))

    # Add Payout record for BK-1001
    cursor.execute("""
        INSERT INTO payout_records (
            booking_id, provider_id, role_in_booking, gross_amount, commission_rate,
            commission_deducted, net_payable, status
        ) VALUES (
            ?, ?, 'photographer', '2000.00', '10.00', '200.00', '1800.00', 'Payable'
        )
    """, (bk1_id, user_map['arjun.lens@snaplocal.com']))

    # Sample 2: Booking Type 4 (Photographer + Rented Gear) -> Accepted & Paid (Pending Event completion)
    # Photographer fee ₹1,500 + Gear rental ₹1,800 + Addon Drone ₹1,200 = ₹4,500
    q2 = finance.calculate_booking_quote(
        photographer_rate='1500.00',
        gear_rate='1800.00',
        addons=[{'key': 'drone', 'title': 'Aerial Drone Angle', 'price': '1200.00'}],
        tax_percentage='0.00',
        commission_percentage='10.00',
        booking_type='photographer_plus_rented_gear'
    )

    cursor.execute("""
        INSERT INTO bookings (
            booking_ref, booking_type, customer_id, photographer_listing_id, gear_listing_id,
            service_date, service_time, duration_units, location_address, notes,
            photographer_fee, gear_fee, addons_fee, taxes_fee,
            total_customer_payment, eligible_booking_amount,
            commission_rate_applied, commission_amount, provider_payable_amount,
            booking_status, payment_status, payout_status, created_at
        ) VALUES (
            'SNAP-BK-1002', 'photographer_plus_rented_gear', ?, ?, ?,
            '2026-10-12', '02:00 PM', 1, 'UB City Amphitheater, Bengaluru',
            'Fashion lookbook shoot with separate cinema gear',
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            'Accepted', 'Paid', 'Pending',
            datetime('now', '-1 days')
        )
    """, (
        user_map['sneha@gmail.com'],
        l_map['Karan Kapoor - Freelance Camera Operator & Event Shooter'],
        l_map['GearHub - Canon EOS R5 + RF 85mm f/1.2L Studio Prime'],
        q2['photographer_fee'], q2['gear_fee'], q2['addons_fee'], q2['taxes_fee'],
        q2['total_customer_payment'], q2['eligible_booking_amount'],
        q2['commission_rate_applied'], q2['commission_amount'], q2['provider_payable_amount']
    ))
    bk2_id = cursor.lastrowid

    # Add Addon record
    cursor.execute("""
        INSERT INTO booking_addons (booking_id, addon_key, title, price)
        VALUES (?, 'drone', 'Aerial Drone Angle', '1200.00')
    """, (bk2_id,))

    # Add Payment for BK-1002
    cursor.execute("""
        INSERT INTO payments (
            booking_id, transaction_ref, idempotency_key, amount, payment_method, status, is_demo, gateway_name
        ) VALUES (
            ?, 'TXN-DEMO-891234', 'IDEMP-SNAP-1002', '4500.00', 'Demo Card Simulator', 'Paid', 1, 'SnapLocal Demo Sandbox Gateway'
        )
    """, (bk2_id,))

    # Add Payout records for both providers (Photographer & Gear Owner)
    # Karan (Photographer + Addon = 1500 + 1200 = 2700 -> comm 270 -> payable 2430)
    cursor.execute("""
        INSERT INTO payout_records (
            booking_id, provider_id, role_in_booking, gross_amount, commission_rate,
            commission_deducted, net_payable, status
        ) VALUES (
            ?, ?, 'photographer', '2700.00', '10.00', '270.00', '2430.00', 'Pending'
        )
    """, (bk2_id, user_map['karan.shooter@snaplocal.com']))

    # Priya (Gear rental = 1800 -> comm 180 -> payable 1620)
    cursor.execute("""
        INSERT INTO payout_records (
            booking_id, provider_id, role_in_booking, gross_amount, commission_rate,
            commission_deducted, net_payable, status
        ) VALUES (
            ?, ?, 'gear_provider', '1800.00', '10.00', '180.00', '1620.00', 'Pending'
        )
    """, (bk2_id, user_map['priya.gear@snaplocal.com']))

    # Sample 3: Booking Type 3 (Camera Gear Rental Only) -> Accepted, Payment Not Started (Ready to pay!)
    q3 = finance.calculate_booking_quote(
        photographer_rate='0.00',
        gear_rate='2200.00',
        addons=None,
        tax_percentage='0.00',
        commission_percentage='10.00',
        booking_type='gear_rental'
    )
    cursor.execute("""
        INSERT INTO bookings (
            booking_ref, booking_type, customer_id, gear_listing_id,
            service_date, service_time, duration_units, location_address, notes,
            photographer_fee, gear_fee, addons_fee, taxes_fee,
            total_customer_payment, eligible_booking_amount,
            commission_rate_applied, commission_amount, provider_payable_amount,
            booking_status, payment_status, payout_status, created_at
        ) VALUES (
            'SNAP-BK-1003', 'gear_rental', ?, ?,
            '2026-10-15', '09:00 AM', 1, 'HSR Layout Sector 2, Bengaluru',
            'Independent documentary short film production',
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            'Accepted', 'Not Started', 'Not Eligible',
            datetime('now', '-2 hours')
        )
    """, (
        user_map['rohan@gmail.com'],
        l_map['GearHub - Sony FX3 Cinema Line + 24-70 GM Bundle'],
        q3['photographer_fee'], q3['gear_fee'], q3['addons_fee'], q3['taxes_fee'],
        q3['total_customer_payment'], q3['eligible_booking_amount'],
        q3['commission_rate_applied'], q3['commission_amount'], q3['provider_payable_amount']
    ))

    # Sample 4: Booking Type 1 -> Pending provider response
    q4 = finance.calculate_booking_quote(
        photographer_rate='3200.00',
        gear_rate='0.00',
        addons=[{'key': 'lighting', 'title': 'Studio Lighting Grid', 'price': '800.00'}],
        tax_percentage='0.00',
        commission_percentage='10.00',
        booking_type='photographer_with_gear'
    )
    cursor.execute("""
        INSERT INTO bookings (
            booking_ref, booking_type, customer_id, photographer_listing_id,
            service_date, service_time, duration_units, location_address, notes,
            photographer_fee, gear_fee, addons_fee, taxes_fee,
            total_customer_payment, eligible_booking_amount,
            commission_rate_applied, commission_amount, provider_payable_amount,
            booking_status, payment_status, payout_status, created_at
        ) VALUES (
            'SNAP-BK-1004', 'photographer_with_gear', ?, ?,
            '2026-10-18', '04:00 PM', 1, 'Whitefield Tech Park, Bengaluru',
            'Corporate campus architectural promo',
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            'Pending', 'Not Started', 'Not Eligible',
            datetime('now', '-30 minutes')
        )
    """, (
        user_map['sneha@gmail.com'],
        l_map['Ananya Roy - Commercial Architecture & Aerial Cinematography'],
        q4['photographer_fee'], q4['gear_fee'], q4['addons_fee'], q4['taxes_fee'],
        q4['total_customer_payment'], q4['eligible_booking_amount'],
        q4['commission_rate_applied'], q4['commission_amount'], q4['provider_payable_amount']
    ))

    # Sample 5: Cancelled & Refunded booking
    q5 = finance.calculate_booking_quote(
        photographer_rate='2500.00',
        gear_rate='0.00',
        addons=None,
        tax_percentage='0.00',
        commission_percentage='10.00',
        booking_type='photographer_with_gear'
    )
    cursor.execute("""
        INSERT INTO bookings (
            booking_ref, booking_type, customer_id, photographer_listing_id,
            service_date, service_time, duration_units, location_address, notes,
            photographer_fee, gear_fee, addons_fee, taxes_fee,
            total_customer_payment, eligible_booking_amount,
            commission_rate_applied, commission_amount, provider_payable_amount,
            booking_status, payment_status, payout_status, created_at
        ) VALUES (
            'SNAP-BK-1005', 'photographer_with_gear', ?, ?,
            '2026-10-02', '11:00 AM', 1, 'MG Road, Bengaluru',
            'Pre-wedding photoshoot (Client rescheduled event)',
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            'Cancelled', 'Refunded', 'Reversed',
            datetime('now', '-8 days')
        )
    """, (
        user_map['rohan@gmail.com'],
        l_map['Arjun Sharma - Candid Portrait & Wedding Specialist'],
        q5['photographer_fee'], q5['gear_fee'], q5['addons_fee'], q5['taxes_fee'],
        q5['total_customer_payment'], q5['eligible_booking_amount'],
        q5['commission_rate_applied'], q5['commission_amount'], q5['provider_payable_amount']
    ))
    bk5_id = cursor.lastrowid

    # Payment for BK-1005
    cursor.execute("""
        INSERT INTO payments (
            booking_id, transaction_ref, idempotency_key, amount, payment_method, status, is_demo, gateway_name
        ) VALUES (
            ?, 'TXN-DEMO-651982', 'IDEMP-SNAP-1005', '2500.00', 'Demo UPI', 'Refunded', 1, 'SnapLocal Demo Sandbox Gateway'
        )
    """, (bk5_id,))
    pay5_id = cursor.lastrowid

    # Refund record for BK-1005
    cursor.execute("""
        INSERT INTO refunds (
            booking_id, payment_id, refund_ref, amount, commission_adjusted, reason, status
        ) VALUES (
            ?, ?, 'REF-DEMO-3091', '2500.00', '250.00', 'Client cancelled due to rain; 100% full demo refund issued', 'Processed'
        )
    """, (bk5_id, pay5_id))

    conn.commit()


if __name__ == '__main__':
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    init_db(seed=True)
    print("Database initialized and seeded successfully at", DB_FILE)
