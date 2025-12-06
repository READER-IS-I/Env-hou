
import os
from rio_tiler.io import Reader
from rio_tiler.profiles import img_profiles

class TilerService:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    def get_tile(self, job_id, layer_name, z, x, y):
        """
        根据 job_id 和 layer_name 读取 COG 文件并切片
        """
        # 映射 layer 名称到文件名
        filename_map = {
            "ndvi": "ndvi_cog.tif",
            "biomass": "biomass_cog.tif",
            "carbon": "carbon_cog.tif"
        }
        
        filename = filename_map.get(layer_name)
        if not filename:
            raise FileNotFoundError("Unknown layer")

        file_path = os.path.join(self.data_dir, job_id, filename)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # 使用 Rio-Tiler 读取
        with Reader(file_path) as cog:
            # 读取瓦片
            img = cog.tile(x, y, z)
            
            # 渲染配置
            # NDVI 通常使用 RdYlGn 颜色表，Biomass 使用 Viridis 等
            colormap = None
            if layer_name == 'ndvi':
                # 重缩放 NDVI [-1, 1] 到 byte，并应用 colormap
                # 这里简单处理，前端 Leaflet 其实可以直接渲染灰度或者我们在这里渲染成 RGB PNG
                render_params = {"rescale": "-1,1", "colormap_name": "rdylgn"}
            elif layer_name == 'biomass':
                # 假设生物量范围 0-500
                render_params = {"rescale": "0,500", "colormap_name": "viridis"}
            elif layer_name == 'carbon':
                 render_params = {"rescale": "0,250", "colormap_name": "magma"}
            else:
                render_params = {}

            # 渲染为 PNG 格式二进制
            content = img.render(img_format="PNG", **render_params)
            return content