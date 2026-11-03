from django.urls import path

from core.crud import Resource

from . import views

app_name = 'knowledge'

# The tabs' routes come from the tabs (core.crud.Resource): their list, form, read and delete pages. A document's
# file and text, and an entry's review, sit under their tab's address so the menu marks them.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('knowledge/library/<uuid:pk>/file/', views.document_file, name='document_file'),
    path('knowledge/library/<uuid:pk>/text/', views.document_text, name='document_text'),
    path('knowledge/entries/<uuid:pk>/review/', views.review_entry, name='entry_review'),
]
