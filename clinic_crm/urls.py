from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from ninja import NinjaAPI

from leads.api import router as clinics_router

api = NinjaAPI(
    title="Clinic CRM",
    version="0.1.0",
    description="Lead-generation API for GP and aesthetic clinics.",
)
api.add_router("/clinics", clinics_router)


def favicon(_request):
    return HttpResponse(status=204)


urlpatterns = [
    path("favicon.ico", favicon),
    path("", include("leads.urls")),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
