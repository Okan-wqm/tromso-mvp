from django.urls import path

from . import views

app_name = 'farm'

urlpatterns = [
    path('sites/', views.site_list, name='site_list'),
    path('sites/new/', views.site_create, name='site_create'),
    path('sites/<uuid:pk>/', views.site_edit, name='site_edit'),
    path('sites/<uuid:pk>/contacts/', views.site_contacts, name='site_contacts'),
    path('sites/<uuid:pk>/delete/', views.site_delete, name='site_delete'),
]
