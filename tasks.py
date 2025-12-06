import os
import json
from celery import Celery
import gee_service
import raster_ops
import biomass_model
import carbon_calc

# 初始化 Celery (必须与 app.py 配置一致)
celery = Celery('app', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')

BASE_STORAGE = './storage'

@celery.task(bind=True)
def run_full_pipeline(self, payload):
    """
    执行完整的分析管道
    """
    job_id = self.request.id
    job_dir = os.path.join(BASE_STORAGE, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    aoi = payload.get('aoi')
    date_range = payload.get('date_range', ['2023-01-01', '2023-12-31'])
    
    self.update_state(state='STARTED', meta={'step': 'Downloading GEE Data'})

    # 1. GEE 导出 (Sentinel-2 & DEM)
    # 这里的 paths 返回的是本地 GeoTIFF 的路径
    raw_paths = gee_service.export_data(aoi, date_range, job_dir)
    
    results = {}
    
    # 2. 计算 NDVI 并生成 COG
    self.update_state(state='STARTED', meta={'step': 'Processing NDVI'})
    ndvi_path = os.path.join(job_dir, 'ndvi.tif')
    raster_ops.calculate_ndvi(raw_paths['s2_bands'], ndvi_path)
    # 转换为 COG 以便切片
    ndvi_cog_path = os.path.join(job_dir, 'ndvi_cog.tif')
    raster_ops.to_cog(ndvi_path, ndvi_cog_path)
    
    # 3. 生物量模型预测 (Biomass)
    self.update_state(state='STARTED', meta={'step': 'Running Biomass Model'})
    biomass_path = os.path.join(job_dir, 'biomass.tif')
    # 输入通常需要所有波段和DEM
    biomass_model.predict(raw_paths, biomass_path)
    biomass_cog_path = os.path.join(job_dir, 'biomass_cog.tif')
    raster_ops.to_cog(biomass_path, biomass_cog_path)

    # 4. 碳储量计算 (Carbon)
    self.update_state(state='STARTED', meta={'step': 'Calculating Carbon'})
    carbon_path = os.path.join(job_dir, 'carbon.tif')
    carbon_calc.compute_carbon(biomass_path, carbon_path)
    carbon_cog_path = os.path.join(job_dir, 'carbon_cog.tif')
    raster_ops.to_cog(carbon_path, carbon_cog_path)

    # 5. 计算统计指标
    metrics = {
        "mean_ndvi": raster_ops.get_stats(ndvi_path),
        "total_carbon": raster_ops.get_sum(carbon_path)
    }

    # 构建返回的前端使用的 URL 模板
    base_url = "/api/v1/tiles"
    
    return {
        "job_id": job_id,
        "layers": {
            "ndvi": f"{base_url}/{job_id}/ndvi/{{z}}/{{x}}/{{y}}.png",
            "biomass": f"{base_url}/{job_id}/biomass/{{z}}/{{x}}/{{y}}.png",
            "carbon": f"{base_url}/{job_id}/carbon/{{z}}/{{x}}/{{y}}.png"
        },
        "metrics": metrics
    }