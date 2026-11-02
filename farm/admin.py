from django.contrib import admin

from .models import Site, SiteContact


class SiteContactInline(admin.TabularInline):
    model = SiteContact
    extra = 0


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'type', 'status', 'country', 'region', 'is_deleted']
    list_filter = ['type', 'status', 'is_deleted']
    search_fields = ['name', 'code', 'region']
    inlines = [SiteContactInline]

    def get_queryset(self, request):
        return Site.all_objects.all()
