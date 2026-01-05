from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('sst/', views.sst_list, name='sst_list'),
    path('sst/cargar-excel/', views.cargar_excel_suministros, name='cargar_excel_suministros'),
    path('suministros/', views.suministro_list, name='suministro_list'),
    path('suministros/<int:suministro_id>/actualizar/', views.actualizar_suministro, name='actualizar_suministro'),
    path('suministro/agregar-adicional/', views.agregar_suministro_adicional, name='agregar_suministro_adicional'),
    path('sst/<int:sst_id>/info/', views.obtener_info_sst, name='obtener_info_sst'),
    path('suministros/<int:suministro_id>/eliminar/', views.eliminar_suministro, name='eliminar_suministro'),
    path('sst/buscar/', views.buscar_sst, name='buscar_sst'),
    path('suministros/descargar-excel/', views.descargar_excel_suministros, name='descargar_excel_suministros')
    #path('dashboard/', views.dashboard, name='dashboard'),
    #path('', views.dashboard, name='dashboard_home'), 
]