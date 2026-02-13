import os
import subprocess
import sys

# 1. Configuración de Rutas de QGIS (Ajusta a tu versión instalada)
QGIS_PATH = r"C:\Program Files\QGIS 3.40.7"
PYTHON_EXE = os.path.join(QGIS_PATH, "apps", "Python312", "python.exe")

# 2. Configurar variables de entorno para evitar el error de PROJ/PostGIS
env = os.environ.copy()
env["PROJ_LIB"] = os.path.join(QGIS_PATH, "share", "proj")
env["GDAL_DATA"] = os.path.join(QGIS_PATH, "share", "gdal")
# Añadir carpetas de QGIS al PATH para que encuentre las DLLs necesarias
env["PATH"] = os.path.join(QGIS_PATH, "bin") + os.pathsep + env["PATH"]
# Asegurar que el backend de netcdf4 sea visible
env["PYTHONPATH"] = os.path.join(QGIS_PATH, "apps", "Python312", "Lib", "site-packages") + os.pathsep + env.get("PYTHONPATH", "")

# 3. Definir los argumentos para tu worker
worker_script = r"worker\era5_worker.py"
points_file = r"C:\Users\sanchez\Downloads\PlantnetTests\TESTERA5\S7\testmil.geojson"
output_dir = r"C:\Users\sanchez\Desktop\era5_test"

if not os.path.exists(output_dir):
    os.makedirs(output_dir)

args = [
    PYTHON_EXE, 
    worker_script,
    "--points", points_file,
    "--start", "2024-01-01",
    "--end", "2024-01-02",
    "--hours", "00:00,12:00", # Prueba con pocas horas primero para rapidez
    "--vars", "2m_temperature,total_precipitation",
    "--out", output_dir
]

# 4. Ejecutar
print("Iniciando prueba del worker con entorno controlado...")
result = subprocess.run(args, env=env, capture_output=True, text=True)

print("--- SALIDA DEL WORKER ---")
print(result.stdout)

if result.stderr:
    print("--- ERRORES ENCONTRADOS ---")
    print(result.stderr)