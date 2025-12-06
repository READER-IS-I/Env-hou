import os
from flask_cors import CORS
from flask import Flask, jsonify, request, send_file, Response
from celery import Celery
from tiler import TilerService
import tasks

app = Flask(__name__)
CORS(app)
# 配置 Celery
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# 初始化瓦片服务
tiler_service = TilerService(data_dir='./storage')

@app.route('/api/v1/analysis', methods=['POST'])
def trigger_analysis():
    """
    触发新分析任务
    Payload: { "aoi": {geojson_geometry}, "date_range": ["2023-01-01", "2023-06-01"] }
    """
    data = request.json
    if not data or 'aoi' not in data:
        return jsonify({"error": "Missing AOI data"}), 400

    # 启动异步任务
    task = tasks.run_full_pipeline.apply_async(args=[data])
    
    return jsonify({
        "job_id": task.id,
        "status": "processing",
        "message": "Analysis pipeline started"
    }), 202

@app.route('/api/v1/analysis/<job_id>', methods=['GET'])
def get_analysis_status(job_id):
    """查询任务状态和结果"""
    task = tasks.run_full_pipeline.AsyncResult(job_id)
    
    if task.state == 'PENDING':
        response = {"state": "PENDING", "status": "Task is waiting for execution"}
    elif task.state == 'STARTED':
        response = {"state": "STARTED", "status": "Task is currently running"}
    elif task.state == 'SUCCESS':
        response = {
            "state": "SUCCESS", 
            "result": task.result  # 包含 layers 的 tile_url
        }
    elif task.state == 'FAILURE':
        response = {"state": "FAILURE", "error": str(task.info)}
    else:
        response = {"state": task.state}
        
    return jsonify(response)

@app.route('/api/v1/tiles/<job_id>/<layer>/<int:z>/<int:x>/<int:y>.png', methods=['GET'])
def get_tile(job_id, layer, z, x, y):
    """
    返回瓦片
    layer: 'ndvi', 'biomass', 'carbon'
    job_id: 任务ID (对应存储目录)
    """
    try:
        # 获取瓦片二进制数据
        tile_data = tiler_service.get_tile(job_id, layer, z, x, y)
        if tile_data:
            return Response(tile_data, mimetype='image/png')
        else:
            return jsonify({"error": "Tile generation failed"}), 404
    except FileNotFoundError:
        return jsonify({"error": "Layer not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # 确保存储目录存在
    os.makedirs('./storage', exist_ok=True)
    app.run(debug=True, port=5000)