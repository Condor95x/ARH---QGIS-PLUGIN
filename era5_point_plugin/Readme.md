QGIS ERA5-Land Data Extractor 🌍
A powerful QGIS plugin designed to automate the download and processing of ERA5-Land climatic data from the Copernicus Climate Data Store (CDS). This tool simplifies the transition from global climate models to local GIS analysis.

🚀 Key Features
Point Extraction: Retrieve historical values for specific coordinate locations and export them into a clean, formatted CSV for time-series analysis.

Polygon Extraction:

Raster Mode: Generates GeoTIFF files automatically clipped and masked to your polygon's exact geometry.

Vector Grid Mode: Creates a GeoJSON grid where each ERA5 pixel is a polygon, allowing you to inspect values spatially as vector attributes.

Flexible Scheduling: Select specific date ranges and individual hours (UTC).

Smart Mapping: Automatically translates internal CDS variable codes (e.g., t2m) back to user-friendly names (e.g., 2m_temperature) in your outputs.

Asynchronous Processing: Uses dedicated workers to ensure QGIS remains responsive during large data downloads.

🛠️ Prerequisites
Before using the plugin, you must install the required Python libraries within your QGIS environment:

Open the QGIS Python Console.

Install the dependencies:

Python
# Run this in your OSGeo4W Shell or terminal
pip install cdsapi xarray netcdf4 geopandas pandas rasterio shapely
CDS API Configuration:

Create an account at Copernicus Climate Data Store.

Find your UID and API Key in your profile.

Create a file named .cdsapirc in your home folder (C:\Users\YourUser) with the following content:

Plaintext
url: https://cds.climate.copernicus.eu/api
key: YOUR_UID:YOUR_API_KEY
📂 Project Structure
Plaintext
era5_point_plugin/
├── worker/
│   ├── era5_worker.py          # Point extraction logic (CSV)
│   └── era5_polygon_worker.py  # Polygon/Raster processing logic
├── era5_extractor_dialog.py    # Main UI and QGIS integration
├── main.py                     # Plugin entry point
└── metadata.txt                # QGIS Plugin metadata
## 🛠️ Prerequisites & API Setup

To use this plugin, you need an account at the **Copernicus Climate Data Store (CDS)**.

1. **Register:** Create a free account at [https://cds.climate.copernicus.eu/](https://cds.climate.copernicus.eu/).
2. **Get your API Key:** * Login and go to your **Profile Page**: [https://cds.climate.copernicus.eu/profile?tab=profile](https://cds.climate.copernicus.eu/profile?tab=profile)
   * Scroll down to the **API Key** section. 
   * You will see a string containing your `UID` and `API Key` (e.g., `12345:abcde-1234-....`).
3. **Plugin Configuration:**
   * Inside the plugin, click on the **"⚙️ Setup CDS Credentials"** button.
   * Paste your key there. The plugin will automatically create the required `.cdsapirc` file in your user home folder.

📖 How to Use
Select Input: Choose a loaded Point or Polygon layer from the dropdown menu.

Define Temporal Range: Set your start and end dates and select the UTC hours required.

Choose Variables: Select one or more variables (e.g., Temperature, Precipitation, Soil Water).

Set Output: * For Points: The plugin generates a CSV file with original attributes preserved.

For Polygons: Choose between Raster (GeoTIFF) or Vector Grid (GeoJSON).

Run: Click "Run Extraction". The plugin will handle the API request, download the NetCDF, process the clip/mask, and load the results directly into your QGIS map canvas.

📋 Supported Variables
Includes all major ERA5-Land parameters:

Temperature: 2m Temperature, Skin Temperature, Soil Temperature (4 levels).

Hydrology: Total Precipitation, Evaporation, Runoff, Soil Water Content.

Solar/Wind: Solar Radiation, Thermal Radiation, 10m Wind Components (u/v).

Vegetation: Leaf Area Index (high/low vegetation).

Technical Note: ERA5-Land provides data at a native resolution of ~0.1° (~11km). When using the "Vector Grid" mode, the plugin calculates the exact intersection of these 11km pixels with your study area, ensuring scientific integrity without artificial interpolation.