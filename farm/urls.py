from django.urls import path

from . import views
from .resources import SiteResource

app_name = 'farm'

urlpatterns = [
    *SiteResource.urls(),
    path('sites/<uuid:pk>/contacts/', views.site_contacts, name='site_contacts'),
]
