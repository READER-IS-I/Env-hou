import rasterio
import numpy as np
from rasterio.io import MemoryFile
from rasterio.enums import Resampling
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

def calculate_ndvi(input_tif, output_tif):
    """
    读取 Sentinel-2 (B4=Red, B8=NIR)，计算 NDVI
    假设输入的 input_tif 波段顺序为: 1:Red, 2:NIR, 3:Blue, 4:Green 
    (对应 gee_service 中的 ['B4', 'B8', 'B2', 'B3'])
    """
    with rasterio.open(input_tif) as src:
        red = src.read(1).astype(float)
        nir = src.read(2).astype(float)
        profile = src.profile

    # 避免除以零
    ndvi = np.where(
        (nir + red) == 0, 
        0, 
        (nir - red) / (nir + red)
    )
    
    # 更新元数据，写入单波段
    profile.update(dtype=rasterio.float32, count=1, driver='GTiff')
    
    with rasterio.open(output_tif, 'w', **profile) as dst:
        dst.write(ndvi.astype(rasterio.float32), 1)

def to_cog(input_path, output_path):
    """
    将普通 GeoTIFF 转换为 Cloud Optimized GeoTIFF (COG)
    这对快速切片至关重要
    """
    dst_profile = cog_profiles.get("deflate")
    
    # 使用 rio-cogeo 进行转换
    cog_translate(
        input_path,
        output_path,
        dst_profile,
        in_memory=True,
        quiet=True
    )

def get_stats(tif_path):
    """计算简单的统计数据"""
    with rasterio.open(tif_path) as src:
        data = src.read(1, masked=True) # 使用 masked array 忽略 nodata
        return float(data.mean())

def get_sum(tif_path):
    """计算总和"""
    with rasterio.open(tif_path) as src:
        data = src.read(1, masked=True)
        # 假设每个像素代表面积，这里简单返回像素值总和
        # 实际项目中需要根据分辨率(resolution)计算真实公顷数
        return float(data.sum())