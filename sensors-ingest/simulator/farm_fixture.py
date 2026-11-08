"""Tanks and systems for the farm check's OWN test database (never the dev database): a site, a hall, two
recirculation systems and 38 tanks with their sampling points, made with the farm tests' own helpers. The demo sensor
configuration on top of them is made by Django itself (manage.py sensors_demo_setup), not here.
Run inside the Django image: python manage.py shell -c "exec(open('sensors-ingest/simulator/farm_fixture.py').read())"
"""
from farm.models import ProductionDepartment, Site, System, Tank
from farm.tests.helpers import point_of
from farm.tests.test_stock import make_unit

site, _ = Site.objects.get_or_create(code='FARMCHECK', defaults={'name': 'Farm check'})
hall, _ = ProductionDepartment.objects.get_or_create(site=site, code='FC', defaults={'name': 'Farm check hall'})
systems = []
for code in ('R1', 'R2'):
    system = System.objects.filter(code=code, site=site).first() or System.objects.create(
        name=f'RAS {code}', code=code, site=site, production_department=hall)
    point_of(system)
    systems.append(system)
for number in range(1, 39):
    code = f'T-{number:02d}'
    tank = Tank.objects.filter(code=code, production_department=hall).first() or make_unit(
        code, hall, system=systems[number % 2])
    point_of(tank)
print('farm fixture: %d systems, %d tanks' % (len(systems), Tank.objects.filter(production_department=hall).count()))
