from flask import Flask, request, jsonify
import requests
import pyinsane2
from PIL import Image
import os

app = Flask(__name__)

def initialize_scanner_get_images():
    pyinsane2.init()
    devices = pyinsane2.get_devices()
    if len(devices) == 0:
        raise Exception("No scanner found")
    scanner = devices[0]
    available_sources = scanner.options['source'].constraint
    feeder_source = next((source for source in available_sources if 'Feeder' in source), None)
    if feeder_source:
        scanner.options['source'].value = feeder_source
    else:
        raise Exception(f"Feeder not available. Available sources: {available_sources}")
    
    scan_session = scanner.scan(multiple=False)
    # images = []
    while True:
        try:
            scan_session.scan.read()
        except EOFError:
            break
    return scan_session.images

def save_images(images, directory='./scanned_images'):
    if not os.path.exists(directory):
        os.makedirs(directory)
    image_paths = []
    for i, image in enumerate(images):
        path = os.path.join(directory, f'scanned_image_{i}.png')
        image.save(path)
        image_paths.append(path)
    return image_paths

def upload_images(image_paths, server_url):
    uploaded_files = []
    for image_path in image_paths:
        with open(image_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(server_url, files=files)
            if response.status_code == 200:
                uploaded_files.append(image_path)
            print(f"Uploaded {image_path}: {response.status_code}")
    return uploaded_files

@app.route('/scan', methods=['POST'])
def scan():
    uploaded_files = []
    try:
        server_url = request.json['server_url']
        try:
            while True:
                images = initialize_scanner_get_images()
                image_paths = save_images(images)
                uploaded_files.extend(upload_images(image_paths, server_url))
        except StopIteration:
            return jsonify({"status": "success", "uploaded_files": uploaded_files})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/test', methods=['GET', 'POST'])
def test():
    try:
        pyinsane2.init()
        devices = pyinsane2.get_devices()
        if len(devices) == 0:
            return jsonify({"status": "success","message":"App working Scanner is not Connected properly"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(port=5001)  # Run the local server on port 5001
