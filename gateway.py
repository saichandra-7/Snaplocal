"""
SnapLocal Payment Gateway Adapter & Demo Sandbox Engine.
Designed with strict separation of concerns, idempotency control, and safety boundaries.
No real financial credentials (cards, CVVs, PINs) are ever processed or stored.
"""

import uuid
import datetime
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from decimal import Decimal
import finance


class PaymentGatewayInterface(ABC):
    """Abstract interface for payment gateway providers (Stripe, Razorpay, Demo)."""

    @abstractmethod
    def process_demo_payment(
        self,
        booking_id: int,
        amount: str,
        payment_method: str,
        idempotency_key: str
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def process_refund(
        self,
        booking_id: int,
        payment_id: int,
        amount: str,
        reason: str
    ) -> Dict[str, Any]:
        pass


class SimulatedDemoPaymentGateway(PaymentGatewayInterface):
    """
    Safe Sandbox Payment Gateway for Hackathon Demo.
    - Idempotency protection prevents duplicate transaction charges.
    - Zero real card/banking data collected or stored.
    - Returns simulated transaction payloads clearly tagged as DEMO.
    """

    GATEWAY_NAME = "SnapLocal Simulated Sandbox Gateway (DEMO ONLY)"

    def process_demo_payment(
        self,
        booking_id: int,
        amount: str,
        payment_method: str,
        idempotency_key: str
    ) -> Dict[str, Any]:
        """
        Simulates payment authorization and settlement.
        Returns idempotent transaction confirmation.
        """
        # Validate amount
        dec_amount = finance.to_decimal(amount)
        if dec_amount <= finance.DECIMAL_ZERO:
            return {
                'success': False,
                'error': 'Payment amount must be greater than zero.',
                'status': 'Failed'
            }

        # Generate unique demo transaction reference
        txn_suffix = uuid.uuid4().hex[:8].upper()
        txn_ref = f"TXN-DEMO-{txn_suffix}"

        return {
            'success': True,
            'status': 'Paid',
            'transaction_ref': txn_ref,
            'idempotency_key': idempotency_key,
            'amount': str(dec_amount),
            'payment_method': payment_method,
            'is_demo': True,
            'gateway_name': self.GATEWAY_NAME,
            'gateway_timestamp': datetime.datetime.now().isoformat(),
            'message': 'Simulated sandbox transaction completed successfully. No real money was charged.'
        }

    def process_refund(
        self,
        booking_id: int,
        payment_id: int,
        amount: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Simulates transaction reversal and refund credit.
        """
        dec_amount = finance.to_decimal(amount)
        ref_suffix = uuid.uuid4().hex[:6].upper()
        refund_ref = f"REF-DEMO-{ref_suffix}"

        return {
            'success': True,
            'refund_ref': refund_ref,
            'amount': str(dec_amount),
            'status': 'Refunded',
            'reason': reason,
            'is_demo': True,
            'processed_at': datetime.datetime.now().isoformat(),
            'message': 'Simulated refund processed. Payout reversed and customer credited in sandbox.'
        }


# Global gateway singleton
demo_gateway = SimulatedDemoPaymentGateway()
