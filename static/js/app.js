/**
 * SnapLocal Interactive Engine
 * Handles live quotes, booking requests, demo payment simulation,
 * idempotent checkout, receipts, provider acceptance, and admin actions.
 */

document.addEventListener('DOMContentLoaded', () => {
  initCustomizer();
});

// Toast notification helper
function showToast(message, type = 'info') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span>
    <div>${message}</div>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Interactive Customizer & Live Price Breakdown
function initCustomizer() {
  const form = document.getElementById('booking-customizer-form');
  if (!form) return;

  const bookingTypeRadios = document.querySelectorAll('input[name="booking_type_choice"]');
  const photographerSelect = document.getElementById('select-photographer');
  const gearSelect = document.getElementById('select-gear');
  const addonCheckboxes = document.querySelectorAll('.addon-checkbox');

  // Hook live change listeners
  bookingTypeRadios.forEach(r => r.addEventListener('change', handleTypeChange));
  if (photographerSelect) photographerSelect.addEventListener('change', updateQuote);
  if (gearSelect) gearSelect.addEventListener('change', updateQuote);
  addonCheckboxes.forEach(cb => cb.addEventListener('change', updateQuote));

  form.addEventListener('submit', handleBookingSubmit);

  // Initial calculation
  handleTypeChange();
}

function handleTypeChange() {
  const selectedTypeRadio = document.querySelector('input[name="booking_type_choice"]:checked');
  if (!selectedTypeRadio) return;

  const type = selectedTypeRadio.value;
  const pGroup = document.getElementById('photographer-field-group');
  const gGroup = document.getElementById('gear-field-group');

  if (pGroup && gGroup) {
    if (type === 'photographer_with_gear') {
      pGroup.style.display = 'block';
      gGroup.style.display = 'none';
      filterPhotographers(true);
    } else if (type === 'photographer_only') {
      pGroup.style.display = 'block';
      gGroup.style.display = 'none';
      filterPhotographers(false);
    } else if (type === 'gear_rental') {
      pGroup.style.display = 'none';
      gGroup.style.display = 'block';
    } else if (type === 'photographer_plus_rented_gear') {
      pGroup.style.display = 'block';
      gGroup.style.display = 'block';
      filterPhotographers(false);
    }
  }

  updateQuote();
}

function filterPhotographers(withGear) {
  const photographerSelect = document.getElementById('select-photographer');
  if (!photographerSelect) return;

  Array.from(photographerSelect.options).forEach(opt => {
    if (!opt.value) return;
    const optType = opt.getAttribute('data-type');
    if (withGear) {
      opt.style.display = (optType === 'photographer_with_gear') ? 'block' : 'none';
    } else {
      opt.style.display = (optType === 'photographer_only' || optType === 'photographer_with_gear') ? 'block' : 'none';
    }
  });

  // Ensure selected option is visible
  if (photographerSelect.selectedOptions[0] && photographerSelect.selectedOptions[0].style.display === 'none') {
    for (let opt of photographerSelect.options) {
      if (opt.style.display !== 'none' && opt.value) {
        photographerSelect.value = opt.value;
        break;
      }
    }
  }
}

async function updateQuote() {
  const selectedTypeRadio = document.querySelector('input[name="booking_type_choice"]:checked');
  if (!selectedTypeRadio) return;

  const type = selectedTypeRadio.value;
  const pSelect = document.getElementById('select-photographer');
  const gSelect = document.getElementById('select-gear');

  const pListingId = (type !== 'gear_rental' && pSelect) ? pSelect.value : null;
  const gListingId = (type !== 'photographer_with_gear' && type !== 'photographer_only' && gSelect) ? gSelect.value : null;

  const addons = [];
  document.querySelectorAll('.addon-checkbox:checked').forEach(cb => {
    addons.push({
      key: cb.value,
      title: cb.getAttribute('data-title'),
      price: cb.getAttribute('data-price')
    });
  });

  try {
    const res = await fetch('/api/quote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        booking_type: type,
        photographer_listing_id: pListingId,
        gear_listing_id: gListingId,
        addons: addons
      })
    });

    const data = await res.json();
    if (data.success && data.quote) {
      renderQuoteBreakdown(data.quote);
    }
  } catch (err) {
    console.error('Failed to fetch quote', err);
  }
}

function renderQuoteBreakdown(q) {
  const formatINR = (val) => `₹${parseFloat(val || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;

  const setElText = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.innerText = text;
  };

  setElText('quote-photographer-fee', formatINR(q.photographer_fee));
  setElText('quote-gear-fee', formatINR(q.gear_fee));
  setElText('quote-addons-fee', formatINR(q.addons_fee));
  setElText('quote-taxes-fee', formatINR(q.taxes_fee));
  setElText('quote-total-payment', formatINR(q.total_customer_payment));

  // Toggle rows visibility if zero
  const pRow = document.getElementById('row-photographer-fee');
  const gRow = document.getElementById('row-gear-fee');
  const aRow = document.getElementById('row-addons-fee');

  if (pRow) pRow.style.display = parseFloat(q.photographer_fee) > 0 ? 'flex' : 'none';
  if (gRow) gRow.style.display = parseFloat(q.gear_fee) > 0 ? 'flex' : 'none';
  if (aRow) aRow.style.display = parseFloat(q.addons_fee) > 0 ? 'flex' : 'none';
}

async function handleBookingSubmit(e) {
  e.preventDefault();

  const selectedTypeRadio = document.querySelector('input[name="booking_type_choice"]:checked');
  const type = selectedTypeRadio ? selectedTypeRadio.value : 'photographer_with_gear';
  const pSelect = document.getElementById('select-photographer');
  const gSelect = document.getElementById('select-gear');

  const pListingId = (type !== 'gear_rental' && pSelect) ? pSelect.value : null;
  const gListingId = (type !== 'photographer_with_gear' && type !== 'photographer_only' && gSelect) ? gSelect.value : null;

  if (type !== 'gear_rental' && !pListingId) {
    showToast('Please select a photographer', 'error');
    return;
  }
  if ((type === 'gear_rental' || type === 'photographer_plus_rented_gear') && !gListingId) {
    showToast('Please select camera rental gear', 'error');
    return;
  }

  const serviceDate = document.getElementById('input-service-date').value;
  const serviceTime = document.getElementById('input-service-time').value;
  const location = document.getElementById('input-location').value;
  const notes = document.getElementById('input-notes').value;

  const addons = [];
  document.querySelectorAll('.addon-checkbox:checked').forEach(cb => {
    addons.push({
      key: cb.value,
      title: cb.getAttribute('data-title'),
      price: cb.getAttribute('data-price')
    });
  });

  const payload = {
    booking_type: type,
    photographer_listing_id: pListingId,
    gear_listing_id: gListingId,
    service_date: serviceDate,
    service_time: serviceTime,
    location_address: location,
    notes: notes,
    addons: addons
  };

  const submitBtn = document.getElementById('btn-submit-booking');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerText = 'Submitting Request...';
  }

  try {
    const res = await fetch('/api/bookings/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (data.success) {
      showToast(data.message, 'success');
      setTimeout(() => {
        window.location.href = '/customer';
      }, 1000);
    } else {
      showToast(data.error || 'Failed to submit booking', 'error');
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerText = 'Submit Booking Request';
      }
    }
  } catch (err) {
    showToast('Network error while booking', 'error');
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerText = 'Submit Booking Request';
    }
  }
}

// Provider actions
async function acceptBooking(bookingId) {
  if (!confirm('Accept this booking request? The customer will be invited to checkout.')) return;
  try {
    const res = await fetch(`/api/bookings/${bookingId}/accept`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Action failed', 'error');
    }
  } catch (err) {
    showToast('Failed to accept booking', 'error');
  }
}

async function rejectBooking(bookingId) {
  if (!confirm('Are you sure you want to decline this booking request?')) return;
  try {
    const res = await fetch(`/api/bookings/${bookingId}/reject`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'info');
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Action failed', 'error');
    }
  } catch (err) {
    showToast('Failed to reject booking', 'error');
  }
}

async function markBookingCompleted(bookingId) {
  if (!confirm('Confirm photography service has been delivered? This will transition your payout to Payable status.')) return;
  try {
    const res = await fetch(`/api/bookings/${bookingId}/complete`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Action failed', 'error');
    }
  } catch (err) {
    showToast('Failed to complete booking', 'error');
  }
}

async function cancelBooking(bookingId) {
  const reason = prompt('Please provide a reason for cancelling this booking:');
  if (reason === null) return;

  try {
    const res = await fetch(`/api/bookings/${bookingId}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'Customer requested cancellation' })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'info');
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Action failed', 'error');
    }
  } catch (err) {
    showToast('Failed to cancel booking', 'error');
  }
}

// Demo Checkout Modal
let currentCheckoutBookingId = null;
let currentCheckoutAmount = null;

function openDemoCheckout(bookingId, bookingRef, amount) {
  currentCheckoutBookingId = bookingId;
  currentCheckoutAmount = amount;

  const refEl = document.getElementById('checkout-booking-ref');
  const amtEl = document.getElementById('checkout-amount-display');
  if (refEl) refEl.innerText = bookingRef;
  if (amtEl) amtEl.innerText = `₹${parseFloat(amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;

  const btn = document.getElementById('btn-confirm-demo-payment');
  if (btn) {
    btn.innerText = `Pay ₹${parseFloat(amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })} (Simulate Demo Payment)`;
    btn.disabled = false;
  }

  const idempEl = document.getElementById('checkout-idempotency-key');
  if (idempEl) {
    idempEl.value = `IDEMP-${bookingId}-${Date.now()}`;
  }

  const modal = document.getElementById('demo-checkout-modal');
  if (modal) modal.classList.add('open');
}

function closeDemoCheckout() {
  const modal = document.getElementById('demo-checkout-modal');
  if (modal) modal.classList.remove('open');
}

function switchPaymentTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.payment-tab-content').forEach(c => c.style.display = 'none');

  const activeBtn = document.getElementById(`tab-btn-${tabName}`);
  const activeContent = document.getElementById(`payment-tab-${tabName}`);
  if (activeBtn) activeBtn.classList.add('active');
  if (activeContent) activeContent.style.display = 'block';
}

async function executeDemoPayment() {
  if (!currentCheckoutBookingId) return;

  const btn = document.getElementById('btn-confirm-demo-payment');
  if (btn) {
    btn.disabled = true;
    btn.innerText = 'Processing Simulated Payment...';
  }

  const activeTab = document.querySelector('.tab-btn.active');
  const method = activeTab ? activeTab.getAttribute('data-method') : 'Demo UPI';
  const idempotencyKey = document.getElementById('checkout-idempotency-key').value;

  try {
    const res = await fetch(`/api/bookings/${currentCheckoutBookingId}/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        payment_method: method,
        idempotency_key: idempotencyKey
      })
    });
    const data = await res.json();

    if (data.success) {
      showToast(data.message, 'success');
      closeDemoCheckout();
      setTimeout(() => window.location.reload(), 800);
    } else {
      showToast(data.error || 'Payment failed', 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerText = `Pay ₹${parseFloat(currentCheckoutAmount).toLocaleString('en-IN', { minimumFractionDigits: 2 })} (Simulate Demo Payment)`;
      }
    }
  } catch (err) {
    showToast('Network error during checkout', 'error');
    if (btn) btn.disabled = false;
  }
}

// Receipt Modal Viewer (Customer invoice only)
function openReceiptModal(bookingRef, txnRef, date, method, totalAmount, pFee, gFee, aFee) {
  const formatINR = (val) => `₹${parseFloat(val || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;

  const setEl = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.innerText = val;
  };

  setEl('rcpt-booking-ref', bookingRef);
  setEl('rcpt-txn-ref', txnRef || 'TXN-DEMO-RECORDED');
  setEl('rcpt-date', date);
  setEl('rcpt-method', method || 'Demo Payment Sandbox');
  setEl('rcpt-total', formatINR(totalAmount));
  setEl('rcpt-p-fee', formatINR(pFee));
  setEl('rcpt-g-fee', formatINR(gFee));
  setEl('rcpt-a-fee', formatINR(aFee));

  const modal = document.getElementById('receipt-modal');
  if (modal) modal.classList.add('open');
}

function closeReceiptModal() {
  const modal = document.getElementById('receipt-modal');
  if (modal) modal.classList.remove('open');
}

// Admin Commission Configuration
async function updateAdminCommission(e) {
  e.preventDefault();
  const rateInput = document.getElementById('admin-commission-rate-input');
  const reasonInput = document.getElementById('admin-commission-reason');
  const rate = rateInput.value;
  const reason = reasonInput.value;

  if (!rate || isNaN(rate) || parseFloat(rate) < 0 || parseFloat(rate) > 50) {
    showToast('Please enter a valid commission percentage between 0 and 50%', 'error');
    return;
  }

  try {
    const res = await fetch('/api/admin/commission', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ commission_rate: rate, reason: reason })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      setTimeout(() => window.location.reload(), 800);
    } else {
      showToast(data.error || 'Failed to update commission', 'error');
    }
  } catch (err) {
    showToast('Network error updating commission', 'error');
  }
}

// Admin Moderation Toggle
async function toggleListingStatus(listingId) {
  try {
    const res = await fetch(`/api/admin/listing/${listingId}/toggle`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      setTimeout(() => window.location.reload(), 500);
    } else {
      showToast(data.error || 'Failed to update listing', 'error');
    }
  } catch (err) {
    showToast('Network error toggling listing status', 'error');
  }
}

// Admin Payout Disbursement
async function disbursePayout(payoutId) {
  if (!confirm('Confirm disbursement of this provider payout?')) return;
  try {
    const res = await fetch(`/api/payouts/${payoutId}/disburse`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, 'success');
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Disbursement failed', 'error');
    }
  } catch (err) {
    showToast('Failed to disburse payout', 'error');
  }
}
