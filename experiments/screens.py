"""What the data map (core.datamap) cannot read from the code, for the experiment tables. The Experiments tab (its form, its
team list and its read page) comes from the code. What a person does to the rest is done through dialogs that write through
the experiment services, each logged on the experiment: the Design tab saves the factors, levels, groups, group levels and
replicates as one design; the Places tab saves the placements; Start, Release and Replace change the experiment and its
placements while it runs. None of those rows is a tab of its own, and a started design is never edited (the database
refuses it: migration 0002), so what is absent is said as absent on purpose."""
from core.datamap import Screen, computed, system

from .forms import FactorRowForm, GroupRowForm, PlaceRowForm

DESIGN = 'experiments:experiment_design'
PLACES = 'experiments:experiment_places'
DETAIL = 'experiments:experiment_detail'
DESIGN_NOTE = ('Saved with the experiment\'s design on the Design tab (services.save_design), logged as one "Design" entry '
               'of the experiment; a row the design no longer has is deleted with the delete plan, and a started design '
               'cannot change.')
LEVELS = {'experiment': system('the experiment the design belongs to'),
          'position': system('the order the rows have on the Design tab')}

SCREENS = {
    'Experiment': Screen(
        extra_fields={},
        columns={'is_template': system('set by Save as a template (the copy dialog), never typed'),
                 'status': system('moved by Start (draft to running) and by closing; the database allows only that order'),
                 'allocation_method': system('set by the Places tab: randomised with a seed, or placed by hand with a reason'),
                 'allocation_seed': system('the seed of a randomised deal, written by the Places tab'),
                 'allocation_note': system('the reason a placement by hand was made, written by the Places tab'),
                 'copied_from': system('the experiment a copy was made from, written by the Copy dialog')},
        note='A started experiment keeps every column but its status, name and notes (trg_experiments_frozen).',
    ),
    'Factor': Screen(
        create=(DESIGN,), edit=(DESIGN,), delete=(DESIGN,), read=(DETAIL, DESIGN), forms=(FactorRowForm,),
        columns=LEVELS,
        note=DESIGN_NOTE),
    'Level': Screen(
        create=(DESIGN,), edit=(DESIGN,), delete=(DESIGN,), read=(DETAIL, DESIGN), forms=(GroupRowForm,),
        columns={'factor': system('the factor the level is of'),
                 'label': computed('the cell typed in the group\'s row for another factor'),
                 'protocol': computed('the protocol chosen in the group\'s row for the diet'),
                 'value': computed('the number typed in the group\'s row with its label')},
        note='A level is made from the cells of the group rows: one per distinct protocol or label. ' + DESIGN_NOTE),
    'ExperimentGroup': Screen(
        create=(DESIGN,), edit=(DESIGN,), delete=(DESIGN,), read=(DETAIL, DESIGN), forms=(GroupRowForm,),
        columns=LEVELS,
        note=DESIGN_NOTE),
    'GroupLevel': Screen(
        create=(DESIGN,), edit=(DESIGN,), delete=(DESIGN,), read=(DETAIL, DESIGN),
        columns={name: computed('rebuilt from the cells of the group\'s row when the design is saved')
                 for name in ('experiment', 'group', 'factor', 'level')},
        note=DESIGN_NOTE),
    'Replicate': Screen(
        create=(DESIGN,), edit=(DESIGN,), delete=(DESIGN,), read=(DETAIL, DESIGN),
        columns={'group': computed('the group whose replicates count is typed'),
                 'number': computed('numbered within the group when the replicates count changes; never renumbered')},
        note='One slot for each of the group\'s replicates; a slot holding tanks is never removed. ' + DESIGN_NOTE),
    'ReplicateUnit': Screen(
        create=(PLACES, 'experiments:experiment_replace'), edit=(PLACES, 'experiments:experiment_release'),
        delete=(PLACES,), read=(DETAIL, 'experiments:experiment_detail'), forms=(PlaceRowForm,),
        columns={name: computed('written by the Places tab from the tanks and days of the replicate\'s row')
                 for name in ('unit', 'from_on', 'until_on')} | {
                 'left_reason': system('typed in the Release or Replace dialog')},
        note='A draft\'s placements are saved on the Places tab (services.save_places, randomise); a running one only gets '
             'shorter (Release) or a replacement (Replace), and is never deleted.'),
}
