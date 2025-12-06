import numpy as np
import rasterio
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles


def calculate_ndvi(input_tif, output_tif):
    """
    Compute NDVI from a multiband Sentinel-2 GeoTIFF (band 1=Red, 2=NIR).
    """
    with rasterio.open(input_tif) as src:
        red = src.read(1).astype(float)
        nir = src.read(2).astype(float)
        profile = src.profile

    ndvi = np.where((nir + red) == 0, 0, (nir - red) / (nir + red))
    profile.update(dtype=rasterio.float32, count=1, driver="GTiff")

    with rasterio.open(output_tif, "w", **profile) as dst:
        dst.write(ndvi.astype(rasterio.float32), 1)


def to_cog(input_path, output_path):
    """
    Convert a GeoTIFF to COG for efficient tiling.
    """
    dst_profile = cog_profiles.get("deflate")
    cog_translate(str(input_path), str(output_path), dst_profile, in_memory=True, quiet=True)


def get_stats(tif_path):
    """Return the mean value of the raster (ignoring nodata)."""
    with rasterio.open(str(tif_path)) as src:
        data = src.read(1, masked=True)
        return float(data.mean())


def get_sum(tif_path):
    """Return the sum of raster values (ignoring nodata)."""
    with rasterio.open(str(tif_path)) as src:
        data = src.read(1, masked=True)
        return float(data.sum())
