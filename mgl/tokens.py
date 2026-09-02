"""UFL token increment rules.

Valid costs use 0.5 steps: 0, 0.5, 1, 1.5, …
The locked exception is the manager auction listing fee of 0.1 TKN.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TOKEN_STEP = Decimal("0.5")
MANAGER_AUCTION_LISTING_FEE = Decimal("0.1")


def as_token(amount):
    try:
        return Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Enter a valid token amount.") from exc


def is_half_step(amount):
    value = as_token(amount)
    return (value * 2) == (value * 2).to_integral_value() and value >= 0


def is_listing_fee(amount):
    return as_token(amount) == MANAGER_AUCTION_LISTING_FEE


def validate_token_amount(amount, *, allow_listing_fee=False):
    value = as_token(amount)
    if allow_listing_fee and is_listing_fee(value):
        return value
    if not is_half_step(value):
        raise ValueError("UFL Coin amounts must use 0.5 increments (0, 0.5, 1, 1.5, …).")
    return value
