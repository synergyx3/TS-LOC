from decimal import Decimal
from uuid import uuid4

import pytest

from ts_local.models import FollowerConfig


def test_scaled_quantity_applies_multiplier():
    follower = FollowerConfig(account_id=uuid4(), multiplier=Decimal("1.5"))
    assert follower.scaled_quantity(4) == 6


def test_scaled_quantity_rounds_down_to_integer_contracts():
    follower = FollowerConfig(account_id=uuid4(), multiplier=Decimal("0.4"))
    assert follower.scaled_quantity(3) == 1


def test_negative_leader_quantity_is_rejected():
    follower = FollowerConfig(account_id=uuid4(), multiplier=Decimal("1"))
    with pytest.raises(ValueError):
        follower.scaled_quantity(-1)
