import numpy as np
import rasterio


def compute_carbon(biomass_path, output_path, factor=0.47):
    """
    Carbon stock is approximated as AGB * factor.
    """
    with rasterio.open(str(biomass_path)) as src:
        biomass = src.read(1, masked=True)
        profile = src.profile

    carbon = (biomass * factor).filled(0).astype(np.float32)
    profile.update(dtype="float32", count=1, driver="GTiff")

    with rasterio.open(str(output_path), "w", **profile) as dst:
        dst.write(carbon, 1)
