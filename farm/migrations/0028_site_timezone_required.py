# Every site has its time zone: a site without one ran on the server's UTC unseen, its plans and punches an hour or two off.
# Each such site is given the company's zone (settings.COMPANY_TIME_ZONE, Europe/Oslo unless the environment names
# another; never the server's UTC unless the company's is UTC), stored and shown on the site's form; the database then
# refuses an empty one. A company zone that is not a zone a site may have is refused, never written. Going back leaves the
# zones as they are.

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import migrations, models

import farm.models.site


# The zones a site may be given when this migration was written (Site.TIMEZONES then), frozen here: a migration never
# reads live code, so a zone added to the model later does not change what this one accepts.
ZONES = ('UTC', 'Europe/Oslo', 'Europe/Istanbul', 'Europe/London', 'America/New_York', 'Asia/Tokyo')


def zone_problem(zone):
    """Why `zone` cannot be written into the sites, or None (the server's start says the same: farm.E001)."""
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return f'COMPANY_TIME_ZONE {zone!r} is not a known time zone.'
    if zone not in ZONES:
        return f'COMPANY_TIME_ZONE {zone!r} is not one a site may be given ({", ".join(ZONES)}).'
    return None


def give_the_companys_zone(apps, schema_editor):
    problem = zone_problem(settings.COMPANY_TIME_ZONE)
    if problem is not None:
        raise ValueError(problem)
    apps.get_model('farm', 'Site')._base_manager.filter(timezone='').update(timezone=settings.COMPANY_TIME_ZONE)


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0027_withdrawal_acknowledgements'),
    ]

    operations = [
        migrations.RunPython(give_the_companys_zone, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='site',
            name='timezone',
            field=models.CharField(choices=[('UTC', 'UTC'), ('Europe/Oslo', 'Europe/Oslo (CET)'), ('Europe/Istanbul', 'Europe/Istanbul (TRT)'), ('Europe/London', 'Europe/London (GMT)'), ('America/New_York', 'America/New York (EST)'), ('Asia/Tokyo', 'Asia/Tokyo (JST)')], default=farm.models.site.company_zone, max_length=50, verbose_name='Timezone'),
        ),
        migrations.AddConstraint(
            model_name='site',
            constraint=models.CheckConstraint(condition=models.Q(('timezone', ''), _negated=True), name='chk_sites_timezone_given'),
        ),
    ]
