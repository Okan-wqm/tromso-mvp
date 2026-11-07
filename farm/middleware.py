"""The box of the withdrawal guard (farm.health.withdrawal.guarded) travels with every POST as `withdrawal_ack`: the
middleware hands its value to the guard for the request, so every write path that changes a withdrawal reads the one
box the same way, whatever its form."""
from .health import withdrawal


class WithdrawalAcknowledgementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        seen = request.POST.get(withdrawal.FIELD, '') if request.method == 'POST' else ''
        with withdrawal.acknowledging(seen):
            return self.get_response(request)
