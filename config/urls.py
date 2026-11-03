"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.forms import PasswordResetForm

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('production/', views.production_home, name='production_home'),
    # Reset links go to invited people too, who have no password yet (core.forms.PasswordResetForm).
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(form_class=PasswordResetForm),
         name='password_reset'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('farm.urls')),
    path('', include('knowledge.urls')),
    path('messages/', include('messaging.urls')),
    path('', include('inventory.urls')),
    path('', include('tasks.urls')),
    path('', include('experiments.urls')),
    path('', include('core.urls')),
    path('admin/', admin.site.urls),
]
