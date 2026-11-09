from django.urls import path

from core.crud import Mount, Resource, serve_mounted

from . import scope, views

app_name = 'hr'

# Production › Team: the same HR pages for the production people, under the Production panel's address. The tabs carry their
# own mounts (core.crud.Resource.mounts); the pages below are served under this one.
TEAM = Mount(scope.PRODUCTION, 'production/team')


def pages(root, mount=None):
    """The HR pages that are not a tab (Today, the roster's batch plan, the decisions on a leave request, the overview and the
    organisation chart) under `root`, served under `mount` and named with its key."""
    def route(address, view, name):
        return path(f'{root}{address}', serve_mounted(view, mount),
                    name=f'{mount.key}_{name}' if mount is not None else name)
    return [
        route('', views.today, 'today'),
        route('today/board/', views.today_board, 'today_board'),
        route('organization/', views.organisation_chart, 'orgchart'),
        route('overview/', views.team_overview, 'overview'),
        route('today/clock-<str:direction>/', views.punch, 'punch'),
        route('schedule/plan/', views.plan, 'roster_plan'),
        route('leave/<uuid:pk>/approve/', views.approve, 'leaverequest_approve'),
        route('leave/<uuid:pk>/reject/', views.reject, 'leaverequest_reject'),
        route('leave/<uuid:pk>/cancel/', views.cancel, 'leaverequest_cancel'),
        route('leave/<uuid:pk>/shorten/', views.shorten, 'leaverequest_shorten'),
    ]


# The tabs' routes come from the tabs (core.crud.Resource), with their mounts; the HR pages that are not a tab have routes
# of their own, in Company › HR and in Production › Team.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += pages('hr/') + pages(f'{TEAM.url_prefix}/', TEAM)
