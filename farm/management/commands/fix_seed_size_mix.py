"""Separates batches of very different sizes that the development seed (seed-history-2026-11) stocked into the same sea
cages: Tromsø's TG-M01 and TG-M02 hold the grow-out salmon B-2026-004 (about 4.2 kg) beside the post-smolt B-2026-005
(about 590 g) and the smolt B-2026-007 (about 78 g), with the lumpfish B-2026-006. Afterwards the post-smolt and the
smolt each have a cage of their own on the same site, TG-M03 and TG-M04, like TG-M02, made through the units tab's own
form; TG-M01 holds the grow-out salmon and its lumpfish; TG-M02's lumpfish go with the post-smolt into TG-M03 (the owner,
2026-11-09: a cage of cleaner fish alone is not realistic), so TG-M02 is left empty (fallow).

How: the app's own transfers (farm/stock/services.py record_transfer, reason "growth stage"), dated on the farm's today,
one per batch and source cage, moving every fish of the batch there; the lumpfish move after the salmon they join,
reason "other" with the notes saying why (none of the reasons says "with the fish they clean"). Not dated back to the stocking: every later record of
those fish (their daily mortalities and weighings, the escape, the cage's production feedings, which also fed the
grow-out salmon) was booked in the old cages, and the stock refuses a transfer that would leave those records without
their fish; moving them would mean voiding about 300 records outside the backdating window and inventing how the
feedings split between cages. So the history stays as recorded, and from today each cage holds one size of salmon.

Only the seed's data: every batch it keeps or moves carries the seed's marker in its notes (seed-history-2026-11), and a
cage of the plan that is there already was made by this command (the marker in its notes); otherwise nothing is done.

Safe to run again: what was moved is not moved twice (a batch with no fish left in a source cage is skipped, a cage of the
plan that exists already is used when it is empty or holds the batch's own fish), and each transfer carries a
deterministic entry key. Everything is one transaction: a refusal (a handling warning not accepted, the withdrawal guard,
any stock rule) leaves the database as it was. The run checks the result (the cages, `check_stock` finding nothing new)
before it commits.

--dry-run only reads (in a read-only transaction): it prints the plan, the fish and weights, and what the run would ask.
The run itself needs the database migrated (the size check's columns), and refuses otherwise.
A development tool (core/management/devtool.py): with DEBUG off it runs only with --force.

    python manage.py fix_seed_size_mix --user admin --dry-run
    python manage.py fix_seed_size_mix --user admin"""
import uuid
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Sum
from django.http import QueryDict
from django.test import RequestFactory
from django.utils import translation

from core import audit
from core.management.devtool import DevCommand
from farm.handling import check
from farm.health.withdrawal import WithdrawalChanged
from farm.models import Batch, Site, StockMovement, Tank
from farm.models.handling import HandlingKind
from farm.models.stock import TransferReason
from farm.resources import TankResource
from farm.stock import integrity, read, services

MARK = 'seed-history-2026-11'
SOURCES = ('TG-M01', 'TG-M02')
KEEP = 'B-2026-004'
MOVES = (('B-2026-005', 'TG-M03', 'Cage 3'), ('B-2026-007', 'TG-M04', 'Cage 4'))
LIKE = 'TG-M02'
# Cleaner fish that go along (source cage, destination cage of MOVES), so no cage holds cleaner fish alone.
CLEANER_MOVES = (('TG-M02', 'TG-M03'),)
NS = uuid.UUID('0b8e7f62-3a4d-4c1e-9d3b-6a1f2e5c7d90')


@dataclass
class Leg:
    batch: object
    source: object
    destination_code: str
    fish: int
    avg_weight_g: object
    cleaner: bool = False         # cleaner fish going with the production fish they clean


@dataclass
class Plan:
    sources: list
    like: object
    keep: object
    moves: list                                   # [(batch, destination code, destination name)]
    legs: list = field(default_factory=list)
    new_units: list = field(default_factory=list)  # [(code, name)] to make like `like`
    existing: list = field(default_factory=list)   # the cages of the plan that are there already
    cleaner: list = field(default_factory=list)   # [(unit, batch)] left where they are


class Command(DevCommand):
    help = ('Development data: moves the post-smolt and the smolt that the seed history stocked beside the grow-out salmon '
            'in TG-M01 and TG-M02 into cages of their own (transfers dated today, one transaction, --dry-run reads only).')

    def add_arguments(self, parser):
        parser.add_argument('--user', required=True, help='The username the records are written as.')
        parser.add_argument('--dry-run', action='store_true', help='Print the plan and write nothing.')
        parser.add_argument('--accept-handling-warnings', action='store_true',
                            help='Go on past the handling check’s warnings (a fast too short), stored and logged '
                                 'as critical, as a person going on past them does.')
        parser.add_argument('--sources', default=','.join(SOURCES), help='The cages to separate, comma-separated.')
        parser.add_argument('--keep', default=KEEP, help='The production batch that stays in them.')
        parser.add_argument('--move', action='append', metavar='BATCH:UNIT:NAME',
                            help='A batch to move and the cage it goes to (made when missing); repeatable.')
        parser.add_argument('--like', default=LIKE, help='The cage a new cage copies its setup from.')
        parser.add_argument('--move-cleaner', action='append', metavar='SOURCE:DEST',
                            help='The cleaner fish of a source cage go along into a cage of the plan; repeatable; an '
                                 'empty value moves none.')

    def handle(self, *args, **options):
        with translation.override('en'):
            user = get_user_model().objects.filter(username=options['user'], is_active=True).first()
            if user is None:
                raise CommandError(f'No active user {options["user"]!r}.')
            moves = ([tuple(item.split(':', 2)) for item in options['move']] if options['move'] else list(MOVES))
            if any(len(move) != 3 or not all(move) for move in moves):
                raise CommandError('--move takes BATCH:UNIT:NAME.')
            sources = [code.strip() for code in options['sources'].split(',') if code.strip()]
            given = options['move_cleaner']
            cleaner_moves = ([tuple(item.split(':', 1)) for item in given if item] if given is not None
                             else list(CLEANER_MOVES))
            if any(len(move) != 2 or not all(move) for move in cleaner_moves):
                raise CommandError('--move-cleaner takes SOURCE:DEST.')
            pending = self.pending_migrations()
            if options['dry_run']:
                # Reads only: the database itself refuses a write in this transaction, which is rolled back at the end.
                # On a database without the opening balances' table (farm 0036) there are none: the stock is read
                # without them (farm.stock.read.OPENING_BALANCES).
                opening = read.OPENING_BALANCES.set('farm.0036_opening_balances' not in pending)
                try:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute('SET TRANSACTION READ ONLY')
                        plan = self.plan(sources, options['keep'], moves, options['like'], cleaner_moves)
                        self.show(plan, pending, user)
                        transaction.set_rollback(True)
                finally:
                    read.OPENING_BALANCES.reset(opening)
                return
            if pending:
                raise CommandError(f'Migrate first: {", ".join(pending)} not applied.')
            self.run(user, sources, options['keep'], moves, options['like'], cleaner_moves,
                     options['accept_handling_warnings'])

    # ---- reading ---------------------------------------------------------------------------------------------
    @staticmethod
    def pending_migrations():
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        return [f'{migration.app_label}.{migration.name}' for migration, backwards in plan if not backwards]

    def plan(self, source_codes, keep_code, moves, like_code, cleaner_moves=()):
        """What there is to do, read without a lock (the run reads it again under its locks): the salmon's legs, then
        the cleaner fish's that go along. Refuses when the data is not the seed's: another site, a batch neither kept
        nor moved nor cleaner fish, a cage of the plan holding other production fish, cleaner fish sent anywhere but
        into a cage of the plan."""
        destinations = {code for _batch, code, _name in moves}
        for source, destination in cleaner_moves:
            if source not in source_codes:
                raise CommandError(f'--move-cleaner {source}:{destination}: {source} is not one of the cages separated.')
            if destination not in destinations:
                raise CommandError(f'--move-cleaner {source}:{destination}: {destination} is not a cage the plan moves '
                                   'salmon into.')
        cleaner_to = dict(cleaner_moves)
        units = {unit.code: unit for unit in Tank.objects.select_related('production_department__site')
                 .filter(code__in=[*source_codes, like_code, *(code for _batch, code, _name in moves)])}
        missing = [code for code in [*source_codes, like_code] if code not in units]
        if missing:
            raise CommandError(f'No live unit {", ".join(missing)}.')
        sources = [units[code] for code in source_codes]
        like = units[like_code]
        site = like.production_department.site
        if site is None or site.type != Site.Type.SEA_CAGE or like.kind != Tank.Kind.CAGE:
            raise CommandError(f'{like.code} is not a cage on a sea site.')
        for unit in sources:
            if unit.production_department.site_id != site.pk:
                raise CommandError(f'{unit.code} is not on {site.code}.')
        batches = {batch.code: batch for batch in Batch.objects.filter(
            code__in=[keep_code, *(code for code, _unit, _name in moves)])}
        missing = [code for code in [keep_code, *(code for code, _unit, _name in moves)] if code not in batches]
        if missing:
            raise CommandError(f'No live batch {", ".join(missing)}.')
        keep = batches[keep_code]
        for batch in batches.values():
            self.marked(batch)
        cleaner_species = set(Batch.objects.filter(species__cleaner_fish_type__gt='').values_list('pk', flat=True))
        plan = Plan(sources, like, keep, [(batches[code], unit, name) for code, unit, name in moves])
        moved = {batches[code].pk: (unit, name) for code, unit, name in moves}
        present = (StockMovement.objects.filter(unit__in=sources, operation__is_deleted=False)
                   .values('unit_id', 'batch_id').annotate(fish=Sum('count_delta')).filter(fish__gt=0))
        by_pk = Batch.all_objects.in_bulk({row['batch_id'] for row in present})
        going = []                                  # the cleaner fish's legs, after every salmon leg
        for row in sorted(present, key=lambda row: (row['unit_id'], by_pk[row['batch_id']].code)):
            unit = next(unit for unit in sources if unit.pk == row['unit_id'])
            batch = by_pk[row['batch_id']]
            if batch.pk == keep.pk:
                continue
            if batch.pk in cleaner_species:
                if unit.code in cleaner_to:
                    self.marked(batch)
                    share = read.share_on(unit.pk, batch.pk, services.local_today(unit))
                    going.append(Leg(batch, unit, cleaner_to[unit.code], row['fish'], share.avg_weight_g, True))
                else:
                    plan.cleaner.append((unit, batch))
                continue
            if batch.pk not in moved:
                raise CommandError(f'{batch.code} in {unit.code} is neither kept, moved nor cleaner fish: the data is not '
                                   'the seed’s, nothing done.')
            share = read.share_on(unit.pk, batch.pk, services.local_today(unit))
            plan.legs.append(Leg(batch, unit, moved[batch.pk][0], row['fish'], share.avg_weight_g))
        plan.legs += going
        for batch, code, name in plan.moves:
            unit = units.get(code)
            if unit is None:
                if Tank.all_objects.filter(code=code).exists():
                    raise CommandError(f'{code} is deleted: restore it or choose another code.')
                plan.new_units.append((code, name))
                continue
            held = set(read.fish_of_batch(batch.pk)) & {unit.pk}
            others = (StockMovement.objects.filter(unit=unit, operation__is_deleted=False).exclude(batch=batch)
                      .exclude(batch_id__in=cleaner_species).values('batch_id').annotate(fish=Sum('count_delta')).filter(fish__gt=0))
            if others.exists() or unit.production_department.site_id != site.pk or unit.kind != Tank.Kind.CAGE:
                raise CommandError(f'{code} exists and is not an empty cage of {site.code} for {batch.code}'
                                   f'{" (it holds it already)" if held else ""}: nothing done.')
            if MARK not in unit.notes:
                raise CommandError(f'{code} was not made by fix_seed_size_mix (no {MARK} in its notes): nothing done.')
            plan.existing.append(unit)
        return plan

    @staticmethod
    def marked(batch):
        if MARK not in batch.notes:
            raise CommandError(f'{batch.code} does not carry the seed’s marker ({MARK}) in its notes: not the seed’s '
                               'data, nothing done.')

    def show(self, plan, pending, user):
        out = self.stdout.write
        out(f'Dry run, as {user.username}: nothing is written.')
        if pending:
            out(f'The database lacks {", ".join(pending)}: the run will refuse until it is migrated; the handling '
                'check is shown by the run.')
        for code, name in plan.new_units:
            like = plan.like
            out(f'Make {code} "{name}" like {like.code}: {like.get_kind_display()} in '
                f'{like.production_department.name}, {like.production_department.site.name}; '
                f'max {like.max_density_kg_m3} kg/m³, {like.max_biomass_kg} kg max biomass.')
        if not plan.legs:
            out('Nothing to move: the cages hold only the kept batch and the cleaner fish.')
        for leg in plan.legs:
            along = ', cleaner fish with the production fish they clean,' if leg.cleaner else ''
            out(f'Transfer {leg.fish} fish of {leg.batch.code} ({leg.avg_weight_g:.1f} g) from {leg.source.code} to '
                f'{leg.destination_code}{along} on {services.local_today(leg.source).isoformat()}.')
            if not pending:
                assessment = check.assess(HandlingKind.TRANSPORT, leg.source, services.local_today(leg.source),
                                          leg.batch, with_earliest=False)
                for text in assessment.messages():
                    out(f'  handling: {text}')
        for unit, batch in plan.cleaner:
            out(f'Leave the cleaner fish {batch.code} in {unit.code}.')
        out(f'Afterwards {", ".join(unit.code for unit in plan.sources)} hold {plan.keep.code} (where it is) and the '
            'cleaner fish left with it only.')

    # ---- writing ---------------------------------------------------------------------------------------------
    def run(self, user, source_codes, keep_code, moves, like_code, cleaner_moves, accept_warnings):
        before = integrity.problems()
        try:
            with transaction.atomic():
                plan = self.plan(source_codes, keep_code, moves, like_code, cleaner_moves)
                if not plan.legs:
                    self.stdout.write('Nothing to move: the cages hold only the kept batch and the cleaner fish.')
                    return
                # The lock order (core/softdelete.py): the fish first, batches then units (the sources and the cages
                # of the plan there already), before a new unit locks its department and site; the transfers then take
                # the same locks again (held) and the new units' (ours, which nobody else can see yet).
                services.lock_fish([unit.pk for unit in [*plan.sources, *plan.existing]])
                made = {code: self.make_unit(user, plan.like, code, name) for code, name in plan.new_units}
                units = {**{unit.code: unit for unit in Tank.objects.filter(
                    code__in=[code for _batch, code, _name in plan.moves])}, **made}
                for leg in self.plan(source_codes, keep_code, moves, like_code, cleaner_moves).legs:
                    self.transfer(user, leg, units[leg.destination_code], accept_warnings)
                self.verify(plan, before, cleaner_moves)
        except ValidationError as error:
            raise CommandError(f'Refused, nothing written: {"; ".join(error.messages)}') from None
        self.stdout.write(self.style.SUCCESS('Done: each cage holds one size of salmon (and its cleaner fish).'))

    def make_unit(self, user, like, code, name):
        """A cage like `like`, through the units tab's own form, logged and given its sampling points as a person's
        new unit is (core/crud.py CreateView)."""
        request = RequestFactory().get('/')
        request.user = user
        base = TankResource.form(request, instance=like)
        values = {name_: base[name_].value() for name_ in base.fields if name_ not in ('version',)}
        values.update(code=code, name=name, status=Tank.Status.PREPARING, status_reason='', regulatory_unit_id='',
                      installation_date='', description='', notes=f'{MARK}: a cage of its own for one size of salmon '
                                                               f'(fix_seed_size_mix).')
        data = QueryDict(mutable=True)
        for key, value in values.items():
            if value in (None, '', False):
                continue
            data[key] = 'on' if value is True else str(value)
        form = TankResource.form(request, data)
        if not form.is_valid():
            raise CommandError(f'{code}: the unit form refused it: {form.errors.as_json()}')
        unit = form.save(commit=False)
        unit.created_by = unit.updated_by = user
        unit.save()
        form.save_m2m()
        audit.record_create(user, unit, TankResource.recorded(unit), entity_type=TankResource.entity_type())
        TankResource.after_save(request, unit, created=True)
        self.stdout.write(f'Made {unit.code} "{unit.name}" ({unit.max_biomass_kg} kg max biomass).')
        return unit

    def transfer(self, user, leg, destination, accept_warnings):
        day = services.local_today(leg.source)
        assessment = check.assess(HandlingKind.TRANSPORT, leg.source, day, leg.batch, with_earliest=False)
        if assessment.warnings and not accept_warnings:
            raise CommandError(f'The handling check warns for {leg.batch.code} in {leg.source.code}: '
                               f'{" ".join(assessment.messages())} Run again with --accept-handling-warnings to go '
                               'on past it; nothing written.')
        token = uuid.uuid5(NS, f'{leg.batch.code}:{leg.source.code}:{destination.code}:{day.isoformat()}')
        if leg.cleaner:
            reason = TransferReason.OTHER
            notes = (f'{MARK}: cleaner fish {leg.batch.code} moved with the post-smolt they clean, so no cage holds '
                     f'cleaner fish alone (fix_seed_size_mix).')
        else:
            reason = TransferReason.GROWTH_STAGE
            notes = (f'{MARK}: {leg.batch.code} moved to a cage of its own, away from the grow-out salmon of another '
                     f'size (fix_seed_size_mix).')
        try:
            services.record_transfer(
                user, source=leg.source, batch=leg.batch, day=day, legs=[(destination, leg.fish)], reason=reason,
                token=token, handling_ack=assessment.fingerprint if assessment.warnings else None, notes=notes)
        except services.AlreadyRecorded:
            return
        except WithdrawalChanged as error:
            raise CommandError(f'The withdrawal guard asks about moving {leg.batch.code}: {" ".join(error.messages)} '
                               'Nothing written.') from None
        self.stdout.write(f'Moved {leg.fish} fish of {leg.batch.code} from {leg.source.code} to {destination.code}.')

    def verify(self, plan, before, cleaner_moves=()):
        """The end state, checked before the commit: the cages hold the kept batch and cleaner fish only, each moved
        batch is in its own cage only, a source whose cleaner fish went along holds none, and check_stock finds nothing
        it did not find before."""
        stock = read.stock_of(plan.sources)
        for unit in plan.sources:
            held = {share.batch.pk for share in stock[unit.pk].shares if not share.cleaner} if unit.pk in stock else set()
            if held - {plan.keep.pk}:
                raise CommandError(f'{unit.code} still holds other production fish: rolled back.')
        for batch, code, _name in plan.moves:
            where = {Tank.objects.get(pk=pk).code for pk in read.fish_of_batch(batch.pk)}
            if where - {code}:
                raise CommandError(f'{batch.code} is still in {", ".join(sorted(where - {code}))}: rolled back.')
        cleaner_from = {source for source, _destination in cleaner_moves}
        for unit in plan.sources:
            if unit.code in cleaner_from and unit.pk in stock and stock[unit.pk].cleaner:
                raise CommandError(f'{unit.code} still holds cleaner fish: rolled back.')
        new = [problem for problem in integrity.problems() if problem not in before]
        if new:
            raise CommandError('check_stock would find: ' + ' '.join(new) + ' Rolled back.')
