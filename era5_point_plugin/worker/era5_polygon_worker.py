import argparse
import cdsapi
import xarray as xr
import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.features import rasterize
from shapely.geometry import box
from datetime import datetime
import os

# Mapeo de nombres de variables: CDS API → NetCDF
# Mapeo: nombre largo (API) → nombre corto (NetCDF)
VARIABLE_NAME_MAP = {
    "2m_temperature": "t2m",
    "2m_dewpoint_temperature": "d2m",
    "skin_temperature": "skt",
    "soil_temperature_level_1": "stl1",
    "soil_temperature_level_2": "stl2",
    "soil_temperature_level_3": "stl3",
    "soil_temperature_level_4": "stl4",
    "total_precipitation": "tp",
    "total_evaporation": "e",
    "potential_evaporation": "pev",
    "snowfall": "sf",
    "snow_depth": "sd",
    "snow_albedo": "asn",
    "snowmelt": "smlt",
    "snow_melt": "smlt",
    "volumetric_soil_water_layer_1": "swvl1",
    "volumetric_soil_water_layer_2": "swvl2",
    "volumetric_soil_water_layer_3": "swvl3",
    "volumetric_soil_water_layer_4": "swvl4",
    "surface_solar_radiation_downwards": "ssrd",
    "surface_net_solar_radiation": "ssr",
    "surface_thermal_radiation_downwards": "strd",
    "surface_net_thermal_radiation": "str",
    "10m_u_component_of_wind": "u10",
    "10m_v_component_of_wind": "v10",
    "surface_pressure": "sp",
    "leaf_area_index_high_vegetation": "lai_hv",
    "leaf_area_index_low_vegetation": "lai_lv",
    "runoff": "ro",
    "surface_runoff": "sro",
    "sub_surface_runoff": "ssro",
}

# Mapeo inverso: nombre corto (NetCDF) → nombre largo (para archivos)
VARIABLE_REVERSE_MAP = {v: k for k, v in VARIABLE_NAME_MAP.items()}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--polygons", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--hours", required=True)
    p.add_argument("--vars", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--resolution", type=float, default=0.1)
    p.add_argument("--output-format", choices=["raster", "vector"], default="raster",
                   help="Output format: 'raster' for GeoTIFF, 'vector' for grid polygons with attributes")
    args = p.parse_args()

    # 1. Cargar polígonos
    print("Cargando polígonos...")
    polygons = gpd.read_file(args.polygons)
    if polygons.crs != "EPSG:4326":
        polygons = polygons.to_crs("EPSG:4326")

    start_dt = datetime.fromisoformat(args.start)
    end_dt = datetime.fromisoformat(args.end)
    hours = args.hours.split(",")
    variables = args.vars.split(",")
    
    # Rango de fechas para la API
    date_range = pd.date_range(start=start_dt, end=end_dt)
    years = list(set(date_range.strftime('%Y')))
    months = list(set(date_range.strftime('%m')))
    days = list(set(date_range.strftime('%d')))

    # 2. Definir área de descarga (bbox de los polígonos con buffer)
    bounds = polygons.total_bounds  # [minx, miny, maxx, maxy]
    buffer = 0.2
    area = [
        bounds[3] + buffer,  # N (maxy)
        bounds[0] - buffer,  # W (minx)
        bounds[1] - buffer,  # S (miny)
        bounds[2] + buffer   # E (maxx)
    ]

    # 3. Descarga de datos ERA5
    c = cdsapi.Client()
    date_suffix = f"{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}"
    nc_path = os.path.join(args.out, f"temp_era5_polygons_{date_suffix}.nc")

    print(f"Solicitando datos desde {args.start} hasta {args.end}...")
    print(f"Área: N={area[0]:.2f}, W={area[1]:.2f}, S={area[2]:.2f}, E={area[3]:.2f}")
    print(f"Variables: {', '.join(variables)}")
    
    c.retrieve(
        "reanalysis-era5-land",
        {
            "variable": variables,
            "year": years,
            "month": months,
            "day": days,
            "time": hours,
            "area": area,
            "data_format": "netcdf",
            "download_format": "unarchived"
        },
        nc_path
    )

    print("Descarga completada. Procesando datos...")

    # 4. Procesar NetCDF y generar rasters
    try:
        # Abrir el dataset
        ds = xr.open_dataset(nc_path, engine="netcdf4")
        print(f"Variables disponibles en el dataset: {list(ds.data_vars)}")
        
        # Ajuste de longitud si es necesario (0-360 a -180:180)
        if ds.longitude.max() > 180:
            ds = ds.assign_coords(
                longitude=(((ds.longitude + 180) % 360) - 180)
            ).sortby('longitude')

        # Asegurar que latitudes estén en orden ascendente para rasterio
        if ds.latitude[0] > ds.latitude[-1]:
            ds = ds.sortby('latitude', ascending=True)

        # Detectar la dimensión de tiempo
        time_coord = 'time' if 'time' in ds.coords else 'valid_time'
        
        # Crear máscara de polígonos usando las coordenadas exactas del dataset
        print("Generando máscara de polígonos...")
        mask = create_polygon_mask(polygons, ds)
        
        # Verificar la máscara
        total_pixels = mask.size
        polygon_pixels = np.sum(mask)
        print(f"Máscara generada: {polygon_pixels}/{total_pixels} píxeles dentro del polígono ({100*polygon_pixels/total_pixels:.1f}%)")

        # 5. Iterar sobre variables y tiempos seleccionados
        raster_count = 0
        vector_count = 0
        selected_hours_ints = [int(h) for h in hours]

        for var_long_name in variables:
            # Mapear nombre largo (API) → nombre corto (NetCDF)
            var_short_name = VARIABLE_NAME_MAP.get(var_long_name, var_long_name)
            
            # Determinar qué nombre de variable existe en el archivo
            if var_short_name in ds.data_vars:
                var_to_use = var_short_name
            elif var_long_name in ds.data_vars:
                var_to_use = var_long_name
            else:
                print(f"⚠ Variable {var_long_name} no encontrada. Saltando...")
                continue

            var_for_filename = var_long_name

            print(f"Procesando variable: {var_to_use} ({var_for_filename})")

            # MODO VECTOR: Crear grid de polígonos con valores
            if args.output_format == "vector":
                created = create_vector_grid(
                    ds, polygons, var_to_use, var_for_filename, 
                    time_coord, selected_hours_ints, args.out
                )
                vector_count += len(created)
            
            # MODO RASTER: Crear rasters enmascarados (comportamiento original)
            else:
                # Iterar por cada paso de tiempo en el dataset
                for time_idx, time_val in enumerate(ds[time_coord].values):
                    time_dt = pd.Timestamp(time_val)
                    
                    # Filtrar por horas seleccionadas
                    if time_dt.hour in selected_hours_ints:
                        # Extraer datos
                        data = ds[var_to_use].isel({time_coord: time_idx}).values
                        
                        # Recortar al bounding box del polígono primero
                        clipped_data, clipped_mask, clipped_lons, clipped_lats = clip_to_polygon_bounds(
                            data, mask, ds.longitude.values, ds.latitude.values
                        )
                        
                        # Aplicar máscara recortada (convertir valores fuera del polígono a NaN)
                        masked_data = np.where(clipped_mask, clipped_data, np.nan)
                        
                        # Generar nombre de archivo único con nombre largo
                        timestamp_str = time_dt.strftime('%Y%m%d_%H%M')
                        raster_filename = f"{var_for_filename}_{timestamp_str}.tif"
                        raster_path = os.path.join(args.out, raster_filename)

                        # Guardar raster recortado y enmascarado
                        save_raster(
                            masked_data, 
                            raster_path, 
                            clipped_lons, 
                            clipped_lats
                        )
                        
                        # Imprimir para que el Plugin lo capture y cargue
                        print(f"RASTER_PATH:{raster_path}")
                        raster_count += 1

        if args.output_format == "vector":
            print(f"✓ Proceso finalizado. {vector_count} capas vectoriales generadas.")
        else:
            print(f"✓ Proceso finalizado. {raster_count} rasters generados.")

    except Exception as e:
        print(f"✗ Error durante el procesamiento: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        if 'ds' in locals():
            ds.close()
        # Eliminar el NetCDF temporal (comentar si quieres conservarlo para debugging)
        if os.path.exists(nc_path):
            try:
                os.remove(nc_path)
                print(f"Archivo temporal eliminado: {nc_path}")
            except:
                pass

def create_vector_grid(ds, polygons, var_short_name, var_long_name, time_coord, selected_hours_ints, output_dir):
    lons = ds.longitude.values
    lats = ds.latitude.values
    
    # 1. Preparar la geometría de corte una sola vez
    # Usamos union_all() si está disponible, si no unary_union
    try:
        target_geometry = polygons.geometry.union_all()
    except AttributeError:
        target_geometry = polygons.geometry.unary_union

    res_lon = abs(lons[1] - lons[0]) if len(lons) > 1 else 0.1
    res_lat = abs(lats[1] - lats[0]) if len(lats) > 1 else 0.1
    
    pixel_geometries = []
    pixel_coords = []
    
    # 2. Pre-calcular las intersecciones para el grid
    print(f"Calculando intersecciones exactas con el polígono...")
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            # Definir el cuadrado del píxel
            minx, maxx = lon - res_lon/2, lon + res_lon/2
            miny, maxy = lat - res_lat/2, lat + res_lat/2
            pixel_poly = box(minx, miny, maxx, maxy)
            
            # Si el píxel toca el polígono, lo recortamos
            if pixel_poly.intersects(target_geometry):
                clipped_geom = pixel_poly.intersection(target_geometry)
                
                # Solo guardamos si el resultado no es una línea o punto (es decir, tiene área)
                if not clipped_geom.is_empty and clipped_geom.area > 0:
                    pixel_geometries.append(clipped_geom)
                    pixel_coords.append((i, j))
    
    if not pixel_geometries:
        print(f"⚠ No se encontraron intersecciones válidas.")
        return []
    
    created_layers = []
    
    # 3. Generar los archivos por cada timestamp
    for time_idx, time_val in enumerate(ds[time_coord].values):
        time_dt = pd.Timestamp(time_val)
        if time_dt.hour in selected_hours_ints:
            data = ds[var_short_name].isel({time_coord: time_idx}).values
            
            pixel_values = [float(data[i, j]) for i, j in pixel_coords]
            
            gdf = gpd.GeoDataFrame({
                'geometry': pixel_geometries,
                var_long_name: pixel_values,
                'lat_center': [lats[i] for i, j in pixel_coords],
                'lon_center': [lons[j] for i, j in pixel_coords],
            }, crs="EPSG:4326")
            
            timestamp_str = time_dt.strftime('%Y%m%d_%H%M')
            output_filename = f"{var_long_name}_{timestamp_str}_grid.geojson"
            output_path = os.path.join(output_dir, output_filename)
            
            gdf.to_file(output_path, driver="GeoJSON")
            print(f"VECTOR_PATH:{output_path}")
            created_layers.append(output_path)
    
    return created_layers

def clip_to_polygon_bounds(data, mask, lons, lats):
    """
    Recorta el raster al bounding box de la máscara del polígono
    Retorna datos recortados, máscara recortada, y coordenadas ajustadas
    """
    # Encontrar filas y columnas que contienen el polígono
    rows_with_data = np.any(mask, axis=1)
    cols_with_data = np.any(mask, axis=0)
    
    # Si no hay datos, retornar todo
    if not np.any(rows_with_data) or not np.any(cols_with_data):
        return data, mask, lons, lats
    
    # Índices de inicio y fin
    row_start = np.argmax(rows_with_data)
    row_end = len(rows_with_data) - np.argmax(rows_with_data[::-1])
    
    col_start = np.argmax(cols_with_data)
    col_end = len(cols_with_data) - np.argmax(cols_with_data[::-1])
    
    # Recortar datos, máscara, lons y lats
    clipped_data = data[row_start:row_end, col_start:col_end]
    clipped_mask = mask[row_start:row_end, col_start:col_end]
    clipped_lats = lats[row_start:row_end]
    clipped_lons = lons[col_start:col_end]
    
    return clipped_data, clipped_mask, clipped_lons, clipped_lats

def create_polygon_mask(polygons, dataset):
    """
    Crea una máscara booleana donde True = dentro del polígono
    Usa las coordenadas exactas del dataset ERA5
    """
    lons = dataset.longitude.values
    lats = dataset.latitude.values
    
    # Calcular resolución real del dataset
    res_lon = abs(lons[1] - lons[0]) if len(lons) > 1 else 0.1
    res_lat = abs(lats[1] - lats[0]) if len(lats) > 1 else 0.1
    
    # Crear transformación afín alineada con los píxeles de ERA5
    # ERA5 usa centros de celda, así que ajustamos medio pixel
    from rasterio.transform import from_origin
    
    # La transformación debe ir desde la esquina superior izquierda
    west = lons.min() - (res_lon / 2)
    north = lats.max() + (res_lat / 2)
    
    transform = from_origin(west, north, res_lon, res_lat)
    
    # Rasterizar los polígonos
    shapes = [(geom, 1) for geom in polygons.geometry]
    
    mask = rasterize(
        shapes,
        out_shape=(len(lats), len(lons)),
        transform=transform,
        fill=0,
        dtype=np.uint8,
        all_touched=True
    )
    
    return mask.astype(bool)

def save_raster(data, output_path, lons, lats):
    """
    Guarda un array 2D como raster GeoTIFF
    Asume que lats ya están en orden ascendente
    """
    height, width = data.shape
    
    # Calcular resolución
    res_lon = abs(lons[1] - lons[0]) if len(lons) > 1 else 0.1
    res_lat = abs(lats[1] - lats[0]) if len(lats) > 1 else 0.1
    
    # Crear transformación desde la esquina superior izquierda
    from rasterio.transform import from_origin
    west = lons.min() - (res_lon / 2)
    north = lats.max() + (res_lat / 2)
    
    transform = from_origin(west, north, res_lon, res_lat)

    # WKT de WGS84 explícito
    wkt_4326 = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'

    # Definir valor NoData
    nodata_value = -9999.0
    
    # Preparar datos: reemplazar NaN con nodata
    output_data = np.where(np.isnan(data), nodata_value, data).astype(np.float32)

    # Calcular niveles de overview válidos
    max_overview_level = min(height, width) // 2
    overview_levels = []
    for level in [2, 4, 8, 16, 32]:
        if level < max_overview_level:
            overview_levels.append(level)
    
    # Escribir raster
    with rasterio.open(
        output_path, 'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=rasterio.float32,
        crs=wkt_4326,
        transform=transform,
        compress='lzw',
        nodata=nodata_value,
        tiled=True if min(height, width) >= 256 else False,
        blockxsize=min(256, width) if min(height, width) >= 256 else None,
        blockysize=min(256, height) if min(height, width) >= 256 else None
    ) as dst:
        # Escribir datos
        dst.write(output_data, 1)
        
        # Establecer NoData explícitamente en la banda
        dst.nodata = nodata_value
        
        # Crear overviews solo si tiene sentido
        if overview_levels and min(height, width) > 16:
            try:
                dst.build_overviews(overview_levels, rasterio.enums.Resampling.average)
            except Exception as e:
                print(f"⚠ No se pudieron crear overviews: {str(e)}")
        
        # Escribir metadatos para QGIS
        dst.update_tags(ns='AREA_OR_POINT', AREA_OR_POINT='Area')
        dst.set_band_description(1, 'ERA5-Land Data')
    
    # Verificar y corregir NoData con GDAL (más confiable para QGIS)
    try:
        from osgeo import gdal
        gdal.UseExceptions()
        
        ds = gdal.Open(output_path, gdal.GA_Update)
        if ds:
            band = ds.GetRasterBand(1)
            band.SetNoDataValue(nodata_value)
            band.FlushCache()
            ds.FlushCache()
            ds = None  # Cerrar
    except Exception as e:
        print(f"⚠ No se pudo establecer NoData con GDAL: {str(e)}")

if __name__ == "__main__":
    main()