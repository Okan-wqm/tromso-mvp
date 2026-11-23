"""The regulatory reports are exempt from the seal (core.sealing): a report counts every unit (a legal figure is never
partial), is computed as the system and frozen when filed, and carries no experiment. Who may open one is the ordinary
right to read reports, which the platform admin gives or withholds (owner amendment C1)."""
from core.sealing import EXEMPT, declare

REASON = ('A regulatory report counts every unit and is opened by the right to read reports, which the platform admin '
          'grants (owner amendment C1).')


def declare_all():
    from . import models as m
    for model in (m.Report, m.ReportSnapshot, m.UnitAnswer, m.TreatmentAnswer, m.ResistanceSuspicion,
                  m.SensitivityTest):
        declare(model, mode=EXEMPT, reason=REASON)
