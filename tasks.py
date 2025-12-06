from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import planetary_computer as pc
import rasterio
import rioxarray  # noqa: F401
from celery import Celery
from pystac_client import Client

import biomass_model
import carbon_calc
import raster_ops


celery = Celery("app", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")

DATA_DIR = Path("data")
AOI_DIR = DATA_DIR / "aoi"
COG_DIR = DATA_DIR / "cog"
MPC_CATALOG = "https://planetarycomputer.microsoft.com/api/stac/v1"


def _load_aoi(aoi_id: str) -> gpd.GeoDataFrame:
    aoi_path = AOI_DIR / f"{aoi_id}.geojson"
    if not aoi_path.exists():
        raise FileNotFoundError(f"AOI not found: {aoi_id}")

    gdf = gpd.read_file(aoi_path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs("EPSG:4326")


def _search_first_item(catalog: Client, collection: str, geom: dict, time_range: Optional[str]):
    search = catalog.search(
        collections=[collection],
        intersects=geom,
        datetime=time_range,
        sortby=[{"field": "properties.datetime", "direction": "desc"}] if time_range else None,
        limit=1,
    )
    items = list(search.get_items())
    if not items:
        raise ValueError(f"No items found for {collection} within given AOI/time range")
    return items[0]


def _resolve_asset_key(item, candidates):
    for key in candidates:
        if key in item.assets:
            return key
    raise ValueError(f"No matching asset in item. Tried: {candidates}")


def _open_and_clip_asset(item, asset_key: str, geom: dict, target=None, target_crs="EPSG:3857", resolution=10):
    href = pc.sign(item.assets[asset_key].href)
    data = rioxarray.open_rasterio(href, masked=True)
    clipped = data.rio.clip([geom], from_disk=True)
    if target is not None:
        return clipped.rio.reproject_match(target)
    return clipped.rio.reproject(target_crs, resolution=resolution)


def _write_single_band(array: np.ndarray, reference_profile: dict, out_path: Path):
    profile = reference_profile.copy()
    profile.update(count=1, dtype="float32", driver="GTiff")
    with rasterio.open(str(out_path), "w", **profile) as dst:
        dst.write(array.astype(np.float32), 1)


@celery.task(bind=True)
def run_pipeline(self, payload: dict):
    job_id = self.request.id
    job_dir = COG_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    aoi_id = payload["aoi_id"]
    start = payload["start"]
    end = payload["end"]
    layers = payload.get("layers", ["ndvi", "biomass", "carbon"])

    gdf = _load_aoi(aoi_id)
    aoi_geom = gdf.geometry.unary_union.__geo_interface__

    catalog = Client.open(MPC_CATALOG)

    s2_item = _search_first_item(catalog, "sentinel-2-l2a", aoi_geom, f"{start}/{end}")
    s1_item = _search_first_item(catalog, "sentinel-1-grd", aoi_geom, f"{start}/{end}")
    dem_item = _search_first_item(catalog, "cop-dem-glo-30", aoi_geom, None)

    red = _open_and_clip_asset(s2_item, "B04", aoi_geom)
    nir = _open_and_clip_asset(s2_item, "B08", aoi_geom, target=red)
    vv = _open_and_clip_asset(s1_item, _resolve_asset_key(s1_item, ["VV", "vv"]), aoi_geom, target=red)
    vh = _open_and_clip_asset(s1_item, _resolve_asset_key(s1_item, ["VH", "vh"]), aoi_geom, target=red)
    dem = _open_and_clip_asset(dem_item, _resolve_asset_key(dem_item, ["data", "DEM", "dem"]), aoi_geom, target=red)

    red_arr = np.nan_to_num(red.squeeze().values, nan=0.0)
    nir_arr = np.nan_to_num(nir.squeeze().values, nan=0.0)

    results = {}

    if "ndvi" in layers:
        ndvi_arr = np.where((nir_arr + red_arr) == 0, 0, (nir_arr - red_arr) / (nir_arr + red_arr))
        ndvi_raw = job_dir / "ndvi_raw.tif"
        _write_single_band(ndvi_arr, red.rio.profile, ndvi_raw)
        ndvi_cog = job_dir / "ndvi.tif"
        raster_ops.to_cog(ndvi_raw, ndvi_cog)
        results["ndvi_path"] = ndvi_cog

    if "biomass" in layers or "carbon" in layers:
        vv_arr = np.nan_to_num(vv.squeeze().values, nan=0.0)
        vh_arr = np.nan_to_num(vh.squeeze().values, nan=0.0)
        dem_arr = np.nan_to_num(dem.squeeze().values, nan=0.0)
        stack = np.concatenate(
            [
                red_arr[np.newaxis, ...],
                nir_arr[np.newaxis, ...],
                vv_arr[np.newaxis, ...],
                vh_arr[np.newaxis, ...],
                dem_arr[np.newaxis, ...],
            ],
            axis=0,
        ).astype(np.float32)

        biomass_raw = job_dir / "biomass_raw.tif"
        biomass_model.predict_from_stack(stack, red.rio.profile, biomass_raw)
        biomass_cog = job_dir / "biomass.tif"
        raster_ops.to_cog(biomass_raw, biomass_cog)
        results["biomass_path"] = biomass_cog

        if "carbon" in layers:
            carbon_raw = job_dir / "carbon_raw.tif"
            carbon_calc.compute_carbon(biomass_cog, carbon_raw)
            carbon_cog = job_dir / "carbon.tif"
            raster_ops.to_cog(carbon_raw, carbon_cog)
            results["carbon_path"] = carbon_cog

    metrics = {}
    if "ndvi" in results:
        metrics["mean_ndvi"] = raster_ops.get_stats(results["ndvi_path"])
    if "carbon" in results:
        metrics["total_carbon"] = raster_ops.get_sum(results["carbon_path"])

    tile_base = "/tiles"
    layers_resp = {}
    if "ndvi" in layers:
        layers_resp["ndvi"] = f"{tile_base}/ndvi/{job_id}/{{z}}/{{x}}/{{y}}.png"
    if "biomass" in layers:
        layers_resp["biomass"] = f"{tile_base}/biomass/{job_id}/{{z}}/{{x}}/{{y}}.png"
    if "carbon" in layers:
        layers_resp["carbon"] = f"{tile_base}/carbon/{job_id}/{{z}}/{{x}}/{{y}}.png"

    return {"job_id": job_id, "layers": layers_resp, "metrics": metrics}
