from django.urls import path

from . import views

app_name = 'messaging'

# Everything under /messages/, the menu entry's address, so the menu marks Messages and the Production panel
# stays chosen while a dialog is open as a page.
urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('list/', views.inbox_list, name='inbox_list'),
    path('unread/', views.unread, name='unread'),
    path('new/', views.start, name='start'),
    path('new-channel/', views.create_channel, name='create_channel'),
    path('<uuid:pk>/', views.conversation, name='conversation'),
    path('<uuid:pk>/post/', views.post, name='post'),
    path('<uuid:pk>/new/', views.poll, name='poll'),
    path('<uuid:pk>/members/', views.members, name='members'),
    path('<uuid:pk>/members/add/', views.add_members, name='add_members'),
    path('<uuid:pk>/members/<uuid:participant>/remove/', views.remove_member, name='remove_member'),
    path('<uuid:pk>/members/<uuid:participant>/role/', views.set_role, name='set_role'),
    path('<uuid:pk>/leave/', views.leave, name='leave'),
    path('<uuid:pk>/messages/<int:message>/delete/', views.delete_message, name='delete_message'),
]
