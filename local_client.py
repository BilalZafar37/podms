from flask import Flask, request, jsonify
import requests
import pyinsane2
from pyinsane2 import Scanner
# from PIL import Image
# import os
import logging
# import sys
import io

app = Flask(__name__)

logging.getLogger('pyinsane2').setLevel(logging.ERROR)
# sys.stderr = open(os.devnull, 'w')


def initialize_scanner_get_images():
    pyinsane2.init()
    devices = pyinsane2.get_devices()
    if len(devices) == 0:
        return None

    try:
        scanner: Scanner = devices[0]
    except:
        message = "Unplug and replug the scanner or try a PC restart"
        return message

    # Check available sources and set the feeder source if available
    if 'source' in scanner.options:
        available_sources = scanner.options['source'].constraint
        feeder_sources = [s for s in available_sources if 'Feeder' in s]
        if feeder_sources:
            scanner.options['source'].value = feeder_sources[0]
            print(f"Feeder source set to {feeder_sources[0]}")
        else:
            raise Exception("Feeder source not available for this scanner")
    else:
        raise Exception("Source option not available for this scanner")
    
    # Set scanner resolution
    if 'resolution' in scanner.options:
        scanner.options['resolution'].value = 200

    scan_session = scanner.scan(multiple=True)
    images2 = []
    try:
        while True:
            try:
                scan_session.scan.read()
            except EOFError:
                print("Got a page!")
            except StopIteration:
                print("Document feeder is now empty.")
                break  # Exit the while loop when StopIteration is caught
    except Exception as e:
        print(f"An error occurred: {e}")

    # Process the scanned images
    if not scan_session.images:
        return None
    
    for idx in range(len(scan_session.images)):
        image = scan_session.images[idx]
        images2.append(image)
        print(f"Appended image {idx}")

    pyinsane2.exit()
    return images2


# def save_images(username, images, directory='./scanned_images'):
#     if not os.path.exists(directory):
#         os.makedirs(directory)
#     image_paths = []
#     for i, image in enumerate(images):
#         path = directory + f'/{username}_image_{i}.png'
#         image.save(path)
#         image_paths.append(path)
#     print("SAVED SAVED SAVED SAVED SAVED SAVED")
#     return image_paths

# def upload_images(image_paths, server_url):
#     uploaded_files = []
#     for image_path in image_paths:
#         with open(image_path, 'rb') as f:
#             files = {'file': f}
#             response = requests.post(server_url, files=files)
#             if response.status_code == 200:
#                 uploaded_files.append(image_path)
#                 print(f"Uploaded {image_path}: {response.status_code}")
#             else:
#                 print(f"Failed to upload {image_path}: {response.status_code}")
#                 print(response.text)
#     return uploaded_files

def upload_images(images, server_url, username):
    uploaded_files = []
    for i, image in enumerate(images):
        # Get raw image data
        with io.BytesIO() as output:
            image.save(output, format="PNG")  # Save the image to the output stream as PNG
            output.seek(0)
            files = {'file': (f'{username}_image_{i}.png', output, 'image/png')}
            
            try:
                response = requests.post(server_url, files=files, timeout=(10, 3000))
            except requests.Timeout:
                print("The request timed out. Retrying....")
                response = requests.post(server_url, files=files, timeout=(10, 3000))
                print("Connected !!")
            except requests.RequestException as e:
                print(f"An error occurred in posting files: {e}")

            if response.status_code == 200:
                uploaded_files.append(f'{username}_image_{i}.png')
                print(f"Uploaded {username}_image_{i}.png: {response.status_code}")
            else:
                print(f"Failed to upload {username}_image_{i}.png: {response.status_code}")
                print(response.text)
    return uploaded_files

@app.route('/scan', methods=['POST'])
def scan():
    server_url = request.json['server_url']
    username = request.json['username']
    print("Server is: " + str(server_url))
    images = initialize_scanner_get_images()

    if images is None:
        return jsonify({"status": "error", "message": "Please ensure the Scanner is ON and has papers."})
    
    if isinstance(images, str):
        return jsonify({"status": "error", "message": images})
    
    # image_paths = save_images(username, images)
    upload_images(images, server_url, username)
    
    response = requests.post(server_url, data={"uploaded_files": 'uploaded_files'})
    # print(server_url)
    return jsonify({"status": "Success", "message": "Scan Complete"})

@app.route('/test', methods=['GET', 'POST'])
def test():
    try:
        pyinsane2.init()
        devices = pyinsane2.get_devices()
        pyinsane2.exit()
        if len(devices) == 0:
            return jsonify({"status": "success","message":"App working Scanner is not Connected properly"})
        return jsonify({"status": "success","message":"App working Scanner Connected"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0' , port=5001)  # Run the local server on port 5001
