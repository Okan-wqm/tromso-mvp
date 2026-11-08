"""What the data map (core.datamap) cannot read from the code, for the farm tables that are not tabs: the dialogs that
write them through the stock, feeding, water and health services, and the pages that show them. A tab, a row list a
tab saves and a many-to-many link of a tab's form come from the code and need nothing here, unless something about
them is not in the code (a column no form has, a form field that is not a column)."""
from core.datamap import Screen, computed, dynamic, gap, no, system

from .feeding import views as feeding
from .forms import stock as stock_forms
from .forms.feeding_protocol import BandRowForm, ProtocolTableForm
from .forms.health import LastDayForm
from .forms.water import MEASURED, RoundForm, RoundRowForm, SampleVoidForm, WaterSampleForm
from .harvest import views as harvest
from .health import views as health
from .resources.feeding_protocol import FeedingProtocolResource
from .stock import views as stock
from .water import views as water

TOKEN = "the form's one-time token: the same form sent twice records once"
VOIDED = system('the reason typed in the void dialog')
LEDGER = 'a ledger is never edited: a mistake is voided and recorded again'
PROTOCOL_TABLE = 'farm:feedingprotocol_table'

# The dialogs of the stock: each is a form of its own, and the stock service writes the operation and its lines.
STOCK_DIALOGS = (stock_forms.MortalityForm, stock_forms.CullForm, stock_forms.WeighingForm, stock_forms.TransferForm,
                 stock_forms.LegForm, stock_forms.GradingForm, stock_forms.OutputForm, stock_forms.HarvestForm,
                 stock_forms.DeliveryForm, stock_forms.EscapeForm, stock_forms.InputLineForm)
STOCK_WRITE = (stock.stock_input, stock.record_operation)

SCREENS = {
    # --- tabs with something the code does not say ---
    'Equipment': Screen(
        columns={'specifications': dynamic('the fields of the chosen equipment type, on the Technical specifications '
                                           'tab (core.schema)')},
        extra_fields={'category': 'narrows the list of types; it is not stored'},
    ),
    'Site': Screen(columns={name: gap('no field on the Site form') for name in (
        'is_active', 'water_capacity_m3', 'max_biomass_kg', 'established_date', 'facilities', 'settings', 'notes',
        'metadata')}),
    'ProductionDepartment': Screen(columns={name: gap('no field on the Production department form')
                                            for name in ('status', 'description')}),
    'Tank': Screen(extra_fields={'freeboard': 'shown, never typed: calculated from the dimensions'}),
    'SamplingPoint': Screen(extra_fields={'owner_type': 'says which of unit, system or equipment owns the point'}),
    'HandlingRule': Screen(extra_fields={
        'fasting_amount': 'typed with its unit and stored as hours (min_fasting_hours)',
        'fasting_unit': 'typed with the amount and stored as hours (min_fasting_hours)'}),
    'ProtocolAssignment': Screen(extra_fields={'units': 'a row is written for each unit chosen (the unit column)'}),
    'HealthEvent': Screen(
        delete=(health.void_event,),
        note='A health event is voided with a reason, not deleted.',
        columns={'void_reason': VOIDED},
    ),

    # --- reference data ---
    'EquipmentType': Screen(
        create=no('reference data: written by migrations from farm/equipment_types.py, as the source has no screen '
                  'for it'),
        edit=no('reference data written by migrations'),
        delete=no('reference data written by migrations; a type no longer offered is made inactive'),
        read=gap('no page lists the equipment catalogue: a type only shows as the choice on the Equipment form'),
        note="The Equipment form offers the active types and shows the chosen type's specification fields.",
        columns={'*': system("reference data from the migrations; the form shows the type's name and its fields")},
    ),

    # --- the stock: one write path (farm/stock/services.py), shown on Production units ---
    'Batch': Screen(
        create=(stock.stock_input,),
        edit=(stock.batch_details,),
        delete=(stock.void_operation,),
        read=(stock.production_units, harvest.harvests),
        note='Voiding a stocking voids its batch. Only the year class and the provenance can be corrected afterwards.',
        extra_fields={'token': TOKEN, 'count': 'the fish stocked: a line of the stocking operation',
                      'avg_weight_g': 'the average weight stocked: a line of the stocking operation',
                      'over_capacity_ack': "the person's acknowledgement of a unit over capacity: stored on the "
                                           'stocking operation'},
    ),
    'StockOperation': Screen(
        create=STOCK_WRITE,
        edit=no(LEDGER),
        delete=(stock.void_operation,),
        read=(stock.production_units, harvest.harvests),
        forms=STOCK_DIALOGS + (stock_forms.VoidForm,),
        fills={'VoidForm.reason': 'void_reason'},
        columns={'kind': computed('which dialog was used: stocking, mortality, cull, weighing, transfer, grading, '
                                  'harvest, delivery or escape')},
    ),
    'StockMovement': Screen(
        part_of='farm.StockOperation',
        read=(stock.production_units, harvest.harvests),
        forms=STOCK_DIALOGS,
        fills={'count': 'count_delta'},
        columns={
            'operation': system('the operation the line belongs to'),
            'kind': computed('the kind of operation the line is part of'),
            'pair': system('ties the out line and the in line of a transfer'),
        },
    ),
    'EscapeRecord': Screen(part_of='farm.StockOperation', create=('farm:stock_escape',),
                           read=(stock.production_units,), forms=(stock_forms.EscapeForm,)),
    'DeliveryRecord': Screen(part_of='farm.StockOperation', create=('farm:stock_delivery',),
                             read=(stock.production_units,), forms=(stock_forms.DeliveryForm,)),
    'HarvestRecord': Screen(part_of='farm.StockOperation', create=('farm:stock_harvest',),
                            read=(stock.production_units, harvest.harvests), forms=(stock_forms.HarvestForm,)),
    'HandlingAcknowledgement': Screen(
        create=('farm:stock_harvest', 'farm:stock_transfer', 'farm:stock_grading', 'farm:treatment_record'),
        edit=no('never edited: what the person was shown stays as it was'),
        delete=no('voiding the operation or the treatment leaves them as history'),
        read=(stock.production_units, harvest.harvests, health.treatments),
        note='One row for each warning the person went on past, written with the operation or the treatment it was '
             'given for. The pages show that a warning was acknowledged (its kind in a tooltip on Harvested), not the '
             'values it kept.',
        columns={'*': computed('what the person was shown when they acknowledged the warning: the handling check '
                               '(farm/handling/check.py) works it out and the service stores it')},
    ),
    'WithdrawalAcknowledgement': Screen(
        create=('farm:treatment_record', 'farm:treatment_last_day', 'farm:treatment_void', 'farm:feeding_record',
                'farm:feeding_void', 'farm:water_record', 'farm:water_round', 'farm:water_void', 'farm:stock_harvest',
                'farm:stock_transfer', 'farm:stock_void', 'farm:medicine_withdrawals'),
        edit=no('append-only (a database trigger): what the person went on past stays as it was'),
        delete=no('append-only (a database trigger): voiding the write leaves them as history'),
        read=gap('no page lists them yet: check_withdrawal reads them, and the write\'s critical log entry says what was '
                 'acknowledged'),
        note='One row for each warning of the withdrawal guard (farm.health.withdrawal.guarded) the person went on past: '
             'a harvest already recorded brought inside a withdrawal, or fish held today freed by the write.',
        columns={'*': computed('what the withdrawal guard found and the person was shown, stored when they went on')},
    ),

    # --- feeding ---
    'FeedingRecord': Screen(
        create=(feeding.record_feeding,),
        edit=no(LEDGER),
        delete=(feeding.void_feeding,),
        read=(feeding.feeding_records, feeding.meal_board, stock.production_units),
        extra_fields={'token': TOKEN},
        columns={'void_reason': VOIDED, 'unit': system('the unit whose drawer or list row opened the dialog')},
    ),
    'ProtocolBand': Screen(
        part_of='farm.FeedingProtocol',
        create=(PROTOCOL_TABLE,), edit=(PROTOCOL_TABLE,), delete=(PROTOCOL_TABLE,),
        read=(FeedingProtocolResource,),
        note="The feeding table is a grid on the protocol's Feeding table tab, saved as a whole.",
        forms=(BandRowForm,),
        columns={'protocol': system('the protocol whose table it is')},
    ),
    'ProtocolRate': Screen(
        part_of='farm.FeedingProtocol',
        create=(PROTOCOL_TABLE,), edit=(PROTOCOL_TABLE,), delete=(PROTOCOL_TABLE,),
        read=(FeedingProtocolResource,),
        forms=(ProtocolTableForm,),
        fills={'temperatures': 'temperature_c'},
        columns={'band': system('the band the cell belongs to'),
                 'sfr_pct': dynamic('one cell for each band and temperature column of the grid')},
    ),

    # --- water ---
    'WaterMeasurement': Screen(
        create=(water.record_sample, water.record_round),
        edit=no('a sample is voided and recorded again'),
        delete=(water.void_sample,),
        read=(water.water_page, stock.production_units),
        forms=(WaterSampleForm, RoundForm, RoundRowForm, SampleVoidForm),
        fills={'SampleVoidForm.reason': 'void_reason'},
        columns={parameter.code: dynamic('one field for each water parameter (farm.forms.water.MEASURED)')
                 for parameter in MEASURED},
    ),

    # --- health ---
    'Treatment': Screen(
        create=(health.record_treatment,),
        edit=(health.change_last_day,),
        delete=(health.void_treatment,),
        read=(health.treatments, stock.production_units),
        note='Only the last day of a course can be changed; anything else is a void and a new treatment.',
        forms=(LastDayForm,),
        extra_fields={'token': TOKEN},
        columns={'void_reason': VOIDED},
    ),
    'Treatment_units': Screen(
        edit=no('the units are chosen when the treatment is recorded; only its last day can be changed'),
        delete=no('the rows stay with the treatment, voided with it'),
        read=(health.treatments,),
    ),
    'LiceCount': Screen(
        create=(health.record_lice_count,),
        edit=no('a correction is a void and a new count, never an overwrite (HLT-19)'),
        delete=(health.void_lice_count,),
        read=(health.lice_counts, stock.production_units),
        extra_fields={'token': TOKEN},
        columns={'void_reason': VOIDED},
    ),
}
