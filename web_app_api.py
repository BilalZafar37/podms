from flask import Flask
from flask import jsonify
import requests

app = Flask(__name__)


@app.route('/trigger_scan', methods=['GET', 'POST'])
def trigger_scan():
    local_client_url = 'http://localhost:5001/scan'  # Local client application URL
    server_url = 'http://127.0.0.1:5000/'  # Server URL to upload scanned images
    try:
        response = requests.post(local_client_url, json={'server_url': server_url})
        data = response.json()
        if data['status'] == 'success':
            return jsonify({"status": "success", "uploaded_files": data['uploaded_files']})
        else:
            return jsonify({"status": "error", "message": data['message']})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/test_printer', methods=['GET', 'POST'])
def test_printer():
    local_client_url = 'http://localhost:5001/scan'  # Local client application URL
    server_url = 'http://127.0.0.1:5000/'  # Server URL to upload scanned images

    response = requests.post(local_client_url, json={'server_url': server_url})
    data = response.json()
    if data['status'] == 'success':
        return True
    
if __name__ == '__main__':
    app.run(debug=True)