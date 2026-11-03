from django.urls import path

from core.crud import Resource

from . import views

app_name = 'tasks'

# The tabs' routes come from the tabs (core.crud.Resource): the tasks and the recurring tasks, their forms,
# deletes and checklists. What a person does to a task from its drawer has a route of its own, under the task.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('operations/tasks/<uuid:pk>/start/', views.start, name='task_start'),
    path('operations/tasks/<uuid:pk>/complete/', views.complete, name='task_complete'),
    path('operations/tasks/<uuid:pk>/cancel/', views.cancel, name='task_cancel'),
    path('operations/tasks/<uuid:pk>/reopen/', views.reopen, name='task_reopen'),
    path('operations/tasks/<uuid:pk>/checklist/<int:item>/', views.tick, name='task_tick'),
    path('operations/tasks/<uuid:pk>/notes/', views.add_note, name='task_note'),
]
