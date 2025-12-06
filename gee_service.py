import ee
import os
import requests
import zipfile
import io

# 无论是使用服务账号还是本地认证，都需要先初始化
try:
    ee.Initialize()
except Exception:
    # 实际部署时这里需要处理认证逻辑
    print("Warning: GEE not initialized. Ensure credentials are set.")

def export_data(aoi_geojson, date_range, output_dir):
    """
    从 GEE 导出 Sentinel-2 和 DEM 数据到本地
    注意：对于大区域，建议导出到 Google Drive/Cloud Storage，这里为了演示使用 getDownloadURL
    """
    region = ee.Geometry(aoi_geojson)
    
    # 1. 获取 Sentinel-2 数据 (去云处理后的合成)
    s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
        .filterBounds(region) \
        .filterDate(date_range[0], date_range[1]) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \
        .median() \
        .select(['B4', 'B8', 'B2', 'B3']) # Red, NIR, Blue, Green
    
    # 2. 获取 DEM 数据
    dem = ee.Image('USGS/SRTMGL1_003').clip(region)
    
    # 导出函数 (辅助)
    def download_image(ee_img, name, bands):
        url = ee_img.select(bands).getDownloadURL({
            'scale': 10, # S2 分辨率
            'crs': 'EPSG:4326',
            'region': region,
            'format': 'GEO_TIFF'
        })
        response = requests.get(url)
        filepath = os.path.join(output_dir, f"{name}.tif")
        with open(filepath, 'wb') as f:
            f.write(response.content)
        return filepath

    print("Downloading Sentinel-2 data...")
    s2_path = download_image(s2, "s2_multiband", ['B4', 'B8', 'B2', 'B3'])
    
    print("Downloading DEM data...")
    # SRTM 原始分辨率是 30m，这里为了对齐重采样到 10m 或者保持 30m
    dem_url = dem.getDownloadURL({
        'scale': 30, 
        'crs': 'EPSG:4326',
        'region': region,
        'format': 'GEO_TIFF'
    })
    dem_path = os.path.join(output_dir, "dem.tif")
    with open(dem_path, 'wb') as f:
        f.write(requests.get(dem_url).content)

    return {
        "s2_bands": s2_path,
        "dem": dem_path
    }