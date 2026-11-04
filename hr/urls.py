from core.crud import Resource

app_name = 'hr'

# The tabs' routes come from the tabs (core.crud.Resource); the HR pages that are not a tab (Today, the roster, the
# organisation chart) have routes of their own below.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
