"""One authoritative quote for checkout preview and payment activation.

Money is not charged for the carried balance: it buys time on the new tier.
The stored rate retains the value of earlier renewals and discounts.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil

from app.services.subscription_kinds import (
    PAID_STACK_SKIP_PLANS, devices_for_plan, plan_expires_at,
)


@dataclass(frozen=True)
class RenewalQuote:
    plan_type: str
    purchased_days: float
    amount: float
    expires_at: datetime
    daily_rate: Decimal
    remaining_days: float
    carried_days: float
    old_devices: int | None
    new_devices: int

    def as_dict(self) -> dict:
        expiry = self.expires_at.strftime("%d.%m.%Y")
        amount = f"{self.amount:g}"
        remaining, carried, purchased = map(ceil, (self.remaining_days, self.carried_days, self.purchased_days))
        from app.services.subscription_kinds import duration_plan_key
        name = {"monthly": "1 месяц", "two_months": "2 месяца", "quarterly": "3 месяца",
                "half_year": "6 месяцев", "yearly": "12 месяцев"}.get(duration_plan_key(self.plan_type), self.plan_type)
        purchase = f"Вы покупаете: {name} на {self.new_devices} устройств за {amount} ₽. "
        if self.old_devices and self.old_devices != self.new_devices:
            message = (
                purchase +
                f"После оплаты лимит изменится с {self.old_devices} на {self.new_devices} устройств. "
                f"Остаток {remaining} дн. пересчитается в {carried} дн. "
                f"нового тарифа. Новый срок: {purchased} дн. покупки + "
                f"{carried} дн. остатка. Подписка будет действовать до {expiry}. "
                f"К оплате {amount} ₽ — цена выбранного тарифа не меняется."
            )
        elif self.old_devices:
            message = (
                purchase +
                f"Остаток {remaining} дн. сохранится, новый срок прибавится к нему. "
                f"Подписка будет действовать до {expiry}. К оплате {amount} ₽."
            )
        else:
            message = purchase + f"Подписка начнётся после оплаты и будет действовать до {expiry}."
        message += " Расчёт предварительный; срок уточняется при подтверждении оплаты."
        return {
            "plan_type": self.plan_type, "purchased_days": purchased,
            "amount": self.amount, "expires_at": self.expires_at.isoformat() + "Z",
            "remaining_days": remaining,
            "carried_days": carried,
            "old_devices": self.old_devices, "new_devices": self.new_devices,
            "message": message,
        }


def quote_renewal(*, now: datetime, plan_type: str, amount: float,
                  prices: dict, subscriptions: list) -> RenewalQuote:
    if plan_type not in prices:
        raise ValueError("Неизвестный тариф")
    current = max((s for s in subscriptions
                   if s.status == "active" and s.expires_at > now
                   and s.plan_type not in PAID_STACK_SKIP_PLANS),
                  key=lambda s: s.expires_at, default=None)
    new_devices = devices_for_plan(plan_type)
    expires = plan_expires_at(now, plan_type)
    purchased_days = (expires - now).total_seconds() / 86400
    remaining = Decimal(0)
    carried = Decimal(0)
    credit = Decimal(0)
    old_devices = None
    if current:
        if current.plan_type == "unlimited":
            raise ValueError("Бессрочную подписку продлевать не нужно")
        old_devices = devices_for_plan(current.plan_type)
        remaining = Decimal(str((current.expires_at - now).total_seconds())) / Decimal(86400)
        rate = getattr(current, "renewal_daily_rate", None)
        if rate is None:
            # Legacy rows only stored the last payment, even when time was stacked.
            # Price one purchased period, rather than spreading it over the stack.
            old_price = Decimal(str(current.amount_paid or prices.get(current.plan_type, (0,))[0]))
            old_days = Decimal(str((plan_expires_at(current.started_at, current.plan_type)
                                   - current.started_at).total_seconds())) / Decimal(86400)
            rate = old_price / old_days
        credit = remaining * Decimal(str(rate))
        if old_devices == new_devices:
            carried = remaining
            expires = plan_expires_at(current.expires_at, plan_type)
            purchased_days = (expires - current.expires_at).total_seconds() / 86400
        else:
            new_days = Decimal(str((expires - now).total_seconds())) / Decimal(86400)
            new_rate = Decimal(str(prices[plan_type][0])) / new_days
            if new_rate <= 0:
                raise ValueError("Стоимость нового тарифа должна быть больше нуля")
            carried = credit / new_rate
            expires += timedelta(seconds=int(carried * Decimal(86400)))
    days = Decimal(str((expires - now).total_seconds())) / Decimal(86400)
    daily_rate = (credit + Decimal(str(amount))) / days
    return RenewalQuote(plan_type, purchased_days, float(amount), expires, daily_rate, float(remaining), float(carried),
                        old_devices, new_devices)
