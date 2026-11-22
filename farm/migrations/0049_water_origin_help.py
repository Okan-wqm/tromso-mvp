# The unit's water-origin help text says that fresh water with sea water or a sea-salt mix added is diluted sea water
# (the salt-added water audit of 2026-11-20, question 1). Text only: no column, constraint or row changes.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0048_withdrawal_acknowledgement_delivered'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tank',
            name='water_origin',
            field=models.CharField(blank=True, choices=[('seawater', 'Sea water or diluted sea water'), ('salt_added', 'Fresh water with salt added')], default='', help_text='Where the salt in its water comes from. Fresh water with salt added (NaCl, for smolt or against disease) is worked out without sea water’s ions; fresh water with sea water or a sea-salt mix added is diluted sea water. Not said, a salinity of 1 to 5 ‰ is taken as diluted sea water.', max_length=12, verbose_name='Water origin'),
        ),
    ]
