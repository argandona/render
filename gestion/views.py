from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from .models import SST, Suministro, Distrito, EstadoSST, EstadoSuministro
import pandas as pd
from decimal import Decimal
from django.db import models as django_models
from django.core.cache import cache

from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json

from django.core.paginator import Paginator


from django.views.decorators.csrf import csrf_exempt
from datetime import datetime


from django.core.paginator import Paginator
from django.core.cache import cache
from django.db.models import Q, Count

import pandas as pd
from django.http import HttpResponse
from io import BytesIO
from django.db.models import Q



@login_required
def dashboard(request):
    return render(request, 'gestion/dashboard.html')

@login_required
def sst_list(request):
    ssts = SST.objects.select_related('distrito', 'estado_sst').all()
    distritos = Distrito.objects.all()
    
    context = {
        'ssts': ssts,
        'distritos': distritos,
    }
    return render(request, 'gestion/sst.html', context)


@login_required
def cargar_excel_suministros(request):
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        
        try:
            # Leer el Excel
            df = pd.read_excel(excel_file)
            
            # Limpiar nombres de columnas
            df.columns = df.columns.str.strip()
            
            # Mapeo de columnas del Excel a nuestro modelo
            columnas_map = {
                'ITEM': 'Item',
                'N° OT': 'No. OT',
                'SUMINISTRO': 'Suministro',
                'DIRECCIÓN': 'Dirección',
                'DISTRITO': 'Distrito',
                'MEDIDOR': 'Medidor',
                'MARCA MEDIDOR': 'Marca',
                'FASE': 'Fase',
                'POTENCIA': 'Potencia',
                'FECHA_PRIMER_ENVIO': 'Fecha Primer Envío',
                'FECHA_PROGRAMADA': 'Fec. Prog.',
                'HORA_INICIO_PROG': 'Hor. Prog.',
                'HORA_FIN_PROG': 'Hor. Fin. Prog.',
                'FECHA_EJECUCION': 'Fecha Ejecución',
                'EJECUTADO_POR': 'Ejecutado Por',
                'CONTACTO': 'Contacto',
                'TELEFONO': 'Teléfono',
                'LATITUD': 'Latitud',
                'LONGITUD': 'Longitud',
                'OBSERVACION_CONTRATISTA': 'Observación Contratista',
                'ESTADO': 'Estado',
            }
            
            # Verificar columnas críticas
            columnas_criticas = ['Item', 'No. OT', 'Suministro', 'Dirección', 'Distrito']
            columnas_faltantes = [col for col in columnas_criticas if col not in df.columns]
            
            if columnas_faltantes:
                messages.error(request, f'❌ Faltan columnas: {", ".join(columnas_faltantes)}')
                return redirect('sst_list')
            
            # Obtener o crear estados por defecto
            estado_sst_default, _ = EstadoSST.objects.get_or_create(
                estado='PENDIENTE',
                defaults={'descripcion': 'Estado por defecto', 'color': '#FFA500'}
            )
            
            estado_suministro_default, _ = EstadoSuministro.objects.get_or_create(
                estado_suministro='PENDIENTE',
                defaults={'descripcion': 'Estado por defecto', 'color': '#FFA500'}
            )
            
            # Contadores
            ssts_creadas = 0
            suministros_creados = 0
            suministros_actualizados = 0
            errores = []
            
            # Agrupar por N° OT
            ots_unicas = df['No. OT'].dropna().unique()
            
            with transaction.atomic():
                ssts_procesadas = set()  # Para trackear SSTs que necesitan actualización
                
                for ot in ots_unicas:
                    try:
                        # Filtrar suministros de esta OT
                        suministros_ot = df[df['No. OT'] == ot]
                        
                        if len(suministros_ot) == 0:
                            continue
                        
                        # Extraer código SST del N° OT
                        codigo_sst = str(ot).strip()[:7] if len(str(ot).strip()) >= 7 else str(ot).strip()
                        
                        # Obtener distrito más frecuente
                        distrito_principal_nombre = suministros_ot['Distrito'].mode()[0] if not suministros_ot['Distrito'].mode().empty else suministros_ot['Distrito'].iloc[0]
                        distrito_principal, _ = Distrito.objects.get_or_create(nombre_distrito=str(distrito_principal_nombre).strip())
                        
                        # Primera dirección
                        direccion_principal = str(suministros_ot['Dirección'].iloc[0]).strip() if pd.notna(suministros_ot['Dirección'].iloc[0]) else 'Sin dirección'
                        
                        # Crear o actualizar SST
                        sst, created = SST.objects.get_or_create(
                            sst=codigo_sst,
                            defaults={
                                'direccion': direccion_principal,
                                'distrito': distrito_principal,
                                'estado_sst': estado_sst_default,
                                'monto_proyectado': Decimal('0.00')
                            }
                        )
                        
                        if created:
                            ssts_creadas += 1
                        
                        ssts_procesadas.add(sst.id)  # Guardar ID de SST procesada
                        
                        # Crear cada suministro
                        for index, row in suministros_ot.iterrows():
                            try:
                                # Extraer datos
                                item = int(row['Item']) if pd.notna(row['Item']) else 0
                                no_ot = str(row['No. OT']).strip() if pd.notna(row['No. OT']) else ''
                                suministro_codigo = str(row['Suministro']).strip() if pd.notna(row['Suministro']) else ''
                                medidor = str(row['Medidor']).strip() if pd.notna(row['Medidor']) else None
                                marca_medidor = str(row['Marca']).strip() if pd.notna(row['Marca']) else None
                                fase = str(row['Fase']).strip() if pd.notna(row['Fase']) else None
                                potencia = str(row['Potencia']).strip() if pd.notna(row['Potencia']) else None
                                direccion = str(row['Dirección']).strip() if pd.notna(row['Dirección']) else ''
                                distrito_nombre = str(row['Distrito']).strip() if pd.notna(row['Distrito']) else ''
                                
                                # Datos adicionales
                                latitud = row.get('Latitud')
                                longitud = row.get('Longitud')
                                contacto = str(row.get('Contacto', '')).strip() if pd.notna(row.get('Contacto')) else None
                                telefono = str(row.get('Teléfono', '')).strip() if pd.notna(row.get('Teléfono')) else None
                                ejecutado_por = str(row.get('Ejecutado Por', '')).strip() if pd.notna(row.get('Ejecutado Por')) else None
                                observacion_contratista = str(row.get('Observación Contratista', '')).strip() if pd.notna(row.get('Observación Contratista')) else None
                                
                                # Fechas y horas
                                fecha_primer_envio = pd.to_datetime(row.get('Fecha Primer Envío'), errors='coerce') if pd.notna(row.get('Fecha Primer Envío')) else None
                                fecha_programada = pd.to_datetime(row.get('Fec. Prog.'), errors='coerce') if pd.notna(row.get('Fec. Prog.')) else None
                                fecha_ejecucion = pd.to_datetime(row.get('Fecha Ejecución'), errors='coerce') if pd.notna(row.get('Fecha Ejecución')) else None
                                
                                # Convertir a TimeField si es posible
                                hora_inicio_prog = None
                                hora_fin_prog = None
                                if pd.notna(row.get('Hor. Prog.')):
                                    try:
                                        hora_inicio_prog = pd.to_datetime(str(row['Hor. Prog.']), format='%H:%M:%S', errors='coerce').time()
                                    except:
                                        pass
                                
                                if pd.notna(row.get('Hor. Fin. Prog.')):
                                    try:
                                        hora_fin_prog = pd.to_datetime(str(row['Hor. Fin. Prog.']), format='%H:%M:%S', errors='coerce').time()
                                    except:
                                        pass
                                
                                # Obtener o crear distrito del suministro
                                distrito_suministro, _ = Distrito.objects.get_or_create(nombre_distrito=distrito_nombre)
                                
                                # Obtener o crear estado del suministro
                                estado_nombre = str(row.get('Estado', '')).strip() if pd.notna(row.get('Estado')) else ''
                                if estado_nombre:
                                    estado_sum, _ = EstadoSuministro.objects.get_or_create(
                                        estado_suministro=estado_nombre,
                                        defaults={'descripcion': '', 'color': '#007bff'}
                                    )
                                else:
                                    estado_sum = estado_suministro_default
                                
                                # Verificar si existe
                                suministro_existente = Suministro.objects.filter(
                                    sst=sst,
                                    suministro=suministro_codigo
                                ).first()
                                
                                if suministro_existente:
                                    # Actualizar
                                    suministro_existente.item = item
                                    suministro_existente.no_ot = no_ot
                                    suministro_existente.medidor = medidor
                                    suministro_existente.marca_medidor = marca_medidor
                                    suministro_existente.fase = fase
                                    suministro_existente.potencia = potencia
                                    suministro_existente.direccion = direccion
                                    suministro_existente.distrito = distrito_suministro
                                    suministro_existente.latitud = latitud
                                    suministro_existente.longitud = longitud
                                    suministro_existente.contacto = contacto
                                    suministro_existente.telefono = telefono
                                    suministro_existente.fecha_primer_envio = fecha_primer_envio
                                    suministro_existente.fecha_programada = fecha_programada
                                    suministro_existente.hora_inicio_programada = hora_inicio_prog
                                    suministro_existente.hora_fin_programada = hora_fin_prog
                                    suministro_existente.fecha_ejecucion = fecha_ejecucion
                                    suministro_existente.ejecutado_por = ejecutado_por
                                    suministro_existente.estado_suministro = estado_sum
                                    suministro_existente.observacion_contratista = observacion_contratista
                                    suministro_existente.save()
                                    suministros_actualizados += 1
                                else:
                                    # Crear nuevo
                                    Suministro.objects.create(
                                        sst=sst,
                                        item=item,
                                        no_ot=no_ot,
                                        suministro=suministro_codigo,
                                        medidor=medidor,
                                        marca_medidor=marca_medidor,
                                        fase=fase,
                                        potencia=potencia,
                                        direccion=direccion,
                                        distrito=distrito_suministro,
                                        latitud=latitud,
                                        longitud=longitud,
                                        contacto=contacto,
                                        telefono=telefono,
                                        fecha_primer_envio=fecha_primer_envio,
                                        fecha_programada=fecha_programada,
                                        hora_inicio_programada=hora_inicio_prog,
                                        hora_fin_programada=hora_fin_prog,
                                        fecha_ejecucion=fecha_ejecucion,
                                        ejecutado_por=ejecutado_por,
                                        estado_suministro=estado_sum,
                                        observacion_contratista=observacion_contratista
                                    )
                                    suministros_creados += 1
                                
                            except Exception as e:
                                errores.append(f"Fila {index + 2}: {str(e)}")
                                continue
                        
                    except Exception as e:
                        errores.append(f"OT {ot}: {str(e)}")
                        continue
                
                # ⭐ ACTUALIZAR ESTADOS DE TODAS LAS SST PROCESADAS
                for sst_id in ssts_procesadas:
                    try:
                        sst = SST.objects.get(id=sst_id)
                        sst.actualizar_estado_segun_suministros()
                    except Exception as e:
                        errores.append(f"Error actualizando SST {sst_id}: {str(e)}")
            
            # Mensajes
            mensaje_exito = []
            if ssts_creadas > 0:
                mensaje_exito.append(f'{ssts_creadas} SST creadas')
            if suministros_creados > 0:
                mensaje_exito.append(f'{suministros_creados} suministros creados')
            if suministros_actualizados > 0:
                mensaje_exito.append(f'{suministros_actualizados} suministros actualizados')
            
            if mensaje_exito:
                messages.success(request, f'✅ {", ".join(mensaje_exito)}.')
            
            if errores:
                messages.warning(request, f'⚠️ {len(errores)} errores encontrados.')
                for error in errores[:5]:
                    messages.warning(request, error)
            
            return redirect('sst_list')
            
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')
            return redirect('sst_list')
    
    return redirect('sst_list')




@login_required
def suministro_list(request):

    # Filtros
    sst_filter = request.GET.get('sst', '')
    distrito_filter = request.GET.get('distrito', '')
    estado_filter = request.GET.get('estado', '')
    search = request.GET.get('search', '')

    todas_sst = SST.objects.select_related('distrito', 'estado_sst').order_by('sst')

    # 🔹 Query base (SIEMPRE primero)
    suministros = Suministro.objects.select_related(
        'sst', 'distrito', 'estado_suministro'
    ).all()

    # 🔹 Filtros
    if sst_filter:
        suministros = suministros.filter(sst__sst__icontains=sst_filter)

    if distrito_filter:
        suministros = suministros.filter(distrito__nombre_distrito=distrito_filter)

    if estado_filter:
        suministros = suministros.filter(
            estado_suministro__estado_suministro=estado_filter
        )

    if search:
        suministros = suministros.filter(
            Q(suministro__icontains=search) |
            Q(medidor__icontains=search) |
            Q(direccion__icontains=search)
        )

    # 🔹 Paginación (DESPUÉS de filtros)
    paginator = Paginator(suministros, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 🔹 Cache distritos (bien)
    distritos = cache.get('distritos')
    if not distritos:
        distritos = Distrito.objects.all()
        cache.set('distritos', distritos, 3600)

    estados = EstadoSuministro.objects.all()
    ssts = SST.objects.all()

    # 🔹 Estadísticas SST
    sst_stats = SST.objects.values('estado_sst__estado').annotate(
        cantidad=Count('id')
    )
    sst_por_estado = {i['estado_sst__estado']: i['cantidad'] for i in sst_stats}

    # 🔹 Estadísticas Suministros
    suministro_stats = Suministro.objects.values(
        'estado_suministro__estado_suministro'
    ).annotate(cantidad=Count('id'))
    suministros_por_estado = {
        i['estado_suministro__estado_suministro']: i['cantidad']
        for i in suministro_stats
    }

    context = {
        'suministros': page_obj,  # 👈 usa el paginado
        'page_obj': page_obj,
        'paginator': paginator,

        'distritos': distritos,
        'estados': estados,
        'ssts': ssts,
        'todas_sst': todas_sst,

        'sst_filter': sst_filter,
        'distrito_filter': distrito_filter,
        'estado_filter': estado_filter,
        'search': search,

        # Estadísticas SST
        'sst_ejecutado': sst_por_estado.get('Ejecutado', 0),
        'sst_admisible': sst_por_estado.get('Admisible', 0),
        'sst_en_ejecucion': sst_por_estado.get('En Ejecución', 0),
        'sst_pendiente': sst_por_estado.get('Pendiente', 0),

        # Estadísticas Suministros
        'sum_asignado': suministros_por_estado.get('ASIGNADO', 0)
                        + suministros_por_estado.get('Asignado', 0),
        'sum_devuelto': suministros_por_estado.get('DEVUELTO', 0)
                        + suministros_por_estado.get('Devuelto', 0),
        'sum_ejecutado': suministros_por_estado.get('EJECUTADO', 0)
                        + suministros_por_estado.get('Ejecutado', 0),

        'total_suministros': suministros.count(),
    }

    return render(request, 'gestion/suministros.html', context)




@login_required
@require_POST
def actualizar_suministro(request, suministro_id):
    try:
        suministro = Suministro.objects.get(id=suministro_id)
        
        # Obtener datos del POST
        data = json.loads(request.body)
        # Guardar el monto anterior para comparar
        monto_anterior = suministro.monto
        
        # Actualizar estado
        estado_id = data.get('estado_suministro')
        if estado_id:
            try:
                estado = EstadoSuministro.objects.get(id=estado_id)
                suministro.estado_suministro = estado
            except EstadoSuministro.DoesNotExist:
                pass
        
        # Actualizar fecha de ejecución
        fecha_ejecucion = data.get('fecha_ejecucion')
        if fecha_ejecucion:
            from datetime import datetime
            suministro.fecha_ejecucion = datetime.strptime(fecha_ejecucion, '%Y-%m-%d').date()
        
        # Actualizar ejecutado por
        ejecutado_por = data.get('ejecutado_por')
        if ejecutado_por:
            suministro.ejecutado_por = ejecutado_por
            
        # ✅ ACTUALIZAR MONTO (IMPORTANTE)
        monto = data.get('monto')
        if monto is not None:
            try:
                suministro.monto = Decimal(str(monto))
            except (ValueError, TypeError):
                pass
        
        observacion = data.get('observacion_contratista')
        if observacion is not None:
            suministro.observacion_contratista = observacion
        
        suministro.save()
        
        # ✅ ACTUALIZAR MONTO DE LA SST SI CAMBIÓ EL MONTO
        if monto_anterior != suministro.monto:
            suministro.sst.actualizar_monto_total()
        
        # Actualizar estado de la SST
        suministro.sst.actualizar_estado_segun_suministros()
        
        return JsonResponse({
            'success': True,
            'message': 'Suministro actualizado correctamente'
        })
        
    except Suministro.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Suministro no encontrado'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
        
           
        
        # Actualizar observaciones
        observacion = data.get('observacion_contratista')
        if observacion is not None:
            suministro.observacion_contratista = observacion
        
        suministro.save()
        
        # ⭐ ACTUALIZAR ESTADO DE LA SST AUTOMÁTICAMENTE
        suministro.sst.actualizar_estado_segun_suministros()
        
        return JsonResponse({
            'success': True,
            'message': 'Suministro actualizado correctamente'
        })
        
    except Suministro.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Suministro no encontrado'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
        
        
@login_required
@csrf_exempt
def agregar_suministro_adicional(request):
    """Vista para agregar suministros adicionales vía AJAX"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Validar datos requeridos
            sst_id = data.get('sst_id')
            if not sst_id:
                return JsonResponse({
                    'success': False,
                    'message': 'Debe seleccionar una SST'
                }, status=400)
            
            motivo_adicional = data.get('motivo_adicional', '').strip()
            if not motivo_adicional:
                return JsonResponse({
                    'success': False,
                    'message': 'El motivo del suministro adicional es obligatorio'
                }, status=400)
            
            # Obtener la SST
            try:
                sst = SST.objects.get(id=sst_id)
            except SST.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'SST no encontrada'
                }, status=404)
            
            # Generar número de suministro automático si está vacío
            suministro_num = data.get('suministro', '').strip()
            if not suministro_num:
                # Contar suministros adicionales existentes en esta SST
                count_adicionales = Suministro.objects.filter(
                    sst=sst, 
                    tipo_suministro='ADICIONAL'
                ).count()
                suministro_num = f"{sst.sst}-AD{count_adicionales + 1:03d}"
            
            # Generar item automático
            ultimo_suministro = Suministro.objects.filter(sst=sst).order_by('-item').first()
            nuevo_item = ultimo_suministro.item + 1 if ultimo_suministro else 1
            
            # Obtener estado del suministro
            estado_sum = None
            estado_id = data.get('estado_suministro')
            if estado_id:
                try:
                    estado_sum = EstadoSuministro.objects.get(id=estado_id)
                except EstadoSuministro.DoesNotExist:
                    pass
            
            # Si no se especifica estado, usar por defecto
            if not estado_sum:
                estado_sum, _ = EstadoSuministro.objects.get_or_create(
                    estado_suministro='PENDIENTE',
                    defaults={'descripcion': 'Pendiente de ejecución', 'color': '#FFA500'}
                )
                
                
            # ✅ OBTENER MONTO (si no viene, se calculará automáticamente)
            monto = Decimal('0.00')
            monto_data = data.get('monto')
            if monto_data:
                try:
                    monto = Decimal(str(monto_data))
                except:
                    pass    
            
            # Crear el suministro adicional
            suministro = Suministro(
                sst=sst,
                tipo_suministro='ADICIONAL',
                item=nuevo_item,
                no_ot=sst.sst,  # Usar SST como N° OT
                suministro=suministro_num,
                monto=monto,  # ✅ AGREGAR MONTO
                estado_suministro=estado_sum,
                direccion=sst.direccion,
                distrito=sst.distrito,
                motivo_adicional=motivo_adicional,
                fecha_ejecucion=data.get('fecha_ejecucion') or None,
                ejecutado_por=data.get('ejecutado_por', '').strip() or None,
                contacto=data.get('contacto', '').strip() or None,
                telefono=data.get('telefono', '').strip() or None,
                solicitado_por=data.get('solicitado_por', '').strip() or None,
                observacion_contratista=data.get('observacion_contratista', '').strip() or None,
                fecha_identificacion=datetime.now().date()  # Fecha actual
            )
            
            suministro.save()
            
            # Actualizar estado de la SST
            sst.actualizar_estado_segun_suministros()
            
            return JsonResponse({
                'success': True,
                'message': f'Suministro adicional "{suministro_num}" creado exitosamente',
                'suministro_id': suministro.id,
                'suministro_numero': suministro_num
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'message': 'Método no permitido'
    }, status=405)


@login_required
def obtener_info_sst(request, sst_id):
    """Obtener información de una SST específica para el modal"""
    try:
        sst = SST.objects.select_related('distrito', 'estado_sst').get(id=sst_id)
        
        # Obtener estadísticas de la SST
        total_suministros = sst.suministros.count()
        suministros_adicionales = sst.suministros.filter(tipo_suministro='ADICIONAL').count()
        
        # Generar sugerencia de número de suministro
        ultimo_adicional = sst.suministros.filter(tipo_suministro='ADICIONAL').order_by('-suministro').first()
        if ultimo_adicional:
            try:
                # Intentar extraer número del último suministro adicional
                ultimo_num = ultimo_adicional.suministro.split('-')[-1]
                if ultimo_num.startswith('AD'):
                    num = int(ultimo_num[2:]) + 1
                    sugerencia = f"{sst.sst}-AD{num:03d}"
                else:
                    sugerencia = f"{sst.sst}-AD001"
            except:
                sugerencia = f"{sst.sst}-AD001"
        else:
            sugerencia = f"{sst.sst}-AD001"
        
        data = {
            'sst': sst.sst,
            'direccion': sst.direccion,
            'distrito': sst.distrito.nombre_distrito if sst.distrito else 'Sin distrito',
            'estado': sst.estado_sst.estado if sst.estado_sst else 'Sin estado',
            'total_suministros': total_suministros,
            'suministros_adicionales': suministros_adicionales,
            'sugerencia_suministro': sugerencia
        }
        
        return JsonResponse({
            'success': True,
            'data': data
        })
        
    except SST.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'SST no encontrada'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)   
        
        
def suministros_view(request):
    context = {
        # SST
        "sst_ejecutadas": SST.objects.filter(estado_sst__estado="Ejecutada").count(),
        "sst_admisibles": SST.objects.filter(estado_sst__estado="Admisible").count(),
        "sst_en_ejecucion": SST.objects.filter(estado_sst__estado="En Ejecución").count(),

        # SUMINISTROS
        "suministros_ejecutados": Suministro.objects.filter(
            estado_suministro__estado_suministro="Ejecutado"
        ).count(),
        "suministros_asignados": Suministro.objects.filter(
            estado_suministro__estado_suministro="Asignado"
        ).count(),
        "suministros_devueltos": Suministro.objects.filter(
            estado_suministro__estado_suministro="Devuelto"
        ).count(),

        # lo que ya tenías
        "suministros": Suministro.objects.select_related(
            "sst", "estado_suministro", "distrito"
        ),
    }

    return render(request, "gestion/suministros.html", context)             




@login_required
@require_POST
def eliminar_suministro(request, suministro_id):
    try:
        suministro = Suministro.objects.get(id=suministro_id)
        sst = suministro.sst  # Guardar referencia antes de eliminar
        
        # Eliminar suministro
        suministro.delete()
        
        # Actualizar estado de la SST automáticamente
        sst.actualizar_estado_segun_suministros()
        
        return JsonResponse({
            'success': True,
            'message': f'Suministro {suministro.suministro} eliminado correctamente'
        })
        
    except Suministro.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Suministro no encontrado'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
        
 
 
@login_required
def buscar_sst(request):
    """Vista para buscar SST con autocompletado"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({
            'success': True,
            'data': []
        })
    
    try:
        # Buscar por código SST o dirección
        sst_list = SST.objects.filter(
            Q(sst__icontains=query) | 
            Q(direccion__icontains=query)
        ).select_related('distrito').order_by('sst')[:10]  # Limitar a 10 resultados
        
        results = []
        for sst in sst_list:
            # Asegúrate de que estos campos existan en tu modelo
            total_original = sst.suministros.filter(tipo_suministro='ORIGINAL').count()
            total_adicional = sst.suministros.filter(tipo_suministro='ADICIONAL').count()
            
            results.append({
                'id': sst.id,
                'sst': sst.sst,
                'direccion': sst.direccion,
                'distrito': sst.distrito.nombre_distrito if sst.distrito else '',
                'estado': sst.estado_sst.estado if sst.estado_sst else '',  # Corregido
                'total_suministros': f"{total_original}/{total_adicional}"
            })
        
        return JsonResponse({
            'success': True,
            'data': results
        })
    
    except Exception as e:
        # Registrar el error para debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error en buscar_sst: {str(e)}")
        
        return JsonResponse({
            'success': False,
            'message': 'Error interno del servidor',
            'data': []
        }, status=500)
        
        
        

@login_required
def descargar_excel_suministros(request):
    """Descargar suministros filtrados en Excel"""
    try:
        # Obtener los mismos filtros que en suministro_list
        sst_filter = request.GET.get('sst', '')
        distrito_filter = request.GET.get('distrito', '')
        estado_filter = request.GET.get('estado', '')
        search = request.GET.get('search', '')
        
        # Aplicar los mismos filtros que en suministro_list
        suministros = Suministro.objects.select_related(
            'sst', 'distrito', 'estado_suministro'
        ).all()
        
        if sst_filter:
            suministros = suministros.filter(sst__sst__icontains=sst_filter)
        
        if distrito_filter:
            suministros = suministros.filter(distrito__nombre_distrito=distrito_filter)
        
        if estado_filter:
            suministros = suministros.filter(
                estado_suministro__estado_suministro=estado_filter
            )
        
        if search:
            suministros = suministros.filter(
                Q(suministro__icontains=search) |
                Q(medidor__icontains=search) |
                Q(direccion__icontains=search)
            )
        
        # Crear DataFrame
        data = []
        for s in suministros:
            data.append({
                'ITEM': s.item,
                'SST': s.sst.sst if s.sst else '',
                'SUMINISTRO': s.suministro,
                'TIPO': s.tipo_suministro,
                'MEDIDOR': s.medidor or '',
                'MARCA_MEDIDOR': s.marca_medidor or '',
                'FASE': s.fase or '',
                'POTENCIA': s.potencia or '',
                'ESTADO': s.estado_suministro.estado_suministro if s.estado_suministro else '',
                'DIRECCIÓN': s.direccion,
                'DISTRITO': s.distrito.nombre_distrito if s.distrito else '',
                'CONTACTO': s.contacto or '',
                'TELÉFONO': s.telefono or '',
                'LATITUD': s.latitud or '',
                'LONGITUD': s.longitud or '',
                'FECHA_PRIMER_ENVIO': s.fecha_primer_envio.strftime('%d/%m/%Y') if s.fecha_primer_envio else '',
                'FECHA_PROGRAMADA': s.fecha_programada.strftime('%d/%m/%Y') if s.fecha_programada else '',
                'HORA_INICIO_PROG': s.hora_inicio_programada.strftime('%H:%M') if s.hora_inicio_programada else '',
                'HORA_FIN_PROG': s.hora_fin_programada.strftime('%H:%M') if s.hora_fin_programada else '',
                'FECHA_EJECUCIÓN': s.fecha_ejecucion.strftime('%d/%m/%Y') if s.fecha_ejecucion else '',
                'EJECUTADO_POR': s.ejecutado_por or '',
                'OBSERVACIÓN_CONTRATISTA': s.observacion_contratista or '',
                'MOTIVO_ADICIONAL': s.motivo_adicional or '',
                'FECHA_IDENTIFICACIÓN': s.fecha_identificacion.strftime('%d/%m/%Y') if s.fecha_identificacion else '',
                'SOLICITADO_POR': s.solicitado_por or '',
            })
        
        df = pd.DataFrame(data)
        
        # Crear el archivo Excel en memoria
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Suministros', index=False)
            
            # Autoajustar columnas
            worksheet = writer.sheets['Suministros']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        # Crear respuesta HTTP
        filename = f"suministros_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        messages.error(request, f'Error al generar Excel: {str(e)}')
        return redirect('suministro_list')        
    
    
    
    
# management/commands/sincronizar_montos_sst.py
from django.core.management.base import BaseCommand
from gestion.models import SST
from decimal import Decimal

class Command(BaseCommand):
    help = 'Sincroniza los montos de todas las SSTs con la suma de sus suministros'
    
    def handle(self, *args, **kwargs):
        ssts = SST.objects.all()
        total_actualizado = 0
        
        for sst in ssts:
            monto_anterior = sst.monto_proyectado
            monto_nuevo = sst.actualizar_monto_total()
            
            if monto_anterior != monto_nuevo:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'SST {sst.sst}: {monto_anterior} → {monto_nuevo}'
                    )
                )
                total_actualizado += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ {total_actualizado} SSTs actualizadas de {ssts.count()} totales'
            )
        )    
        
        
        
@login_required
def descargar_excel_modulo(request):
    pass

from django.db.models import Count, Sum, Q
from datetime import datetime, timedelta
from django.utils import timezone
from decimal import Decimal

@login_required
def dashboard(request):
    """Dashboard simple de SST"""
    
    hoy = timezone.now()
    inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # KPIs principales
    sst_totales = SST.objects.count()
    
    # Estados de SST (EXACTAMENTE como mencionaste)
    sst_ejecutadas = SST.objects.filter(
        estado_sst__estado='EJECUTADO'
    ).count()
    
    sst_en_ejecucion = SST.objects.filter(
        estado_sst__estado='EN EJECUCIÓN'
    ).count()
    
    sst_admisibles = SST.objects.filter(
        estado_sst__estado='ADMISIBLE'
    ).count()
    
    # Otros estados (si existen)
    sst_otros = sst_totales - (sst_ejecutadas + sst_en_ejecucion + sst_admisibles)
    
    # Porcentajes
    if sst_totales > 0:
        porcentaje_ejecutadas = round((sst_ejecutadas / sst_totales) * 100, 1)
        porcentaje_en_ejecucion = round((sst_en_ejecucion / sst_totales) * 100, 1)
        porcentaje_admisibles = round((sst_admisibles / sst_totales) * 100, 1)
        porcentaje_otros = round((sst_otros / sst_totales) * 100, 1)
    else:
        porcentaje_ejecutadas = porcentaje_en_ejecucion = porcentaje_admisibles = porcentaje_otros = 0
    
    # Suministros (EXACTAMENTE como mencionaste)
    total_suministros = Suministro.objects.count()
    
    suministros_ejecutados = Suministro.objects.filter(
        estado_suministro__estado_suministro='EJECUTADO'
    ).count()
    
    suministros_asignados = Suministro.objects.filter(
        estado_suministro__estado_suministro='ASIGNADO'
    ).count()
    
    suministros_devueltos = Suministro.objects.filter(
        estado_suministro__estado_suministro='DEVUELTO'
    ).count()
    
    # Montos
    monto_total_proyectado = SST.objects.aggregate(
        total=Sum('monto_proyectado')
    )['total'] or Decimal('0.00')
    
    monto_total_real = SST.objects.aggregate(
        total=Sum('monto_real')
    )['total'] or Decimal('0.00')
    
    # Eficiencia financiera
    if monto_total_proyectado > 0:
        eficiencia_financiera = round((monto_total_real / monto_total_proyectado) * 100, 1)
    else:
        eficiencia_financiera = 0
    
    # Este mes
    sst_este_mes = SST.objects.filter(
        created_at__gte=inicio_mes
    ).count()
    
    sst_ejecutadas_mes = SST.objects.filter(
        created_at__gte=inicio_mes,
        estado_sst__estado='EJECUTADO'
    ).count()
    
    monto_mes = SST.objects.filter(
        created_at__gte=inicio_mes
    ).aggregate(
        total=Sum('monto_proyectado')
    )['total'] or Decimal('0.00')
    
    suministros_mes = Suministro.objects.filter(
        created_at__gte=inicio_mes
    ).count()
    
    # Últimas SST
    ultimas_sst = SST.objects.select_related('distrito', 'estado_sst').order_by('-created_at')[:10]
    
    # SST en ejecución con días transcurridos
    sst_en_ejecucion_list = SST.objects.filter(
        estado_sst__estado='EN EJECUCIÓN'
    ).select_related('distrito').order_by('-created_at')[:10]
    
    # Calcular días transcurridos
    for sst in sst_en_ejecucion_list:
        sst.dias_transcurridos = (timezone.now().date() - sst.created_at.date()).days
    
    context = {
        # SST
        'sst_totales': sst_totales,
        'sst_ejecutadas': sst_ejecutadas,
        'sst_en_ejecucion': sst_en_ejecucion,
        'sst_admisibles': sst_admisibles,
        'sst_otros': sst_otros,
        
        # Porcentajes SST
        'porcentaje_ejecutadas': porcentaje_ejecutadas,
        'porcentaje_en_ejecucion': porcentaje_en_ejecucion,
        'porcentaje_admisibles': porcentaje_admisibles,
        'porcentaje_otros': porcentaje_otros,
        
        # Suministros
        'total_suministros': total_suministros,
        'suministros_ejecutados': suministros_ejecutados,
        'suministros_asignados': suministros_asignados,
        'suministros_devueltos': suministros_devueltos,
        
        # Financiero
        'monto_total_proyectado': monto_total_proyectado,
        'monto_total_real': monto_total_real,
        'eficiencia_financiera': eficiencia_financiera,
        
        # Este mes
        'sst_este_mes': sst_este_mes,
        'sst_ejecutadas_mes': sst_ejecutadas_mes,
        'monto_mes': monto_mes,
        'suministros_mes': suministros_mes,
        
        # Listados
        'ultimas_sst': ultimas_sst,
        'sst_en_ejecucion_list': sst_en_ejecucion_list,
    }
    
    return render(request, 'gestion/dashboard.html', context)







# sst_app/views.


# sst_app/views.py

"""
from django.shortcuts import render
from django.db.models import Sum

def reporte_productividad(request):
  
    Vista para mostrar el reporte de productividad por ejecutor
    Maneja correctamente valores None y tablas vacías
   
    try:
        # Obtener suministros con ejecutor
        suministros_con_ejecutor = Suministro.objects.exclude(
            ejecutado_por__isnull=True
        ).exclude(
            ejecutado_por=''
        )

        # Agrupar por ejecutor y sumar montos
        resultados = suministros_con_ejecutor.values('ejecutado_por').annotate(
            total_monto=Sum('monto')
        ).order_by('ejecutado_por')

        # Calcular total general
        total_general = sum(item['total_monto'] or 0 for item in resultados)

        # Calcular promedio por ejecutor
        promedio_por_ejecutor = 0
        if len(resultados) > 0:
            promedio_por_ejecutor = total_general / len(resultados)

    except Exception as e:
        print(f"[ERROR] reporte_productividad: {e}")
        resultados = []
        total_general = 0
        promedio_por_ejecutor = 0

    context = {
        'resultados': resultados,
        'total_general': total_general,
        'promedio_por_ejecutor': promedio_por_ejecutor,
    }
    
    return render(request, 'gestion/reporte_productividad.html', context)"""
    
    
    
from django.shortcuts import render
from django.db.models import Sum
from django.db.models.functions import TruncDate
from .models import Suministro
from collections import defaultdict

def reporte_productividad(request):
    """
    Reporte agrupado por fecha y luego por ejecutor
    """
    # Filtrar solo suministros ejecutados
    suministros = Suministro.objects.exclude(
        ejecutado_por__isnull=True
    ).exclude(
        ejecutado_por=''
    ).order_by('fecha_ejecucion', 'ejecutado_por')

    # Diccionario para agrupar datos
    reporte = defaultdict(lambda: defaultdict(lambda: Decimal('0.00')))
    total_general = Decimal('0.00')

    for s in suministros:
        fecha = s.fecha_ejecucion
        ejecutor = s.ejecutado_por
        monto = s.monto or Decimal('0.00')

        reporte[fecha][ejecutor] += monto
        total_general += monto

    # Convertir defaultdict a dict normal para pasar al template
    reporte = {fecha: dict(ejecutores) for fecha, ejecutores in reporte.items()}

    context = {
        'reporte': reporte,
        'total_general': total_general,
    }

    return render(request, 'gestion/reporte_productividad_fecha.html', context)
    
