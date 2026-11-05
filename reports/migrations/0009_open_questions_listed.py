"""The twelve questions the coverage review of 2026-11-04 says only the authority can answer, written into the register
(docs/regulatory-reports.md, section 7) as open. Reversible: the reverse takes the rows with these numbers away."""
from django.db import migrations

QUESTIONS = [
    ('Q1', 'Mattilsynet', 'Sea-lice report: the amount of an active substance (virkestoff.mengde, coverage R03)',
     'In virkestoff.mengde, is the amount the amount of the product or of the active substance? What does styrke multiply?'),
    ('Q2', 'Mattilsynet', 'Sea-lice report: the type of a treatment (R04)',
     'Definitions of FORBEHANDLING, BADEBEHANDLING and ANNEN_BEHANDLING: is an injection ANNEN_BEHANDLING, is a medicated feed '
     'FORBEHANDLING?'),
    ('Q3', 'Mattilsynet', 'Smolt report: a unit emptied in the month, and two species in one tank (R07)',
     'Settefisk: what is the month-end count of a unit emptied during the month, and may one karId appear twice for two species?'),
    ('Q4', 'Mattilsynet', 'Cleaner-fish report: fish delivered out, and the feed (R10, R11)',
     'Rensefisk: where do fish delivered out of the company or sent to slaughter go (antallFlyttetUt or '
     'antallKanIkkeGjøresRedeFor)? Is the feed the cleaner-fish batches only, or all feed of the unit?'),
    ('Q5', 'Mattilsynet', 'Planned slaughter: who reports, and the kilo basis (R14)',
     'Is a farm accepted as the reporter of a planned slaughter, and is the kilo basis round or gutted weight? Does the weekday '
     'mean the slaughter day?'),
    ('Q6', 'Mattilsynet', 'Driftsplan and the lice coordination plan (R16, R17)',
     'Are the driftsplan and the lakselusforskriften § 4 plan filed only in Altinn 3, or also through the API? Is a late 2027-28 '
     'plan still accepted, and what is the consequence?'),
    ('Q7', 'Fiskeridirektoratet', 'Monthly biomass, yearly stock of a land site and the escape notice (R20, R21, R24)',
     'Are the monthly biomass report, the land yearly stock and the escape notice still filed through Altinn, or through an API '
     'only? Where is the escape form now?'),
    ('Q8', 'Mattilsynet', 'Cleaner-fish broodstock annual report (R29)',
     'The annual report on cleaner-fish broodstock (stamfisk): form, deadline and channel.'),
    ('Q9', 'Statsforvalteren', 'The county report of a land site with a discharge permit (R31)',
     'Does the Statsforvalter annual report apply to our permit and county, and by when?'),
    ('Q10', 'Fiskeridirektoratet', 'A land research site (R32)',
     'How is a land research site (annen produksjon, § 3 l) classified, and which duties follow?'),
    ('Q11', 'Mattilsynet', 'Sea-lice duty: which species (R33)',
     'Is Arctic char "laksefisk" for the lice duty (lakselusforskriften § 2)?'),
    ('Q12', 'Mattilsynet', 'Deadlines that fall on a weekend or a holiday, and the week-year (C10)',
     'Does the 7th, or the Tuesday, shift when it falls on a weekend or a holiday? Which year applies to a week that crosses 1 January?'),
]


def add(apps, schema_editor):
    OpenQuestion = apps.get_model('reports', 'OpenQuestion')
    for code, authority, affects, question in QUESTIONS:
        OpenQuestion.objects.create(code=code, authority=authority, affects=affects, question=question, status='open')


def remove(apps, schema_editor):
    apps.get_model('reports', 'OpenQuestion').objects.filter(code__in=[row[0] for row in QUESTIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0008_open_questions'),
    ]

    operations = [
        migrations.RunPython(add, remove),
    ]
