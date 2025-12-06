from pathlib import Path

from rio_tiler.io import Reader


class TilerService:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def get_tile(self, job_id, layer_name, z, x, y):
        """
        Read a COG for the given layer/job and render a PNG tile.
        """
        filename_map = {"ndvi": "ndvi.tif", "biomass": "biomass.tif", "carbon": "carbon.tif"}

        filename = filename_map.get(layer_name)
        if not filename:
            raise FileNotFoundError("Unknown layer")

        file_path = self.data_dir / job_id / filename
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with Reader(file_path) as cog:
            img = cog.tile(x, y, z)
            if layer_name == "ndvi":
                render_params = {"rescale": "-1,1", "colormap_name": "rdylgn"}
            elif layer_name == "biomass":
                render_params = {"rescale": "0,500", "colormap_name": "viridis"}
            elif layer_name == "carbon":
                render_params = {"rescale": "0,250", "colormap_name": "magma"}
            else:
                render_params = {}

            return img.render(img_format="PNG", **render_params)
