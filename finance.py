"""
SnapLocal Decimal-Safe Financial and Commission Engine.
All monetary amounts are represented as Decimal with 2 decimal places (ROUND_HALF_UP).
No floating-point arithmetic is used for financial calculations.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional

DECIMAL_ZERO = Decimal('0.00')
CENT = Decimal('0.01')


def to_decimal(val: Any) -> Decimal:
    """Safely convert any numeric, string or Decimal to a 2-decimal place Decimal."""
    if val is None:
        return DECIMAL_ZERO
    if isinstance(val, Decimal):
        return val.quantize(CENT, rounding=ROUND_HALF_UP)
    try:
        # Avoid float precision artifacts by string conversion
        return Decimal(str(val)).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return DECIMAL_ZERO


def calculate_booking_quote(
    photographer_rate: Any,
    gear_rate: Any,
    addons: Optional[List[Dict[str, Any]]] = None,
    tax_percentage: Any = Decimal('0.00'),
    commission_percentage: Any = Decimal('10.00'),
    booking_type: str = 'photographer_with_gear'
) -> Dict[str, Any]:
    """
    Computes a complete, transparent price breakdown and provider payout projection.
    
    Rules:
    - Customer pays: photographer_fee + gear_fee + addons_fee + applicable taxes.
    - Eligible booking amount: services & rentals delivered (photographer_fee + gear_fee + addons_fee).
    - Platform commission: deducted from provider earnings (eligible_booking_amount * commission_rate / 100).
    - Provider payable amount: eligible_booking_amount - commission_amount.
    - Commission is NEVER added on top of the customer fee or charged twice.
    """
    p_fee = to_decimal(photographer_rate)
    g_fee = to_decimal(gear_rate)
    
    addons_fee = DECIMAL_ZERO
    addons_list = []
    if addons:
        for addon in addons:
            price = to_decimal(addon.get('price', 0))
            addons_fee += price
            addons_list.append({
                'key': addon.get('key', 'addon'),
                'title': addon.get('title', 'Addon'),
                'price': str(price)
            })
    addons_fee = addons_fee.quantize(CENT, rounding=ROUND_HALF_UP)

    tax_pct = to_decimal(tax_percentage)
    comm_pct = to_decimal(commission_percentage)

    # Eligible booking amount for services
    eligible_booking_amount = (p_fee + g_fee + addons_fee).quantize(CENT, rounding=ROUND_HALF_UP)

    # Applicable taxes on customer (if configured, default 0.00)
    if tax_pct > DECIMAL_ZERO:
        taxes_fee = (eligible_booking_amount * (tax_pct / Decimal('100'))).quantize(CENT, rounding=ROUND_HALF_UP)
    else:
        taxes_fee = DECIMAL_ZERO

    # Total customer payment
    total_customer_payment = (eligible_booking_amount + taxes_fee).quantize(CENT, rounding=ROUND_HALF_UP)

    # Platform commission deducted from provider
    commission_amount = (eligible_booking_amount * (comm_pct / Decimal('100'))).quantize(CENT, rounding=ROUND_HALF_UP)

    # Provider payable amount
    provider_payable_amount = (eligible_booking_amount - commission_amount).quantize(CENT, rounding=ROUND_HALF_UP)

    # Split between photographer and gear rental provider if combined package (Type 4)
    # Both share the same commission percentage rate
    p_commission = (p_fee * (comm_pct / Decimal('100'))).quantize(CENT, rounding=ROUND_HALF_UP)
    p_payable = (p_fee - p_commission).quantize(CENT, rounding=ROUND_HALF_UP)

    # Addons typically go to photographer unless gear-only
    g_commission = (g_fee * (comm_pct / Decimal('100'))).quantize(CENT, rounding=ROUND_HALF_UP)
    g_payable = (g_fee - g_commission).quantize(CENT, rounding=ROUND_HALF_UP)

    return {
        'booking_type': booking_type,
        'photographer_fee': str(p_fee),
        'gear_fee': str(g_fee),
        'addons_fee': str(addons_fee),
        'addons': addons_list,
        'taxes_fee': str(taxes_fee),
        'tax_percentage': str(tax_pct),
        'eligible_booking_amount': str(eligible_booking_amount),
        'total_customer_payment': str(total_customer_payment),
        'commission_rate_applied': str(comm_pct),
        'commission_amount': str(commission_amount),
        'provider_payable_amount': str(provider_payable_amount),
        'split': {
            'photographer': {
                'gross': str(p_fee),
                'commission': str(p_commission),
                'net_payable': str(p_payable)
            },
            'gear_provider': {
                'gross': str(g_fee),
                'commission': str(g_commission),
                'net_payable': str(g_payable)
            }
        }
    }


def format_currency(amount_str_or_val: Any) -> str:
    """Format decimal amount as Indian Rupee string, e.g. '₹2,000.00'."""
    dec = to_decimal(amount_str_or_val)
    # Format with 2 decimal places and thousands separator
    return f"₹{dec:,.2f}"
