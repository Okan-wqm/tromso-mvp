from core.crud import Resource

app_name = 'farm'

# Every route comes from a tab (core.crud.Resource): its list, form and delete pages and its row lists.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
