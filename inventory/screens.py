"""What the data map (core.datamap) cannot read from the code, for the store's tables: the dialogs of Operations ›
Storage write them through the services, and its page and the item and lot pages show them. The reorder levels are a
row list of the Storage locations tab and come from the code."""
from core.datamap import Screen, computed, no, system
from farm.forms.stock import VoidForm

from . import forms, views

LEDGER = 'a ledger is never edited: a mistake is voided and recorded again'
DIALOGS = (views.receive, views.departure, views.count)
READ = (views.storage, views.item_page, views.lot_page)

SCREENS = {
    'ReorderLevel': Screen(fills={'feed': 'item'}),
    'InventoryItem': Screen(
        create=(views.receive, 'inventory:storagelocation_reorder'),
        edit=no('an item is its link to a feed and its unit: made the first time the feed is stored, never edited'),
        delete=no('an item stays: its lots, lines and reorder levels point at it'),
        read=(views.storage, views.item_page),
        note='The person never picks an item, they pick a feed: a delivery or a reorder level makes the feed\'s item '
             'when it has none.',
        forms=(forms.ReceiptLineForm, forms.FoundLotForm),
        columns={'unit': computed('kilograms: the store keeps feed by the kilo')},
    ),
    'InventoryLot': Screen(
        create=(views.receive, views.count),
        edit=no(LEDGER),
        delete=(views.void,),
        read=(views.storage, views.lot_page),
        note='A lot is made by the delivery (or the count) that first names it; one left without live lines is voided '
             'with them.',
        forms=(forms.ReceiptLineForm, forms.FoundLotForm),
        fills={'feed': 'item', 'lot_number': 'number'},
    ),
    'InventoryOperation': Screen(
        create=DIALOGS,
        edit=no(LEDGER),
        delete=(views.void,),
        read=(views.storage, views.item_page, views.lot_page),
        forms=(forms.ReceiptForm, forms.IssueForm, forms.WriteOffForm, forms.ReturnForm, forms.TransferForm,
               forms.CountForm, VoidForm),
        fills={'VoidForm.reason': 'void_reason'},
        columns={'kind': computed('which dialog was used: delivery, issue, write-off, return, transfer or count')},
    ),
    'InventoryLine': Screen(
        part_of='inventory.InventoryOperation',
        read=READ,
        forms=(forms.ReceiptLineForm, forms.IssueForm, forms.WriteOffForm, forms.ReturnForm, forms.TransferForm,
               forms.CountLineForm, forms.FoundLotForm),
        fills={'source': ('lot', 'location'), 'destination': 'location'},
        columns={
            'operation': system('the operation the line belongs to'),
            'kind': computed('the kind of line the operation writes: delivered, taken out, moved or counted'),
            'pair': system('ties the out line and the in line of a transfer'),
        },
    ),
}
