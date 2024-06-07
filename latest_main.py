from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from db import db_connection
from sqlalchemy import text
import re
import pyinsane2
from pyzbar.pyzbar import decode
import pytesseract
pytesseract.pytesseract.tesseract_cmd ='D:\\tesseract\\tesseract.exe'
import cv2
import logging
import sys
import os
import numpy as np
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PIL import Image
import json
import requests
from datetime import datetime
import time

logging.getLogger('pyinsane2').setLevel(logging.ERROR)
sys.stderr = open(os.devnull, 'w')

app = Flask(__name__)
USER_FILE = 'users.json'
app.secret_key = 'wertyuiertyui45678'
# app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)



# Util FUNCTIONS
def create_pdf(image_paths, output_path):
    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter
    for image_path in image_paths:
        c.drawImage(image_path, 0, 0, width, height)
        c.showPage()
    c.save()

def reduce_image_quality(image_paths, quality=30): # TODO
    """
    Reduces the quality of the image.
    :param image_path: Path to the original image.
    :param quality: Quality to which the image should be reduced.
    :return: Path to the reduced quality image.
    """
    reduced_image_paths = []
    for path in image_paths:
        img = Image.open(path)
        reduced_image_path = f"reduced_{path}"
        
        # Save image with reduced quality
        img.save(reduced_image_path, quality=quality)

        reduced_image_paths.append(reduced_image_path)
    return reduced_image_paths

def cleanup_files(file_paths):
    for file_path in file_paths:
        try:
            os.remove(file_path)
            print(f"Deleted file: {file_path}")
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")

def load_users():
    with open(USER_FILE, 'r') as file:
        return json.load(file)['users']

def save_users(users):
    with open(USER_FILE, 'w') as file:
        json.dump({"users": users}, file, indent=4)

def initialize_scanner_get_images():
    # error = None
    pyinsane2.init()
    devices = pyinsane2.get_devices()
    if len(devices) == 0:
        raise Exception("No scanner found")

    scanner = devices[0]
    # available_sources = scanner.options['source'].constraint
    # feeder_source = next((source for source in available_sources if 'Feeder' in source), None)
    # if feeder_source:
    #     scanner.options['source'].value = feeder_source
    #     print("Feeder source set successfully")
    # else:
    #     raise Exception(f"Feeder not available. Available sources: {available_sources}")
    
    
    # scan_session = scanner.scan(multiple=True)
    images = []
    print("Scanner init")
    # time.sleep(10)
    while True:
        try:
            scan_session = scanner.scan(multiple=True)
            print("scanning")
            scan_session.scan.read()
            images.extend(scan_session.images)
            print(f"Scanned {len(scan_session.images)} images")
        except EOFError:
            print("EOF BREAK")
            break
    return images
    # while True:
    #     try:
    #         scan_session.scan.read()
    #     except EOFError:
    #         break
    # return scan_session.images

def mock_scanner_images():
     # './saved-docs/Delivery_Note_81505029-4.png',
        # './saved-docs/Delivery_Note_81505501-1.png',
        # './saved-docs/Delivery_Note_81505501-2.png',
        # './saved-docs/Delivery_Note_81505501-3.png',
        # './saved-docs/Delivery_Note_81505501-4.png',
        # './saved-docs/Delivery_Note_81505501-5.png',
        # './saved-docs/Delivery_Note_81505501-6.png',
        # './saved-docs/Delivery_Note_81507776-1.png',
        # './saved-docs/Delivery_Note_81507776-2.png',
    image_paths = [
        './saved-docs/Delivery_Note_81505029-1.png',
        './saved-docs/Delivery_Note_81505029-2.png',
        './saved-docs/Delivery_Note_81505029-3.png',
        './saved-docs/Delivery_Note_81502417-1.png',
        './saved-docs/Delivery_Note_81502417-2.png',
        './saved-docs/Delivery_Note_81505501-50.png'
    ]

    for image_path in image_paths:
        yield Image.open(image_path)

def extract_text(image):
    print("Extracting data with Tesseract...")
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    
    full_text = ""
    confidences = []

    print("Processing extracted data...")
    for i in range(len(data['text'])):
        text = data['text'][i]
        conf = int(data['conf'][i])
        # print(f"Detected text: {text}, Confidence: {conf}")
        if conf > 0:  # Exclude empty and low confidence results
            full_text += " " + text
            confidences.append(conf)

    return full_text.strip(), confidences

def is_blank_page(full_text, downloaded_img):
    if len(full_text)<10: 
        try:
            os.remove(downloaded_img)
            print("Blank Img detected and deleted")
        except:
            print("Blank Img not deleted")

        return True
    return False

def read_barcode(downloaded_img):
    img = cv2.imread(downloaded_img, cv2.IMREAD_GRAYSCALE)
    closed = cv2.morphologyEx(img, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 21)))
    dens = np.sum(img, axis=0)
    thresh = closed.copy()
    for idx, val in enumerate(dens):
        if val < 10800:
            thresh[:, idx] = 0
    _, thresh2 = cv2.threshold(thresh, 128, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    barcodes = decode(thresh2)
    if barcodes:
        for barcode in barcodes:
            x, y, w, h = barcode.rect
            new_barcode = barcode.data.decode('utf-8')
            print("=======================")
            print(f"New barcode detected : {new_barcode}")
            print("=======================")
            return new_barcode, (x, y, w, h)
    print("Barcode Not found")
    return None, None

def find_date(thresh2, x, y, w, h, i):
    # roi_x = x
    # roi_y = y - int(h * 0.1)
    # roi_w = (thresh2.shape[1] - roi_x - 20) // 2
    # roi_h = int(h * 1.8)
    # roi = thresh2[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
    roi_x = x
    roi_y = y - int(h * 0.2)  # Increase the top margin
    roi_w = (thresh2.shape[1] - roi_x - 20) // 2
    roi_h = int(h * 2.3)  # Increase the height multiplier
    roi = thresh2[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
    cropped_roi_path = f"static/img/processed/cropped_date_{i}.png"
    cv2.imwrite(cropped_roi_path, roi)
    print(f"Cropped Date image saved to {cropped_roi_path}")
    text = pytesseract.image_to_string(roi)
    print(text)
    date_pattern = re.compile(r'\d{2}\s*/\s*\d{2}\s*/\s*\d{4}')
    date_match = date_pattern.search(text)
    if date_match:
        print("DATE DATE DATE")
        pod_date = date_match.group(0)
        print(pod_date)
        # try:
        #     pod_date = datetime.strftime(date_match.group(0),"%d/%m/%Y")
        # except:
        #     print("Date not convertable")
        return date_match.group(), f'img/processed/cropped_date_{i}.png'
    
    # Get today's date
    today = datetime.today()

    # Format the date as dd/mm/yyyy
    formatted_date = today.strftime('%d/%m/%Y')

    return formatted_date, f'img/processed/cropped_date_{i}.png'

def extract_note_numbers(image_path, j):
    img = Image.open(image_path)
    # data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    # New
    # Calculate the height to crop
    width, height = img.size
    crop_height = int(height * 0.12)
    
    # Crop the image to remove the top 10%
    img = img.crop((0, crop_height, width, height))
    
    # Use the cropped image for OCR
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    # New

    n_boxes = len(data['level'])
    delivery_note_number = None
    sales_order_number = None
    delivery_note_img_path = None
    # sales_order_img_path = None
    delivery_note_img_path2 = None
    # sales_order_img_path2 = None

    pattern = re.compile(r"\d+")

    combined_text = ""
    combined_x1, combined_y1, combined_x2, combined_y2 = float('inf'), float('inf'), 0, 0

    print("Extracted data:")
    for i in range(n_boxes):
        text = data['text'][i]
        # text = text[10:]
        conf = int(data['conf'][i])
        (x, y, w, h) = (data['left'][i], data['top'][i], data['width'][i], data['height'][i])
        # print(text)
        if text and conf > 0:
            if text in ["Delivery", "Note", "No", "Sales", "Order"]:
                combined_text += text + " "
                combined_x1 = min(combined_x1, x)
                combined_y1 = min(combined_y1, y)
                combined_x2 = max(combined_x2, x + w)
                combined_y2 = max(combined_y2, y + h)
            elif combined_text.strip() in ["Delivery Note No", "Sales Order No"]:
                match = pattern.search(text)
                if match:
                    number = match.group(0)
                    combined_x2 = max(combined_x2, x + w)
                    combined_y2 = max(combined_y2, y + h)

                    # Look ahead to the next few boxes to complete the number
                    for k in range(1, 4):
                        if i + k < n_boxes:
                            next_text = data['text'][i + k]
                            next_x, next_y, next_w, next_h = (data['left'][i + k], data['top'][i + k], data['width'][i + k], data['height'][i + k])
                            next_match = pattern.search(next_text)
                            if next_match:
                                number += next_match.group(0)
                                combined_x2 = max(combined_x2, next_x + next_w)
                                combined_y2 = max(combined_y2, next_y + next_h)
                                if len(number) >= 8:
                                    number = number[:9]  
                                    # break

                    if combined_text.strip() == "Delivery Note No":
                        delivery_note_number = number
                        delivery_note_img_path = f"static/img/processed/cropped_dn_{j}.png"
                        delivery_note_img_path2 = f"img/processed/cropped_dn_{j}.png"
                        cropped_img = img.crop((combined_x1, combined_y1, combined_x2, combined_y2))
                        print(f"Saving cropped image to: {delivery_note_img_path}")
                        cropped_img.save(delivery_note_img_path)
                    # elif combined_text.strip() == "Sales Order No":
                    #     sales_order_number = number
                    #     sales_order_img_path = f"static/img/processed/cropped_so_{j}.png"
                    #     sales_order_img_path2 = f"img/processed/cropped_so_{j}.png"
                    #     cropped_img = img.crop((combined_x1, combined_y1, combined_x2, combined_y2))
                    #     print(f"Saving cropped image to: {sales_order_img_path}")
                    #     cropped_img.save(sales_order_img_path)

                    print("=================")
                    print(f"{combined_text.strip()}: {number}")
                    print("=================")
                    avg_confidence = conf
                    print(f"Match found - Coordinates: x1={combined_x1}, y1={combined_y1}, x2={combined_x2}, y2={combined_y2}")

                    combined_text = ""
                    combined_x1, combined_y1, combined_x2, combined_y2 = float('inf'), float('inf'), 0, 0
            else:
                combined_text = ""
                combined_x1, combined_y1, combined_x2, combined_y2 = float('inf'), float('inf'), 0, 0

    if delivery_note_number is None and sales_order_number is None:
        print("Pattern not found in the image data")
    elif delivery_note_number is None:
        print("Delivery Note is None")
    elif sales_order_number is None:
        sales_order_number = '00001111'
        print("Sales Order_number is None")

    return delivery_note_number, delivery_note_img_path2 #, sales_order_number, sales_order_img_path2




#Login SYSTEM
@app.route("/login", methods=['GET', 'POST'])
def login():
    if 'username' in session:
        # return redirect(url_for('home_page'))
        session.pop('username')
    if request.method == 'POST':
        user = request.form['username']
        password = request.form['password']
        users = load_users()
        for u in users:
            if u['username'] == user and u['password'] == password:
                session['role'] = u['role']
                session['username'] = user
                session['department'] = u['department']
                return redirect(url_for('home_page'))
        return render_template('sign-in.html', error="Invalid Credentials. Please try again.")
    return render_template('sign-in.html')

@app.route("/update-user", methods=['GET', 'POST'])
def update_user():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    if session['role'] == 'admin':
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            role = request.form['role']
            department = request.form['department']
            users = load_users()
            for u in users:
                if u['username'] == username:
                    u['password'] = password
                    u['role'] = role
                    u['department'] = department
                    save_users(users)
                    return jsonify({"status": "success", "message": "User updated successfully"})
            return jsonify({"status": "error", "message": "User not found"})
        return render_template('update-user.html')

@app.route("/all-pod")
@app.route("/")
def home_page():
    if 'username' in session:
        return render_template('all-pod.html')
    else:
        return redirect(url_for('login'))

@app.route('/scan-new-pod', methods=['POST', 'GET'])
def scan_pod_page():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    # barcode_list = [81398514, 81507776]
    # cropped_dn_img_path = ['img/croped_dn.png', 'img/croped_dn_2.png']
    # cropped_date_img_path = ['img/croped_date.png', 'img/croped_date_2.png']
    # dates = ['28/02/2023', '28/02/2023']

    # To run when form is submited and docs are scaned
    if request.method == 'POST':
        barcode_list, pdf_index, cropped_date_img_path, cropped_dn_img_path, avg_confidence_dn, extracted_dn, scaned_img_urls, dates= scan_document() #, cropped_so_img_path, extracted_so 
        return render_template(
            'scan-new-pod.html', 
            barcode_list=barcode_list, 
            pdf_index=pdf_index, 
            cropped_date_img_path=cropped_date_img_path, 
            cropped_dn_img_path=cropped_dn_img_path, 
            avg_confidence_dn=avg_confidence_dn, 
            extracted_dn=extracted_dn, 
            scaned_img_urls=scaned_img_urls, 
            dates=dates
            # cropped_so_img_path = cropped_so_img_path,
            # extracted_so = extracted_so
        )
    else:
        # To display normal page
         return render_template('scan-new-pod.html')

        # For testing
        # return render_template('scan-new-pod.html', barcode_list = barcode_list, cropped_dn_img_path = cropped_dn_img_path, cropped_date_img_path = cropped_date_img_path, dates = dates)
    
def scan_document():
    barcode_list = []
    scaned_img_urls = []
    current_pdf_pages = []
    cropped_date_img_path = []
    cropped_dn_img_path = []
    # cropped_so_img_path = []
    avg_confidence_dn = []
    extracted_dn = []
    # extracted_so = []
    current_barcode = None
    pdf_index = 1
    dates = [] 
    j = 0

    # Mocking scanner for testing
    # scan_session_images = list(mock_scanner_images())

    try:
        while True:
        # while j < len(scan_session_images):

            # Setup scanner and Get the scanned images
            scan_session_images = initialize_scanner_get_images()
            
            for i, image in enumerate(scan_session_images):
                print("For executed")
                j += 1
                downloaded_img = f"./saved-docs/DNscanned_document_{j}.png"
                image.save(downloaded_img)
                image = Image.open(downloaded_img)

                # Exterect text and confidence level from page
                full_text, confidences = extract_text(image)

                # # For blank page detection
                if is_blank_page(full_text, downloaded_img):
                    break
                
                print(f"Full extracted text: {len(full_text)}")

                # Get delivery note number from text #, sales_order_number, sales_order_img_path2 TODO
                delivery_note_number, cropped_dn_path = extract_note_numbers(downloaded_img, j) #full_text, confidences, 

                if delivery_note_number:
                    extracted_dn.append(delivery_note_number)
                    # avg_confidence_dn.append(avg_confidence) TODO
                    cropped_dn_img_path.append(cropped_dn_path)
                    # extracted_so.append(sales_order_number)
                    # cropped_so_img_path.append(sales_order_img_path2)

                # READING BARCODE
                new_barcode, barcode_rect = read_barcode(downloaded_img)
                
                # READING Date infront of barcode 
                if new_barcode:
                    x, y, w, h = barcode_rect
                    date, cropped_date_path = find_date(cv2.imread(downloaded_img, cv2.IMREAD_GRAYSCALE), x, y, w, h, j)
                    dates.append(date)
                    cropped_date_img_path.append(cropped_date_path)

                # PDF creation logic
                if new_barcode and new_barcode != current_barcode:
                    if current_pdf_pages:
                        pdf_path = f'./saved-docs/Delivery_Note_{current_barcode}.pdf'
                        # current_pdf_pages = reduce_image_quality(current_pdf_pages)
                        create_pdf(current_pdf_pages, pdf_path)
                        pdf_index += 1
                        current_pdf_pages = []
                    barcode_list.append(new_barcode)
                    current_barcode = new_barcode

                current_pdf_pages.append(downloaded_img)
                scaned_img_urls.append(downloaded_img)
            # pyinsane2.exit()
    except StopIteration:
        print("=======================")
        print("Document feeder is now empty.")
        print("=======================")
        
    # Create the last PDF if there are remaining pages
    if current_pdf_pages:
        pdf_path = f'./saved-docs/Delivery_Note_{current_barcode}.pdf'
        create_pdf(current_pdf_pages, pdf_path)
    
    # Clean up the scanned image files
    # cleanup_files(scaned_img_urls)

    return barcode_list, pdf_index, cropped_date_img_path, cropped_dn_img_path, avg_confidence_dn, extracted_dn, scaned_img_urls, dates #, cropped_so_img_path, extracted_so


@app.route('/upload-pod', methods=['POST'])
def upload_pod():
    created_at = datetime.now()
    status = 'pending'
    if request.method == 'POST':
        engine = db_connection()
        with engine.connect() as conn:
            for i in range(len(request.form)//3):  # Assuming 4 fields per entry (DN, Date, Include)
                if request.form.get(f'include{i}') == 'on':
                    dn = request.form.get(f'dn{i}')
                    # so = request.form.get(f'so{i}')
                    date = request.form.get(f'date{i}')
                    # date = '06/05/2024'
                    pdf_url = f'/static/pdfs/Delivery_Note_{dn}.pdf'
                    conn.execute(text("INSERT INTO dbo.dntable_ruh (dn, date, pdf_url, CreatedAt , Status) VALUES (:dn, :date, :pdf_url, :created_at, :status);"),
                                 {'dn': dn, 'date': date, 'pdf_url':pdf_url, 'created_at': created_at, 'status': status})
                    conn.commit()
                    print("Database updated. New Entry added")
            conn.close()
        return render_template('scan-new-pod.html', message="Data successfully uploaded.")
    return render_template('scan-new-pod.html')

@app.route('/all-pod', methods=['POST', 'GET'])
def all_pod():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    # notes = ['Delivery_Note_86332602.pdf']
    if request.method == 'POST':
        dn_input = request.form['DN']
        # so_input = request.form['SO']
        date_input = request.form['date']

        dn_list = [dn.strip() for dn in dn_input.split() if dn.strip()]
        # so_list = [so.strip() for so in so_input.split() if so.strip()]
        date_list = [date.strip() for date in date_input.split() if date.strip()]

        engine = db_connection()
        results = []

        with engine.connect() as conn:
            if dn_list:
                for dn in dn_list:
                    result = conn.execute(text("SELECT date, pdf_url FROM dbo.dntable_ruh WHERE dn = :dn"), {'dn': dn}).fetchone()
                    if result:
                        date = result[0]
                        pdf_url = result[1]
                        pdf_url = f'/static/pdfs/Delivery_Note_{dn}.pdf'
                        results.append({'dn': dn, 'date': date, 'pdf_url': pdf_url})
                    else:
                        results.append({'dn': dn, 'error': "DN number not found."})

            # if so_list:
            #     for so in so_list:
            #         result = conn.execute(text("SELECT date, pdf_url FROM dbo.dntable_ruh WHERE so = :so"), {'so': so}).fetchone()
            #         if result:
            #             date = result[0]
            #             pdf_url = result[1]
            #             results.append({'so': so, 'date': date, 'pdf_url': pdf_url})
            #         else:
            #             results.append({'so': so, 'error': "SO number not found."})

            if date_list:
                for date in date_list:
                    result = conn.execute(text("SELECT dn, date, pdf_url FROM dbo.dntable_ruh WHERE date = :date"), {'date': date}).fetchall()
                    for row in result:
                        dn, date, pdf_url = row
                        results.append({'dn': dn, 'date': date, 'pdf_url': pdf_url})
                        pdf_url = f'/static/pdfs/Delivery_Note_{dn}.pdf'
                    if not result:
                        results.append({'date': date, 'error': "Date not found."})

        return render_template('all-pod.html', results=results)

    return render_template('all-pod.html')

@app.route('/printer_settings', methods=['POST', 'GET'])
def printer_settings():
    if request.method == 'POST' and 'scan-button' in request.form:
        local_client_url = 'http://localhost:5001/test'  # Local client application URL
        server_url = 'http://127.0.0.1:5000/'  # Server URL to upload scanned images

        response = requests.post(local_client_url, json={'server_url': server_url})
        data = response.json()
        print(data['status'])
        if data['status'] == 'success':
            working = True
            return render_template('printer_settings.html', working=working)
        
    return render_template('printer_settings.html')

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


if __name__ == '__main__':
    app.run(debug=True)




















# def extract_delivery_note_number(image_path, j):
#     img = Image.open(image_path)
#     data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

#     n_boxes = len(data['level'])
#     delivery_note_number = None
#     avg_confidence = None
#     cropped_img_path = None

#     pattern = re.compile(r"\d+")

#     combined_text = ""
#     combined_x1, combined_y1, combined_x2, combined_y2 = float('inf'), float('inf'), 0, 0

#     # print("Extracted data:")
#     for i in range(n_boxes):
#         text = data['text'][i]
#         conf = int(data['conf'][i])
#         (x, y, w, h) = (data['left'][i], data['top'][i], data['width'][i], data['height'][i])

#         # if text:
#             # print(f"Text: {text}, Confidence: {conf}, Coordinates: (x={x}, y={y}, w={w}, h={h})")

#         if text and conf > 0:
#             if text in ["Delivery", "Note", "No"]:
#                 combined_text += text + " "
#                 combined_x1 = min(combined_x1, x)
#                 combined_y1 = min(combined_y1, y)
#                 combined_x2 = max(combined_x2, x + w)
#                 combined_y2 = max(combined_y2, y + h)
#             elif combined_text.strip() == "Delivery Note No":
#                 match = pattern.search(text)
#                 if match:
#                     delivery_note_number = match.group(0)
#                     combined_x2 = max(combined_x2, x + w)
#                     combined_y2 = max(combined_y2, y + h)

#                     # Look ahead to the next few boxes to complete the number
#                     for k in range(1, 4):
#                         if i + k < n_boxes:
#                             next_text = data['text'][i + k]
#                             next_x, next_y, next_w, next_h = (data['left'][i + k], data['top'][i + k], data['width'][i + k], data['height'][i + k])
#                             next_match = pattern.search(next_text)
#                             if next_match:
#                                 delivery_note_number += next_match.group(0)
#                                 combined_x2 = max(combined_x2, next_x + next_w)
#                                 combined_y2 = max(combined_y2, next_y + next_h)
#                                 if len(delivery_note_number) >= 8:
#                                     break

#                     print("=================")
#                     print(f"Delivery Note No: {delivery_note_number}")
#                     print("=================")
#                     avg_confidence = conf
#                     print(f"Match found - Coordinates: x1={combined_x1}, y1={combined_y1}, x2={combined_x2}, y2={combined_y2}")

#                     # Crop the image using the combined bounding box
#                     cropped_img = img.crop((combined_x1, combined_y1, combined_x2, combined_y2))
#                     cropped_img_path = f"static/img/processed/cropped_dn_{j}.png"
#                     print(f"Saving cropped image to: {cropped_img_path}")
#                     cropped_img.save(cropped_img_path)
#                     return delivery_note_number, avg_confidence, f'img/processed/cropped_dn_{j}.png'
#             else:
#                 combined_text = ""
#                 combined_x1, combined_y1, combined_x2, combined_y2 = float('inf'), float('inf'), 0, 0

#     if delivery_note_number is None:
#         print("Delivery Note No pattern not found in the image data")

#     return None, None, None