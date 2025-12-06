import json
import tempfile
import uuid
import zipfile
from pathlib import Path

import geopandas as gpd
from celery import Celery
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

import tasks
from tiler import TilerService


BASE_DATA_DIR = Path("data")
AOI_DIR = BASE_DATA_DIR / "aoi"
COG_DIR = BASE_DATA_DIR / "cog"

app = Flask(__name__)
CORS(app)

app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
app.config["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/0"

celery = Celery(app.name, broker=app.config["CELERY_BROKER_URL"])
celery.conf.update(app.config)

tiler_service = TilerService(data_dir=COG_DIR)


def _load_gdf_from_upload(file_storage) -> gpd.GeoDataFrame:
    """Load uploaded AOI file (zip shp or geojson) into a GeoDataFrame."""
    filename = (file_storage.filename or "").lower()
    if not filename:
        raise ValueError("Missing filename")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        if filename.endswith(".zip"):
            tmp_zip = tmpdir_path / filename
            file_storage.save(tmp_zip)
            extract_dir = tmpdir_path / "unzipped"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(extract_dir)
            shapefiles = list(extract_dir.rglob("*.shp"))
            if not shapefiles:
                raise ValueError("No .shp found inside zip")
            gdf = gpd.read_file(shapefiles[0])
        elif filename.endswith(".geojson") or filename.endswith(".json"):
            tmp_geojson = tmpdir_path / filename
            file_storage.save(tmp_geojson)
            gdf = gpd.read_file(tmp_geojson)
        else:
            raise ValueError("Unsupported file type. Use zip (SHP) or GeoJSON.")

    if gdf.empty:
        raise ValueError("AOI file contains no features")
    return gdf


@app.route("/api/v1/aoi/upload", methods=["POST"])
def upload_aoi():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "Missing file"}), 400

    try:
        gdf = _load_gdf_from_upload(file)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        gdf_4326 = gdf.to_crs("EPSG:4326")

        area_km2 = float(gdf_4326.to_crs("EPSG:3857").area.sum() / 1e6)
        if area_km2 > 100:
            return jsonify({"error": "AOI area exceeds 100 km²", "area_km2": area_km2}), 400

        aoi_geojson = json.loads(gdf_4326.to_json())
        aoi_id = str(uuid.uuid4())
        AOI_DIR.mkdir(parents=True, exist_ok=True)
        with open(AOI_DIR / f"{aoi_id}.geojson", "w", encoding="utf-8") as f:
            json.dump(aoi_geojson, f)

        return jsonify({"aoi_id": aoi_id, "geojson": aoi_geojson, "area_km2": area_km2}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to process AOI: {e}"}), 500


@app.route("/api/v1/analysis", methods=["POST"])
def trigger_analysis():
    data = request.get_json(silent=True) or {}
    required = ["aoi_id", "start", "end"]
    if any(field not in data for field in required):
        return jsonify({"error": "aoi_id, start, end are required"}), 400

    aoi_path = AOI_DIR / f"{data['aoi_id']}.geojson"
    if not aoi_path.exists():
        return jsonify({"error": "AOI not found"}), 404

    payload = {
        "aoi_id": data["aoi_id"],
        "start": data["start"],
        "end": data["end"],
        "layers": data.get("layers", ["ndvi", "biomass", "carbon"]),
    }

    task = tasks.run_pipeline.apply_async(args=[payload])
    return jsonify({"job_id": task.id, "status": "processing", "message": "Analysis pipeline started"}), 202


@app.route("/api/v1/analysis/<job_id>", methods=["GET"])
def get_analysis_status(job_id):
    task = tasks.run_pipeline.AsyncResult(job_id)

    if task.state == "PENDING":
        response = {"state": "PENDING", "status": "Task is waiting for execution"}
    elif task.state == "STARTED":
        response = {"state": "STARTED", "status": "Task is currently running"}
    elif task.state == "SUCCESS":
        response = {"state": "SUCCESS", "result": task.result}
    elif task.state == "FAILURE":
        response = {"state": "FAILURE", "error": str(task.info)}
    else:
        response = {"state": task.state}

    return jsonify(response)


@app.route("/tiles/<layer>/<job_id>/<int:z>/<int:x>/<int:y>.png", methods=["GET"])
def get_tile(layer, job_id, z, x, y):
    try:
        tile_data = tiler_service.get_tile(job_id, layer, z, x, y)
        if tile_data:
            return Response(tile_data, mimetype="image/png")
        return jsonify({"error": "Tile generation failed"}), 404
    except FileNotFoundError:
        return jsonify({"error": "Layer not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    COG_DIR.mkdir(parents=True, exist_ok=True)
    AOI_DIR.mkdir(parents=True, exist_ok=True)
    app.run(debug=True, port=5000)
