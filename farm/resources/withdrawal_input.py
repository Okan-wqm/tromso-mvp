"""A tab whose records are facts a medicine withdrawal is worked out from (a feed's type, a species' assumed water
temperature, a unit's loop, a sampling point): its edit goes through the withdrawal guard over the fish the record
reaches, which are locked before the record is (the order a stock operation and a water sample lock them in), and the
edit page asks what the change does to their withdrawals before it is saved."""
from ..health import withdrawal


class WithdrawalInput:
    question_template, question_field = 'farm/_withdrawal_change.html', withdrawal.FIELD

    @classmethod
    def reached(cls, request, record):
        """(the ids of the units whose fish the edit of `record` can reach, the first day it reaches them or None for
        every fish they ever held)."""
        raise NotImplementedError

    @classmethod
    def edited(cls, request, record, write, seen):
        unit_ids, first = cls.reached(request, record)
        return withdrawal.guarded_units(request.user, unit_ids, first, write, seen)
