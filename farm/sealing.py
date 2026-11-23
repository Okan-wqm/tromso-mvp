"""How the farm's records are sealed (core.sealing): a record on a sealed cell, dated inside it, does not exist for someone
the cell's owner has not granted. Declared once here, read by the managers. Farm records are facts (an `oversee`
holder sees them); the unit and the system themselves are sealed only while today is inside a cell, so a booking for next
month never hides the fish a technician feeds today."""
from core.sealing import EXEMPT, declare


def declare_all():
    from . import models as m

    # The places themselves, while today is inside a cell.
    declare(m.Tank, part='systems', unit='pk')
    declare(m.System, part='systems', system='pk')
    declare(m.EquipmentSystem, part='systems', system='system')
    declare(m.SamplingPoint, part='water', unit='unit', system='system')
    declare(m.Equipment, mode=EXEMPT, reason='A piece of equipment is plant shared by systems (a pump, a feeder); its '
                                             'links to a sealed system are sealed (EquipmentSystem), its readings by '
                                             'their channel bindings.')
    declare(m.FeederCalibration, mode=EXEMPT, reason='A feeder\'s calibration belongs to the equipment, not to a cell.')

    # The stock: each line on its unit and day; an operation, a batch shown while one of its lines is.
    declare(m.StockMovement, unit='unit', day='operation__date')
    declare(m.StockOperation, any_of=('farm.StockMovement', 'operation'))
    declare(m.Batch, any_of=('farm.StockMovement', 'batch'))
    declare(m.EscapeRecord, via=('operation',))
    declare(m.DeliveryRecord, via=('operation',))
    declare(m.HarvestRecord, via=('operation',))
    declare(m.OpeningBalance, via=('operation',))
    declare(m.WithdrawalAcknowledgement, via=('batch', 'harvest'))
    declare(m.HandlingAcknowledgement, via=('operation', 'treatment'))
    declare(m.ProductionPlan, via=('batch',))
    declare(m.HandlingPlanItem, unit='unit', day='date', via=('destination_unit', 'batch', 'operation'))

    # Feeding, health, water.
    declare(m.FeedingRecord, unit='unit', day='date')
    declare(m.ProtocolAssignment, unit='unit', day=('valid_from', 'valid_until'), via=('batch',))
    declare(m.Treatment, unit='units', day=('start_date', 'end_date'))
    declare(m.HealthEvent, unit='units', day='date')
    declare(m.LiceCount, unit='unit', day='date')
    declare(m.WaterMeasurement, part='water', unit='point__unit', system='point__system', day='measured_at')
