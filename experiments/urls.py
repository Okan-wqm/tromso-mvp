from core.crud import Resource

app_name = 'experiments'

# The tab's routes come from the tab (core.crud.Resource): the list, create, edit, delete, the team and the read page.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
