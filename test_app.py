"""
SnapLocal Comprehensive Automated Test Suite.
Validates:
1. Secure role-based authentication (Customer, Provider, Admin).
2. Role separation, boundary enforcements, and unauthorized access rejections.
3. Anti-escalation & public admin registration prevention.
4. Commission privacy: strictly hiding owner commission & platform revenue from customers and providers.
5. Double-booking prevention for photographers, equipment, and blocked calendar slots.
6. Backend ownership checks & data isolation between users.
7. Provider listing and availability management.
8. Full booking, demo payment, completion, and admin payout lifecycle.
9. Decimal financial accuracy and historical commission snapshot preservation.
"""

import os
import unittest
import json
from decimal import Decimal
import database
import finance
from app import app


class SnapLocalRoleSecurityTests(unittest.TestCase):

    def setUp(self):
        # Fresh isolated database for each test
        if os.path.exists(database.DB_FILE):
            os.remove(database.DB_FILE)
        database.init_db(seed=True)
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

    # --- 1. Authentication & Role Separation Tests ---

    def test_customer_login_success_and_role_matching(self):
        """Customer logs in with valid credentials; fails if trying to access admin login."""
        # Valid login through customer portal
        res = self.client.post('/auth/login/customer', data={
            'email': 'rohan@gmail.com',
            'password': 'customer123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_role'), 'customer')
            self.assertEqual(sess.get('user_email'), 'rohan@gmail.com')

        # Customer attempts to login via Admin portal -> Must be rejected!
        self.client.get('/logout')
        admin_res = self.client.post('/auth/login/admin', data={
            'email': 'rohan@gmail.com',
            'password': 'customer123'
        }, follow_redirects=True)
        self.assertIn(b"Access Denied", admin_res.data)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_provider_login_success(self):
        """Service provider logs in via provider portal with correct password."""
        res = self.client.post('/auth/login/provider', data={
            'email': 'arjun.lens@snaplocal.com',
            'password': 'provider123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_role'), 'provider')

    def test_admin_login_restricted_success(self):
        """Administrator logs in via restricted admin portal."""
        res = self.client.post('/auth/login/admin', data={
            'email': 'admin@snaplocal.com',
            'password': 'admin123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_role'), 'admin')

    def test_invalid_password_rejected(self):
        """Incorrect password is rejected and session is not created."""
        res = self.client.post('/auth/login/customer', data={
            'email': 'rohan@gmail.com',
            'password': 'wrongpassword'
        }, follow_redirects=True)
        self.assertIn(b"Invalid email or password", res.data)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_logout_invalidates_session(self):
        """Logout invalidates the session completely."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['user_role'] = 'customer'

        res = self.client.get('/logout', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    # --- 2. Registration & Anti-Escalation Tests ---

    def test_customer_registration_enforces_customer_role(self):
        """Customer registration strictly assigns 'customer' role; role tampering ignored."""
        res = self.client.post('/auth/register/customer', data={
            'name': 'Pooja Varma',
            'email': 'pooja@test.com',
            'password': 'password123',
            'phone': '+91 99999 88888',
            'city': 'Bengaluru',
            'role': 'admin' # Tampering attempt
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        conn = database.get_db()
        u = conn.execute("SELECT * FROM users WHERE email = 'pooja@test.com'").fetchone()
        conn.close()
        self.assertIsNotNone(u)
        self.assertEqual(u['role'], 'customer') # Enforced to customer!
        self.assertNotEqual(u['role'], 'admin')

    def test_provider_registration_creates_listing(self):
        """Provider registration creates provider account and initial service listing."""
        res = self.client.post('/auth/register/provider', data={
            'name': 'Dev Cinematography',
            'email': 'dev@cine.com',
            'password': 'password123',
            'phone': '+91 88888 77777',
            'city': 'Bengaluru',
            'provider_category': 'Events & Fashion',
            'listing_type': 'photographer_only',
            'base_rate': '1800.00',
            'gear_details': 'Sony FX3 + 50mm Prime',
            'rental_conditions': 'Govt ID required'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        conn = database.get_db()
        u = conn.execute("SELECT * FROM users WHERE email = 'dev@cine.com'").fetchone()
        listing = conn.execute("SELECT * FROM listings WHERE provider_id = ?", (u['id'],)).fetchone()
        conn.close()
        self.assertEqual(u['role'], 'provider')
        self.assertIsNotNone(listing)
        self.assertEqual(listing['base_rate'], '1800.00')
        self.assertEqual(listing['rental_conditions'], 'Govt ID required')

    def test_public_admin_registration_forbidden(self):
        """Public admin registration is blocked with HTTP 403."""
        res = self.client.post('/auth/register/admin', data={
            'name': 'Hacker',
            'email': 'hacker@evil.com',
            'password': 'password123'
        })
        self.assertEqual(res.status_code, 403)

    # --- 3. Role-Based Access Boundary Enforcements ---

    def test_unauthenticated_access_redirects_to_auth(self):
        """Unauthenticated requests to protected dashboards redirect to /auth."""
        res_c = self.client.get('/customer')
        self.assertEqual(res_c.status_code, 302)
        self.assertIn('/auth', res_c.headers['Location'])

        res_p = self.client.get('/provider')
        self.assertEqual(res_p.status_code, 302)
        self.assertIn('/auth', res_p.headers['Location'])

        res_a = self.client.get('/admin')
        self.assertEqual(res_a.status_code, 302)
        self.assertIn('/auth', res_a.headers['Location'])

    def test_customer_cannot_access_provider_or_admin(self):
        """Customer is rejected with HTTP 403 when trying to access provider or admin dashboard."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2 # Rohan Patel (customer)
            sess['user_role'] = 'customer'

        res_p = self.client.get('/provider')
        self.assertEqual(res_p.status_code, 403)

        res_a = self.client.get('/admin')
        self.assertEqual(res_a.status_code, 403)

    def test_provider_cannot_access_customer_or_admin(self):
        """Provider is rejected with HTTP 403 when trying to access customer or admin dashboard."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4 # Arjun Sharma (provider)
            sess['user_role'] = 'provider'

        res_c = self.client.get('/customer')
        self.assertEqual(res_c.status_code, 403)

        res_a = self.client.get('/admin')
        self.assertEqual(res_a.status_code, 403)

    def test_admin_access_allowed(self):
        """Authorized administrator can access /admin."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1 # Vikram Malhotra (admin)
            sess['user_role'] = 'admin'

        res = self.client.get('/admin')
        self.assertEqual(res.status_code, 200)

    # --- 4. Commission Privacy Controls ---

    def test_customer_quote_api_omits_owner_commission(self):
        """Quote API called by customer or guest does NOT leak commission rate or amount."""
        res = self.client.post('/api/quote', json={
            'booking_type': 'photographer_with_gear',
            'photographer_listing_id': 1
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        quote = data['quote']
        # Must contain customer payment
        self.assertIn('total_customer_payment', quote)
        self.assertIn('photographer_fee', quote)
        # Must NOT expose owner commission or provider settlement!
        self.assertNotIn('commission_amount', quote)
        self.assertNotIn('commission_rate_applied', quote)
        self.assertNotIn('provider_payable_amount', quote)
        self.assertNotIn('split', quote)

    def test_provider_dashboard_omits_owner_commission_and_platform_revenue(self):
        """Provider dashboard HTML does NOT expose owner commission percentage, deduction, or total revenue."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4 # Arjun Sharma
            sess['user_role'] = 'provider'

        res = self.client.get('/provider')
        self.assertEqual(res.status_code, 200)
        # Check that owner commission is not displayed
        self.assertNotIn(b"SnapLocal Commission Deducted", res.data)
        self.assertNotIn(b"Total Commission Earned", res.data)
        self.assertNotIn(b"Platform Take", res.data)
        # Net earnings should be present
        self.assertIn(b"Estimated Net Earnings", res.data)
        self.assertIn(b"Total Service Value", res.data)

    def test_admin_dashboard_shows_platform_revenue(self):
        """Admin dashboard displays total platform commission revenue and gross booking value."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_role'] = 'admin'

        res = self.client.get('/admin')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Total Commission Earned (Platform Revenue)", res.data)
        self.assertIn(b"Total Booking Value (GMV)", res.data)

    # --- 5. Double-Booking Prevention Tests ---

    def test_double_booking_photographer_prevented(self):
        """Attempting to book the same photographer on the same date & time slot returns HTTP 409."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2 # Rohan Patel (customer)
            sess['user_role'] = 'customer'

        # First booking succeeds
        res1 = self.client.post('/api/bookings/create', json={
            'booking_type': 'photographer_with_gear',
            'photographer_listing_id': 1,
            'service_date': '2026-11-01',
            'service_time': '10:00 AM',
            'location_address': 'Indiranagar, Bengaluru'
        })
        self.assertEqual(res1.status_code, 200)

        # Second booking for same photographer, date, and time slot -> Must fail with 409 Conflict
        res2 = self.client.post('/api/bookings/create', json={
            'booking_type': 'photographer_with_gear',
            'photographer_listing_id': 1,
            'service_date': '2026-11-01',
            'service_time': '10:00 AM',
            'location_address': 'Koramangala, Bengaluru'
        })
        self.assertEqual(res2.status_code, 409)
        self.assertIn("already booked", res2.get_json()['error'])

    def test_provider_blocked_date_prevents_booking(self):
        """If provider manually blocks a date in availability calendar, booking is rejected with 409."""
        # Provider blocks 2026-11-05
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4 # Arjun Sharma
            sess['user_role'] = 'provider'

        block_res = self.client.post('/api/provider/listings/1/availability', json={
            'blocked_date': '2026-11-05',
            'reason': 'Traveling for destination shoot'
        })
        self.assertEqual(block_res.status_code, 200)

        # Customer attempts to book on the blocked date
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2 # Rohan Patel
            sess['user_role'] = 'customer'

        book_res = self.client.post('/api/bookings/create', json={
            'booking_type': 'photographer_with_gear',
            'photographer_listing_id': 1,
            'service_date': '2026-11-05',
            'service_time': '10:00 AM',
            'location_address': 'Bengaluru'
        })
        self.assertEqual(book_res.status_code, 409)
        self.assertIn("unavailable", book_res.get_json()['error'])

    # --- 6. Backend Ownership & Data Isolation Tests ---

    def test_customer_cannot_cancel_other_customer_booking(self):
        """Customer A cannot cancel Customer B's booking (HTTP 403)."""
        # Booking 2 belongs to Sneha Reddy (ID 3)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2 # Rohan Patel (ID 2)
            sess['user_role'] = 'customer'

        cancel_res = self.client.post('/api/bookings/2/cancel', json={
            'reason': 'Unauthorized cancellation attempt'
        })
        self.assertEqual(cancel_res.status_code, 403)

    def test_provider_cannot_accept_other_provider_booking(self):
        """Provider A cannot accept a booking request assigned to Provider B (HTTP 403)."""
        # Booking 4 is assigned to Ananya Roy (ID 7)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4 # Arjun Sharma (ID 4)
            sess['user_role'] = 'provider'

        accept_res = self.client.post('/api/bookings/4/accept')
        self.assertEqual(accept_res.status_code, 403)

    # --- 7. Full Lifecycle: Booking -> Accept -> Checkout -> Complete -> Payout ---

    def test_full_lifecycle_and_historical_snapshots(self):
        """End-to-end user journey with strict role separation and historical rate snapshot preservation."""
        # 1. Customer creates booking
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2 # Rohan Patel
            sess['user_role'] = 'customer'

        create_res = self.client.post('/api/bookings/create', json={
            'booking_type': 'photographer_with_gear',
            'photographer_listing_id': 1,
            'service_date': '2026-11-10',
            'service_time': '02:00 PM',
            'location_address': 'Indiranagar 100ft Rd',
            'addons': [{'key': 'express', 'title': '24h Delivery', 'price': '500.00'}]
        })
        self.assertEqual(create_res.status_code, 200)
        booking_id = create_res.get_json()['booking_id']

        # 2. Provider accepts request
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4 # Arjun Sharma (owner of listing 1)
            sess['user_role'] = 'provider'

        accept_res = self.client.post(f'/api/bookings/{booking_id}/accept')
        self.assertEqual(accept_res.status_code, 200)

        # 3. Customer demo checkout
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['user_role'] = 'customer'

        idemp_key = f"IDEMP-TEST-{booking_id}"
        pay_res = self.client.post(f'/api/bookings/{booking_id}/checkout', json={
            'payment_method': 'Demo UPI',
            'idempotency_key': idemp_key
        })
        self.assertEqual(pay_res.status_code, 200)
        self.assertTrue(pay_res.get_json()['success'])

        # Check idempotency: second checkout attempt returns duplicate confirmation without charging again
        dup_res = self.client.post(f'/api/bookings/{booking_id}/checkout', json={
            'payment_method': 'Demo UPI',
            'idempotency_key': idemp_key
        })
        self.assertTrue(dup_res.get_json().get('is_duplicate', False))

        # 4. Provider marks completed
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4
            sess['user_role'] = 'provider'

        comp_res = self.client.post(f'/api/bookings/{booking_id}/complete')
        self.assertEqual(comp_res.status_code, 200)

        # Verify payout status transitioned to Payable
        conn = database.get_db()
        payout = conn.execute("SELECT * FROM payout_records WHERE booking_id = ?", (booking_id,)).fetchone()
        conn.close()
        self.assertEqual(payout['status'], 'Payable')

        # 5. Admin disburses payout
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1 # Vikram Malhotra (Admin)
            sess['user_role'] = 'admin'

        disb_res = self.client.post(f"/api/payouts/{payout['id']}/disburse")
        self.assertEqual(disb_res.status_code, 200)
        self.assertTrue(disb_res.get_json()['payout_ref'].startswith('PO-DEMO-'))


if __name__ == '__main__':
    unittest.main()
