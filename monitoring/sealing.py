"""How the monitoring rows are sealed (core.sealing): a board's row and a card template rule for a sealed unit or system
are absent while today is inside its cell, so a wall shows no card of it to someone not granted."""
from core.sealing import declare


def declare_all():
    from . import models as m
    declare(m.MonitorBoardUnit, unit='unit')
    declare(m.CardTemplateAssignment, unit='unit', system='system')
