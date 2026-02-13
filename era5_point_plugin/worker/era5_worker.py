import argparse
import cdsapi
import xarray as xr
import geopandas as gpd
import pandas as pd
from datetime import datetime, timedelta
import os

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
}

# Crear el mapa inverso: Corto -> Largo
REVERSE_MAP = {v: k for k, v in VARIABLE_NAME_MAP.items()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--points", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--hours", required=True)
    p.add_argument("--vars", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    # 1. Cargar puntos y preparar fechas
    points = gpd.read_file(args.points)
    # Asegurarnos de que estén en EPSG:4326
    if points.crs != "EPSG:4326":
        points = points.to_crs("EPSG:4326")

    start_dt = datetime.fromisoformat(args.start)
    end_dt = datetime.fromisoformat(args.end)
    hours = args.hours.split(",")
    variables = args.vars.split(",")
    
    # Rango de fechas para la API
    date_range = pd.date_range(start=start_dt, end=end_dt)
    years = list(set(date_range.strftime('%Y')))
    months = list(set(date_range.strftime('%m')))
    days = list(set(date_range.strftime('%d')))

    # 2. Definir área (N, W, S, E)
    lons = points.geometry.x
    lats = points.geometry.y
    area = [lats.max() + 0.1, lons.min() - 0.1, lats.min() - 0.1, lons.max() + 0.1]

    # 3. Descarga única (más eficiente que un bucle diario)
    
    c = cdsapi.Client()
    date_suffix = f"{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}"
    nc_path = os.path.join(args.out, f"temp_era5_{date_suffix}.nc")
    csv_filename = f"era5_results_{date_suffix}.csv"
    csv_path = os.path.join(args.out, csv_filename)

    print(f"Solicitando datos desde {args.start} hasta {args.end}...")
    
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

    # 4. Procesamiento con Xarray
    print("Extrayendo valores por punto...")
    
    try:
        ds = xr.open_dataset(nc_path, engine="netcdf4")
    except Exception as e:
        print(f"Error al abrir NetCDF: {e}")
        # Si sigue bajando un zip, podrías necesitar descomprimirlo aquí
        return
    
    # Ajuste de longitud si el dataset usa 0-360 y tus puntos -180 a 180
    if ds.longitude.max() > 180 and lons.min() < 0:
        ds = ds.assign_coords(longitude=(((ds.longitude + 180) % 360) - 180)).sortby('longitude')

    rows = []
    for i, row in points.iterrows():
        # Selección espacial
        p_ds = ds.sel(
            longitude=row.geometry.x,
            latitude=row.geometry.y,
            method="nearest"
        )
        
        # Convertir el subset del punto a DataFrame
        p_df = p_ds.to_dataframe().reset_index()
        
        # --- SOLUCIÓN PARA EL ID ---
        # Pasamos todos los atributos de la fila original del punto al nuevo DataFrame
        for column in points.columns:
            if column != 'geometry':
                p_df[column] = row[column]
        
        # También guardamos el índice original por si la capa no tiene campo ID
        p_df['original_index'] = i
        
        rows.append(p_df)

    # 5. Guardar resultado final
    final_df = pd.concat(rows, ignore_index=True)
    final_df = final_df.rename(columns=REVERSE_MAP)
    # Limpiar columnas técnicas de xarray que ensucian el CSV (opcional)
    cols_to_drop = ['expver', 'number'] 
    final_df = final_df.drop(columns=[c for c in cols_to_drop if c in final_df.columns])

    start_str = args.start.replace("-", "")
    end_str = args.end.replace("-", "")
    filename = f"era5_results_{start_str}_to_{end_str}.csv"
    
    csv_path = os.path.join(args.out, filename)
    final_df.to_csv(csv_path, index=False)
    ds.close()
    # Opcional: eliminar el .nc temporal
    os.remove(nc_path)
    
    print(f"RESULT_PATH:{csv_path}")
    print(f"Proceso finalizado. CSV en: {csv_path}")

if __name__ == "__main__":
    main()