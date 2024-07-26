import os
import sys
import re
import json
# import logging
# from turtle import down
import requests
import threading
from datetime import datetime, timedelta, date

import cv2
import numpy as np
import pytesseract
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from PIL import Image
from pyzbar.pyzbar import decode
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from skimage import io
from skimage.color import rgb2gray, rgba2rgb
from skimage.transform import rotate
from sqlalchemy import text

from deskew import determine_skew
from db import db_connection

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

pytesseract.pytesseract.tesseract_cmd = 'D:\\tesseract\\tesseract.exe'

# sys.stderr = open(os.devnull, 'w')

app = Flask(__name__)
USER_FILE = './users.json'
app.secret_key = 'wertyuiertyui45678'

# Thread-safe event to signal the flag
flag_received = threading.Event()



# Util FUNCTIONS
def create_pdf(image_paths, output_path):
    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter
    for image_path in image_paths:
        c.drawImage(image_path, 0, 0, width, height)
        c.showPage()
    c.save()

    # Track the created PDF in the session
    if 'created_pdfs' not in session:
        session['created_pdfs'] = []
    session['created_pdfs'].append(output_path)

def reduce_image_quality(image_paths, quality=1):
    """
    Reduces the quality of the image.
    :param image_paths: List of paths to the original images.
    :param quality: Quality to which the image should be reduced (1-100).
    :return: List of paths to the reduced quality images.
    """
    reduced_image_paths = []
    for path in image_paths:
        img = Image.open(path)
        reduced_image_path = f"reduced_{path}"
        
        # Save image with reduced quality (for JPEG images)
        if img.format == 'JPEG':
            img.save(reduced_image_path, quality=quality)
        else:
            # Convert to JPEG and save with reduced quality
            img = img.convert("RGB")
            reduced_image_path = f"{reduced_image_path.rsplit('.', 1)[0]}.jpg"
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
    roi_x = x
    roi_y = y - int(h * 0.2)  # Increase the top margin
    roi_w = (thresh2.shape[1] - roi_x - 20) // 2
    roi_h = int(h * 2.3)  # Increase the height multiplier
    roi = thresh2[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
    
    cropped_roi_path = f"./static/img/processed/cropped_date_{i}.png"
    cv2.imwrite(cropped_roi_path, roi)
    print(f"Cropped Date image saved to {cropped_roi_path}")

    roi = deskew(cropped_roi_path)

    # Configure Tesseract to recognize only digits and slashes
    custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789/'
    text = pytesseract.image_to_string(roi, config=custom_config)
    print("Detected text in date_img : " + str(text))
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

def deskew(_img):
    # Read the image
    image = io.imread(_img)

    # Check if the image has an alpha channel (4 channels)
    if image.shape[2] == 4:
        # Convert RGBA to RGB
        image = rgba2rgb(image)

    # Convert to grayscale
    grayscale = rgb2gray(image)

    # Determine the skew angle
    angle = determine_skew(grayscale)
    print(f"Determined skew angle: {angle} degrees")

    # Rotate the image to deskew it
    rotated = rotate(image, angle, resize=True) * 255

    # rotated.save()
    return rotated.astype(np.uint8)

def extract_reason(response): # Extract the content inside <REASON> tag for 2 pages
    match = re.search(r'<REASON>(.*?)</REASON>', response, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    else:
        print(f"Could not find <REASON> in: {response}")  # Debugging line
        return None

# END UTIL FUNCTIONS


@app.route("/login", methods=['GET', 'POST'])
def login():
    if 'username' in session:
        # return redirect(url_for('home_page'))
        session.clear()
    if request.method == 'POST':
        user = request.form['username']
        password = request.form['password']
        users = load_users()
        for u in users:
            if u['username'] == user and u['password'] == password:
                session['role'] = u['role']
                session['username'] = user
                session['department'] = u['department']
                session['ip'] = u['ip']
                return redirect(url_for('home_page'))
        return render_template('sign-in.html', error="Invalid Credentials. Please try again.")
    return render_template('sign-in.html')

@app.route("/update-user", endpoint='update-user', methods=['GET', 'POST']) 
def update_user():
    if 'username' not in session:
        return redirect(url_for('login'))

    message = None
    if session.get('role') == 'admin':
        if request.method == 'POST':
            old_username = request.form.get('old_username')
            old_password = request.form.get('old_password')

            new_username = request.form.get('username')
            new_password = request.form.get('password')
            new_role = request.form.get('role')
            # new_department = request.form.get('department')  # Uncomment if needed
            new_ip = request.form.get('ip')

            users = load_users()
            for u in users:
                if u['username'] == old_username and u['password'] == old_password:
                    if new_password and new_password == u['password']:
                        message = "New password cannot be the same as the old password"
                        break
                    if new_username:
                        u['username'] = new_username
                    if new_password:
                        u['password'] = new_password
                    if new_role:
                        u['role'] = new_role
                    # if new_department:
                    #     u['department'] = new_department  # Uncomment if needed
                    if new_ip:
                        u['ip'] = new_ip
                        
                    save_users(users)
                    message = "User updated successfully"
                    break
            else:
                message = "Username or password incorrect"
        return render_template('update-user.html', message=message)
    
    return redirect(url_for('home_page'))  # Add a fallback in case the user is not an admin

@app.route("/", methods=['GET'])
def home_page():
    if 'username' in session:
        return render_template('home_page.html')
    else:
        return redirect(url_for('login'))

@app.route('/scan-new-pod', endpoint='scan-new-pod' , methods=['POST', 'GET'])
def scan_pod_page():
    if 'username' not in session:
        return redirect(url_for('login'))

    # To run when form is submited and docs are scaned
    if request.method == 'POST':
        data = trigger_scan()
        try:
            print(data['status'])
            if data['status'] == 'error':
                flag_received.clear()
                print("Cleared")
                return render_template('scan-new-pod.html', error=data['message'])
        except:
            flag_received.clear()
            print("Cleared")
            error = "Client app not connected! Restart the app"
            return render_template('scan-new-pod.html', error=error)
        
        flag_received.wait()  

        # List all files in the directory
        image_dir = './received_files'
        all_files = os.listdir(image_dir)

        username = session.get('username')

        # Filter files that contain the session's username
        user_images = [os.path.join(image_dir, f) for f in all_files if username in f]
                

        result, pdf_index, cropped_date_img_path, scaned_img_urls, dates= scan_document(user_images)
        if result['status'] == 'warning':
            print("No barcode on any scanned page")
            return render_template('scan-new-pod.html', error=result['message'])

        print("Normally scanned")
        return render_template(
            'scan-new-pod.html',
            barcode_list=result['barcodes'],
            pdf_index=pdf_index, 
            cropped_date_img_path=cropped_date_img_path, 
            scaned_img_urls=scaned_img_urls, 
            dates=dates
        )
    else:
        # Reset the flag when the page is refreshed
        flag_received.clear()
        return render_template('scan-new-pod.html')

def scan_document(scan_session_images):
    barcode_list = []
    scaned_img_urls = []
    current_pdf_pages = []
    cropped_date_img_path = []
    # cropped_dn_img_path = []
    # avg_confidence_dn = []
    # extracted_dn = []
    current_barcode = None
    pdf_index = 1
    dates = [] 
    j = 0
    no_barcode_pages = []

    try: 
        for image in scan_session_images:
            new_barcode = None
            j += 1
            downloaded_img = image

            # READING BARCODE
            new_barcode, barcode_rect = read_barcode(downloaded_img)

            # Track pages with no barcode
            if not new_barcode:
                no_barcode_pages.append(downloaded_img)

            # if new_barcode:
            #     # Get delivery note number from text #, sales_order_number, sales_order_img_path2 TODO
            #     delivery_note_number, cropped_dn_path, deskewed_img = exteract_dn(downloaded_img, j) #full_text, confidences, 

            #     if delivery_note_number:
            #         extracted_dn.append(delivery_note_number)
            #         cropped_dn_img_path.append(cropped_dn_path)
            
            # READING Date infront of barcode 
            if new_barcode:
                deskewed_img = deskew(downloaded_img)
                x, y, w, h = barcode_rect
                date, cropped_date_path = find_date(deskewed_img, x, y, w, h, j) 
                dates.append(date)
                cropped_date_img_path.append(cropped_date_path)

            # PDF creation logic
            if new_barcode and new_barcode != current_barcode:
                if current_pdf_pages:
                    pdf_path = f'./static/pdfs/Delivery_Note_{current_barcode}.pdf'
                    # current_pdf_pages = reduce_image_quality(current_pdf_pages)
                    create_pdf(current_pdf_pages, pdf_path)
                    pdf_index += 1
                    current_pdf_pages = []
                barcode_list.append(new_barcode)
                current_barcode = new_barcode

            current_pdf_pages.append(downloaded_img)
            scaned_img_urls.append(downloaded_img)
    finally:
        print("=======================")
        print("Document feeder is now empty.")
        print("=======================")
        # pyinsane2.exit()
        
    # Create the last PDF if there are remaining pages
    if current_pdf_pages and current_barcode:
        pdf_path = f'./static/pdfs/Delivery_Note_{current_barcode}.pdf'
        create_pdf(current_pdf_pages, pdf_path)
    
    # Clean up the scanned image files
    cleanup_files(scaned_img_urls)

    # Check if no barcodes were found in any of the pages
    if len(barcode_list) == 0:
        return {"status": "warning", "message": "No barcodes found on any scanned pages."}, pdf_index, cropped_date_img_path, scaned_img_urls, dates

    return {"status": "success", "barcodes": barcode_list}, pdf_index, cropped_date_img_path, scaned_img_urls, dates #, cropped_so_img_path, extracted_so , cropped_dn_img_path, avg_confidence_dn, extracted_dn,

@app.before_request
def before_request():
    if 'created_pdfs' in session:
        # Check if the user is navigating away from PDF creation/upload endpoints
        if request.method == 'GET'and request.endpoint not in ('static'):
            print("if 2")
            if request.endpoint not in ('upload_pod'):
                print("if 3")
                # User is navigating away from the upload endpoint
                for pdf_path in session['created_pdfs']:
                    if os.path.exists(pdf_path):
                        print(request.endpoint)
                        print("pdf deleted")
                        os.remove(pdf_path)
                session.pop('created_pdfs')

@app.route('/upload-pod', methods=['POST'])
def upload_pod():
    created_at = datetime.now()
    status = 'pending'
    site = session['department']
    username = session['username']
    if request.method == 'POST':
        engine = db_connection()
        with engine.connect() as conn:
            uploaded_pdfs = []
            for i in range(len(request.form)//3):  # Assuming 4 fields per entry (DN, Date, Include)
                if request.form.get(f'include{i}') == 'on':
                    dn = request.form.get(f'dn{i}')
                    date = request.form.get(f'date{i}')
                    date = datetime.strptime(date, '%d/%m/%Y')
                    # date = '06/05/2024'
                    pdf_url = f'http://podms.modern-electronics.com:8080/static/pdfs/Delivery_Note_{dn}.pdf'
                    conn.execute(text("INSERT INTO dbo.TB_WH_POD (Site, DN, PODDate, URL, CreatedAt , Status, username) VALUES (:site, :dn, :date, :pdf_url, :created_at, :status, :username);"),
                                 {'site':site, 'dn': dn, 'date': date, 'pdf_url':pdf_url, 'created_at': created_at, 'status': status, 'username': username})
                    conn.commit()
                    print("Database updated. New Entry added")
                    uploaded_pdfs.append(dn)
            conn.close()

            # Clean up 
            if 'created_pdfs' in session:
                for pdf_path in session['created_pdfs']:
                    # Extract DN from the PDF path
                    pdf_dn = os.path.basename(pdf_path).split('_')[2].split('.')[0]
                    if pdf_dn not in uploaded_pdfs:
                        if os.path.exists(pdf_path):
                            os.remove(pdf_path)
                session.pop('created_pdfs')
        return render_template('scan-new-pod.html', error="Data successfully uploaded.")
    return render_template('scan-new-pod.html')

@app.route('/all-pod',  endpoint='all-pod', methods=['POST', 'GET'])
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
                    result = conn.execute(text("SELECT PODDate, URL FROM dbo.TB_WH_POD WHERE DN = :dn"), {'dn': dn}).fetchone()
                    if result:
                        date = result[0]
                        pdf_url = result[1]
                        pdf_url = f'/static/pdfs/Delivery_Note_{dn}.pdf'
                        results.append({'dn': dn, 'date': date, 'pdf_url': pdf_url})
                    else:
                        results.append({'dn': dn, 'error': "DN number not found."})

            if date_list:
                for date in date_list:
                    result = conn.execute(text("SELECT Dn, PODDate, URL FROM dbo.TB_WH_POD WHERE PODDate = :date"), {'date': date}).fetchall()
                    for row in result:
                        dn, date, pdf_url = row
                        results.append({'dn': dn, 'date': date, 'pdf_url': pdf_url})
                        pdf_url = f'/static/pdfs/Delivery_Note_{dn}.pdf'
                    if not result:
                        results.append({'date': date, 'error': "Date not found."})

        return render_template('all-pod.html', results=results)

    return render_template('all-pod.html')

@app.route("/sap-sync", endpoint='sap-sync' , methods=['POST', 'GET'])
def sapSync():
    engine = db_connection()
    if request.method == 'POST' and 'resync' in request.form:
       with engine.connect() as conn:
            # Define the SQL update query
            query = text("""
                UPDATE dbo.TB_WH_POD
                SET CompletedAt = NULL, 
                    CompletedStatus = '', 
                    CompletedResponse = '', 
                    Status = 'pending'
                WHERE CompletedStatus = 'Fail';
            """)
            
            # Execute the update query
            conn.execute(query)
            conn.commit()
            conn.close()
 
    with engine.connect() as conn:
        # Calculate the cutoff times
        cutoff_time_2_minutes = datetime.now() - timedelta(minutes=2)
        cutoff_time_15_minutes = datetime.now() - timedelta(minutes=15)

        # Define the SQL query with the combined conditions using OR
        query = text("""
            SELECT DN, CreatedAt, CompletedStatus, Completedresponse 
            FROM dbo.TB_WH_POD 
            WHERE (CompletedStatus != 'Success' AND CreatedAt < :cutoff_time_2_minutes)
            OR (Status = 'pending' AND CreatedAt < :cutoff_time_15_minutes)
        """)
        
        # Execute the query and fetch results
        result = conn.execute(query, {'cutoff_time_2_minutes': cutoff_time_2_minutes, 'cutoff_time_15_minutes': cutoff_time_15_minutes}).fetchall()
        # print(result)
        
        records = [
            {
                'DN': row[0],
                'CreatedAt': row[1],
                'CompletedStatus': row[2],
                'Completedresponse': extract_reason(str(row[3]))
            }
            for row in result
        ]
    
    # Render the template with the fetched records
    return render_template('sapSync.html', records=records)

#-------------- SCANNER APP -------------- #
@app.route('/printer_settings', methods=['POST', 'GET'])
def printer_settings():
    if request.method == 'POST' and 'scan-button' in request.form:
        local_client_url = 'http://' + session.get('ip') + ':5001/test'  # Local client application URL
        print(local_client_url)
        server_url = request.host_url  # Server URL to upload scanned images

        try:
            response = requests.post(local_client_url, json={'server_url': server_url}, timeout=10)  # Set a timeout
            response.raise_for_status()  # Raise an HTTPError if the HTTP request returned an unsuccessful status code
            data = response.json()
            print(data['status'])

            if data['status'] == 'success':
                working = True
                if 'not Connected properly' in data['message']:
                    useable = False
                    return render_template('printer_settings.html', working=working, useable=useable, message=data['message'])
                else:
                    useable = True
                    return render_template('printer_settings.html', working=working, useable=useable, message=data['message'])
            elif data['status'] == 'error':
                working = False
                useable = False
                message = "Not Connected !"
                return render_template('printer_settings.html', working=working, useable=useable, message=message)
        except (requests.ConnectionError, requests.Timeout, requests.RequestException) as e:
            # Handle request failure
            working = False
            useable = False
            message = "Client app not started or user IP incorrect"
            print(str(e))  # Log the exception for debugging
            return render_template('printer_settings.html', working=working, useable=useable, message=message)

    if request.method == 'POST' and 'download' in request.form:
        filename = "Local_client/Local_client.zip"
        return send_from_directory(directory='./', path=filename, as_attachment=True)
        
    return render_template('printer_settings.html')

def trigger_scan():
    try:
        local_client_url = 'http://'+session['ip']+':5001/scan'  # Local client application URL
        print(str(session['username']) + " | " +str(local_client_url))
        response = requests.post(local_client_url, json={'server_url': request.host_url + 'upload', 'username':session['username']}, timeout=(10,1000))
        data = response.json()
        print(data)
        return data
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
    
@app.route('/upload', methods=['POST']) #FOR SCANNER APP
def upload():
    if 'file' in request.files:
        # user = 'admin'
        file = request.files['file']

        if file.filename == '':
            return jsonify({"status": "error", "message": "No selected file"}), 400

        file_path = f'./received_files/{file.filename}'
        file.save(file_path)
        print("File Received")
    elif 'uploaded_files' in request.form:
        print("Completed Flag received by Server")
        flag_received.set()

    return ''
#-------------- END SCANNER APP -------------- #

#-------------- REPORTS --------------#
@app.route('/general-upload-report', endpoint='general-upload-report' , methods=['POST', 'GET'])
def upload_rep():
    engine = db_connection()
    with engine.connect() as conn:
        # Fetch the latest 10 results by default
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))

        # Fetch total number of records
        # text("SELECT COUNT(*) FROM dbo.TB_WH_POD")
        total_query = text("SELECT COUNT(DISTINCT DN) AS UniqueDNCount FROM dbo.TB_WH_POD")
        total_records = conn.execute(total_query).scalar()
        
        # query = text(f"""
        #     SELECT Site, DN, CreatedAt, CompletedStatus, CompletedResponse 
        #     FROM dbo.TB_WH_POD 
        #     ORDER BY CreatedAt DESC 
        #     OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        # """)
        query = text(f"""
            WITH UniqueDN AS (
                SELECT DISTINCT DN, MAX(CreatedAt) AS LatestCreatedAt
                FROM dbo.TB_WH_POD
                GROUP BY DN
            )
            SELECT T.Site, T.DN, T.CreatedAt, T.CompletedStatus, T.CompletedResponse, T.username
            FROM dbo.TB_WH_POD T
            INNER JOIN UniqueDN U ON T.DN = U.DN AND T.CreatedAt = U.LatestCreatedAt
            ORDER BY T.CreatedAt DESC 
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """)
        
        # Execute the query and fetch results
        result = conn.execute(query, {'offset': offset, 'limit': limit}).fetchall()
        
        records = [
            {
                'Site': row[0],
                'DN': row[1],
                'CreatedAt': row[2].strftime('%d/%b/%Y %H:%M'),  # Format the datetime
                'CompletedStatus': row[3],
                'Completedresponse': extract_reason(str(row[4])),
                'username': row[5]
            }
            for row in result
        ]
        
        usernames = []
        deps = []
        users = load_users()
        for u in users:
            usernames.append(u['username'])
            deps.append(u['department'])
    
    return render_template('general_upload_report.html', records=records, limit=limit, offset=offset, total_records=total_records, usernames=usernames, deps=deps)

@app.route('/general-upload-report-filters', methods=['POST', 'GET']) #FILTER
def upload_rep_filter():
    engine = db_connection()
    with engine.connect() as conn:
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))
        search = request.args.get('search', None)
        filter_site = request.args.get('filter_site', '')
        filter_dn = request.args.get('filter_dn', '')
        filter_date_from = request.args.get('filter_date_from', '')
        filter_date_to = request.args.get('filter_date_to', '')
        filter_status = request.args.get('filter_status', '')
        filter_un = request.args.get('filter_username', '')
        filter_response = request.args.get('filter_response', '')

        base_query = """
            WITH CTE AS (
                SELECT 
                    Site, 
                    DN, 
                    CreatedAt, 
                    CompletedStatus, 
                    CompletedResponse,
                    username,
                    ROW_NUMBER() OVER (PARTITION BY DN ORDER BY CreatedAt DESC) AS rn
                FROM dbo.TB_WH_POD 
                WHERE 1=1
        """
        
        filters = []
        if filter_site:
            filters.append(f"Site LIKE :filter_site")
        if filter_dn:
            filters.append(f"DN LIKE :filter_dn")
        if filter_date_from:
            filters.append(f"CreatedAt >= :filter_date_from")
        if filter_date_to:
            filters.append(f"CreatedAt <= :filter_date_to")
        if filter_status:
            filters.append(f"CompletedStatus LIKE :filter_status")
        if filter_un:
            filters.append(f"username LIKE :filter_username")
        if filter_response:
            filters.append(f"CompletedResponse LIKE :filter_response")
        
        if filters:
            filter_query = " AND ".join(filters)
            base_query += f" AND {filter_query}"
        
        base_query += """
            )
            , FilteredCTE AS (
                SELECT Site, DN, CreatedAt, CompletedStatus, CompletedResponse, username
                FROM CTE 
                WHERE rn = 1
            )
        """

        total_query = f"""
            {base_query}
            SELECT COUNT(*) FROM FilteredCTE
        """
        
        paginated_query = f"""
            {base_query}
            SELECT Site, DN, CreatedAt, CompletedStatus, CompletedResponse, username
            FROM FilteredCTE
            ORDER BY CreatedAt DESC 
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """

        total_records = conn.execute(text(total_query), {
            'filter_site': f'%{filter_site}%',
            'filter_dn': f'%{filter_dn}%',
            'filter_date_from': filter_date_from,
            'filter_date_to': filter_date_to,
            'filter_status': f'%{filter_status}%',
            'filter_username': f'%{filter_un}%',
            'filter_response': f'%{filter_response}%'
        }).scalar()

        params = {
            'offset': offset,
            'limit': limit,
            'filter_site': f'%{filter_site}%',
            'filter_dn': f'%{filter_dn}%',
            'filter_date_from': filter_date_from,
            'filter_date_to': filter_date_to,
            'filter_status': f'%{filter_status}%',
            'filter_username': f'%{filter_un}%',
            'filter_response': f'%{filter_response}%'
        }
        
        result = conn.execute(text(paginated_query), params).fetchall()
        
        records = [
            {
                'Site': row[0],
                'DN': row[1],
                'CreatedAt': row[2].strftime('%d/%b/%Y %H:%M'),  # Format with month name
                'CompletedStatus': row[3],
                'CompletedResponse': extract_reason(str(row[4])),
                'username': row[5]
            }
            for row in result
        ]
        # Debugging: Print out the records to ensure CompletedResponse is processed
        for record in records:
            print(f"{record['CompletedResponse']}")
    
    return render_template('general_upload_report.html', records=records, limit=limit, offset=offset, total_records=total_records, search=search)

@app.route('/user-performance', endpoint='user-performance', methods=['POST', 'GET'])
def performance_report():
    limit = int(request.args.get('limit', 20))
    offset = int(request.args.get('offset', 0))

    # Load users and create a dictionary mapping username to department and send to frontend 
    users = load_users()
    username_to_department = {u['username']: u['department'] for u in users}
    usernames = []
    dep = []
    for u in users:
        usernames.append(u['username'])
        dep.append(u['department'])
    
    engine = db_connection()
    with engine.connect() as conn:
        query_count = text("""
            SELECT COUNT(*) AS total_count
            FROM dbo.user_activity ua
            LEFT JOIN (
                SELECT username, 
                       CONVERT(VARCHAR, CreatedAt, 23) AS Date, 
                       COUNT(*) AS pod_count
                FROM TB_WH_POD
                GROUP BY username, CONVERT(VARCHAR, CreatedAt, 23)
            ) pod_count
            ON ua.user_id = pod_count.username 
               AND CONVERT(VARCHAR, ua.activity_date, 23) = pod_count.Date
        """)
        
        total_records = conn.execute(query_count).scalar()

        query_activity = text("""
            SELECT ua.user_id, 
                   CONVERT(VARCHAR, ua.activity_date, 23) AS Date, 
                   ua.activity_time / 60.0 AS activity_time_minutes,
                   ISNULL(pod_count.pod_count, 0) AS pod_count,
                   pod_count.Site
            FROM dbo.user_activity ua
            LEFT JOIN (
                SELECT username, 
                       Site,
                       COUNT(*) AS pod_count,
                       CONVERT(VARCHAR, CreatedAt, 23) AS Date
                FROM TB_WH_POD
                GROUP BY username, Site, CONVERT(VARCHAR, CreatedAt, 23)
            ) pod_count
            ON ua.user_id = pod_count.username 
               AND CONVERT(VARCHAR, ua.activity_date, 23) = pod_count.Date
            ORDER BY ua.activity_date DESC, ua.user_id
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """)

        result_activity = conn.execute(query_activity, {'offset': offset, 'limit': limit}).fetchall()
        
        # Process the activity result into a list of dictionaries with formatted time
        activity_data = []
        for row in result_activity:
            user_id = row[0]
            date = row[1]

            total_minutes = row[2]
            hours = total_minutes // 60
            minutes = total_minutes % 60
            formatted_time = f"{int(minutes)}M {int(hours)}H"

            pod_count = row[3]
            site = row[4]

            # If site is None, use the department from the loaded users
            if site is None:
                site = username_to_department.get(user_id, 'Unknown')

            activity_data.append({
                "Username": user_id,
                "Date": date,
                "Site": site,
                "ActivityTime": formatted_time,
                "TotalPODs": pod_count
            })
    
    return render_template('user-performance-report.html', activity_data=activity_data, limit=limit, offset=offset, usernames=usernames, dep=dep, total_records=total_records)

@app.route('/user-performance-filters', endpoint='user-performance-filters', methods=['POST', 'GET']) # FILTER
def performance_report_filters():
    limit = int(request.args.get('limit', 20))
    offset = int(request.args.get('offset', 0))
    filter_username = request.args.get('filter_username', '')
    filter_site = request.args.get('filter_site', '')
    filter_date_from = request.args.get('filter_date_from', '')
    filter_date_to = request.args.get('filter_date_to', '')

    # Load users and create a dictionary mapping username to department
    users = load_users()
    username_to_department = {u['username']: u['department'] for u in users}

    filter_conditions = []
    if filter_username:
        filter_conditions.append("ua.user_id = :username")
    if filter_site:
        filter_conditions.append("pod_count.Site = :site")
    if filter_date_from:
        filter_conditions.append("ua.activity_date >= :date_from")
    if filter_date_to:
        filter_conditions.append("ua.activity_date <= :date_to")

    where_clause = ' AND '.join(filter_conditions)
    if where_clause:
        where_clause = 'WHERE ' + where_clause

    engine = db_connection()
    with engine.connect() as conn:
        query_count = text(f"""
            SELECT COUNT(*) AS total_count
            FROM dbo.user_activity ua
            LEFT JOIN (
                SELECT username, 
                       Site,
                       CONVERT(VARCHAR, CreatedAt, 23) AS Date, 
                       COUNT(*) AS pod_count
                FROM TB_WH_POD
                GROUP BY username, Site, CONVERT(VARCHAR, CreatedAt, 23)
            ) pod_count
            ON ua.user_id = pod_count.username 
               AND CONVERT(VARCHAR, ua.activity_date, 23) = pod_count.Date
            {where_clause}
        """)

        count_params = {
            'username': filter_username,
            'site': filter_site,
            'date_from': filter_date_from,
            'date_to': filter_date_to
        }

        total_records = conn.execute(query_count, count_params).scalar()

        query_activity = text(f"""
            SELECT ua.user_id, 
                   CONVERT(VARCHAR, ua.activity_date, 23) AS Date, 
                   ua.activity_time / 60.0 AS activity_time_minutes,
                   ISNULL(pod_count.pod_count, 0) AS pod_count,
                   pod_count.Site
            FROM dbo.user_activity ua
            LEFT JOIN (
                SELECT username, 
                       Site,
                       COUNT(*) AS pod_count,
                       CONVERT(VARCHAR, CreatedAt, 23) AS Date
                FROM TB_WH_POD
                GROUP BY username, Site, CONVERT(VARCHAR, CreatedAt, 23)
            ) pod_count
            ON ua.user_id = pod_count.username 
               AND CONVERT(VARCHAR, ua.activity_date, 23) = pod_count.Date
            {where_clause}
            ORDER BY ua.activity_date DESC, ua.user_id
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """)

        query_params = {
            'username': filter_username,
            'site': filter_site,
            'date_from': filter_date_from,
            'date_to': filter_date_to,
            'offset': offset,
            'limit': limit
        }

        result_activity = conn.execute(query_activity, query_params).fetchall()

        # Process the activity result into a list of dictionaries with formatted time
        activity_data = []
        for row in result_activity:
            user_id = row[0]
            date = row[1]

            total_minutes = row[2]
            hours = total_minutes // 60
            minutes = total_minutes % 60
            formatted_time = f"{int(minutes)}M {int(hours)}H"

            pod_count = row[3]
            site = row[4]

            # If site is None, use the department from the loaded users
            if site is None:
                site = username_to_department.get(user_id, 'Unknown')

            activity_data.append({
                "Username": user_id,
                "Date": date,
                "Site": site,
                "ActivityTime": formatted_time,
                "TotalPODs": pod_count
            })

    return render_template('user-performance-report.html', 
                           activity_data=activity_data, 
                           limit=limit, 
                           offset=offset, 
                           total_records=total_records,
                           filter_username=filter_username,
                           filter_site=filter_site,
                           filter_date_from=filter_date_from,
                           filter_date_to=filter_date_to)

@app.route('/daily-progress-report', endpoint='daily-progress-report' , methods=['POST', 'GET'])
def daily_progress_report():
    # Display user --> DAY/DATE --> Total PODs uploaded
    usernames = []
    dep = []
    users = load_users()
    for u in users:
        usernames.append(u['username'])
        dep.append(u['department'])
    
    limit = int(request.args.get('limit', 20))
    offset = int(request.args.get('offset', 0))

    engine = db_connection()
    with engine.connect() as conn:
        count_query = text("""
            WITH CTE AS (
                SELECT 
                    Site, 
                    username,
                    CONVERT(VARCHAR, CreatedAt, 23) AS Date,
                    ROW_NUMBER() OVER (PARTITION BY DN ORDER BY CreatedAt DESC) AS rn
                FROM dbo.TB_WH_POD
            )
            SELECT COUNT(*)
            FROM (
                SELECT Site, username, Date
                FROM CTE
                WHERE rn = 1
                GROUP BY Site, username, Date
            ) AS count_query;
        """)
        
        total_records = conn.execute(count_query).scalar()   

        query = text("""
            WITH CTE AS (
                SELECT 
                    Site, 
                    username,
                    CONVERT(VARCHAR, CreatedAt, 23) AS Date,
                    ROW_NUMBER() OVER (PARTITION BY DN ORDER BY CreatedAt DESC) AS rn
                FROM dbo.TB_WH_POD
            )
            SELECT Site, 
                   username,
                   Date,
                   COUNT(*) AS TotalPODs
            FROM CTE
            WHERE rn = 1
            GROUP BY Site, username, Date
            ORDER BY Date DESC, Site, username
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """)
            
        result = conn.execute(query, {'offset': offset, 'limit': limit}).fetchall()
        
        # Process the result into a list of dictionaries
        report_data = [
            {
                'Site': row[0],
                'Username': row[1],
                'Date': row[2],
                'TotalPODs': row[3]
            }
            for row in result
        ]

    return render_template('daily-progress-report.html', 
                           usernames=usernames, 
                           dep=dep, 
                           report_data=report_data,
                           limit=limit, 
                           offset=offset, 
                           total_records=total_records)

@app.route('/daily-progress-report-filters', endpoint='daily-progress-report-filters', methods=['POST', 'GET']) #FILTER
def daily_prog_rep_filter():
    usernames = []
    dep = []
    users = load_users()
    for u in users:
        usernames.append(u['username'])
        dep.append(u['department'])

    limit = int(request.args.get('limit', 20))
    offset = int(request.args.get('offset', 0))
    filter_username = request.args.get('filter_username', '')
    filter_site = request.args.get('filter_site', '')
    filter_date_from = request.args.get('filter_date_from', '')
    filter_date_to = request.args.get('filter_date_to', '')


    filter_conditions = []
    if filter_username:
        filter_conditions.append("username = :username")
    if filter_site:
        filter_conditions.append("Site = :site")
    if filter_date_from:
        filter_conditions.append("CreatedAt >= :date_from")
    if filter_date_to:
        filter_conditions.append("CreatedAt <= :date_to")

    where_clause = ' AND '.join(filter_conditions)
    if where_clause:
        where_clause = 'WHERE ' + where_clause

    engine = db_connection()
    with engine.connect() as conn:
        count_query = text(f"""
            SELECT COUNT(*)
            FROM (
                SELECT Site, 
                       username,
                       CONVERT(VARCHAR, CreatedAt, 23) AS Date
                FROM dbo.TB_WH_POD
                {where_clause}
                GROUP BY Site, username, CONVERT(VARCHAR, CreatedAt, 23)
            ) AS count_query;
        """)
        
        count_params = {
            'username': filter_username,
            'site': filter_site,
            'date_from': filter_date_from,
            'date_to': filter_date_to
        }

        total_records = conn.execute(count_query, count_params).scalar()

        query = text(f"""
            SELECT Site, 
                   username,
                   CONVERT(VARCHAR, CreatedAt, 23) AS Date, 
                   COUNT(*) AS TotalPODs
            FROM dbo.TB_WH_POD
            {where_clause}
            GROUP BY Site, username, CONVERT(VARCHAR, CreatedAt, 23)
            ORDER BY Date DESC, Site, username
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY;
        """)
        
        query_params = {
            'username': filter_username,
            'site': filter_site,
            'date_from': filter_date_from,
            'date_to': filter_date_to,
            'offset': offset,
            'limit': limit
        }

        result = conn.execute(query, query_params).fetchall()
        
        report_data = [
            {
                'Site': row[0],
                'Username': row[1],
                'Date': row[2],
                'TotalPODs': row[3]
            }
            for row in result
        ]

    return render_template('daily-progress-report.html', 
                           usernames=usernames, 
                           dep=dep, 
                           report_data=report_data,
                           limit=limit, 
                           offset=offset, 
                           total_records=total_records,
                           filter_username=filter_username,
                           filter_site=filter_site,
                           filter_date_from=filter_date_from,
                           filter_date_to=filter_date_to)

#-------------- END REPORTS --------------#

@app.route('/save_activity', methods=['POST', 'GET']) # Gets Pereodic calls to save user activity
def save_activity():
    try:
        data = request.get_json()
        app.logger.info(f'Received data: {data}')
        
        user_id = session.get('username')
        if not user_id:
            return redirect(url_for('login'))

        elapsed_time = data.get('elapsedTime')
        if elapsed_time is None:
            app.logger.error("Elapsed time is None")
            return jsonify({'status': 'fail'})
        
        activity_date = date.today()

        engine = db_connection()
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                # Fetch all records for the user on the given date
                result = conn.execute(text('''
                    SELECT activity_time, timestamp FROM dbo.user_activity
                    WHERE user_id = :user_id AND activity_date = :activity_date
                    ORDER BY timestamp DESC
                '''), {'user_id': user_id, 'activity_date': activity_date})
                rows = result.fetchall()
                if rows:
                    # Update the most recent record
                    latest_row = rows[0]
                    new_activity_time = latest_row[0] + elapsed_time
                    conn.execute(text('''
                        UPDATE dbo.user_activity
                        SET activity_time = :activity_time, timestamp = :timestamp
                        WHERE user_id = :user_id AND activity_date = :activity_date
                    '''), {'activity_time': new_activity_time, 'timestamp': datetime.now(), 'user_id': user_id, 'activity_date': activity_date})
                else:
                    # Insert new record
                    conn.execute(text('''
                        INSERT INTO dbo.user_activity (user_id, activity_time, activity_date, timestamp)
                        VALUES (:user_id, :activity_time, :activity_date, :timestamp)
                    '''), {'user_id': user_id, 'activity_time': elapsed_time, 'activity_date': activity_date, 'timestamp': datetime.now()})
                trans.commit()
            except Exception as e:
                trans.rollback()
                app.logger.error(f'Error executing query: {e}')
                raise e
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f'Error saving activity: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ----------------------EMAIL REPORTS---------------------- # 
@app.route('/send_report', methods=['GET', 'POST'])
def send_report():
    # Fetch the top 5 results
    activity_data = performance_report_data(limit=5, offset=0)

    # Render the HTML for the email
    html_content = render_template('email_template.html', activity_data=activity_data)
    
    # Email details
    subject = "PODMS Users Performance Report"
    sender = "bilalzafar37201@gmail.com"
    recipient = 'biqbal@modern-electronics.com'
    
    # Send the email
    send_email(subject, sender, recipient, html_content)
    
    return "Email sent successfully!"

def performance_report_data(limit, offset):
    users = load_users()
    username_to_department = {u['username']: u['department'] for u in users}
    
    engine = db_connection()
    with engine.connect() as conn:
        query_activity = text("""
            SELECT ua.user_id, 
                   CONVERT(VARCHAR, ua.activity_date, 23) AS Date, 
                   ua.activity_time / 60.0 AS activity_time_minutes,
                   ISNULL(pod_count.pod_count, 0) AS pod_count,
                   pod_count.Site
            FROM dbo.user_activity ua
            LEFT JOIN (
                SELECT username, 
                       Site,
                       COUNT(*) AS pod_count,
                       CONVERT(VARCHAR, CreatedAt, 23) AS Date
                FROM TB_WH_POD
                GROUP BY username, Site, CONVERT(VARCHAR, CreatedAt, 23)
            ) pod_count
            ON ua.user_id = pod_count.username 
               AND CONVERT(VARCHAR, ua.activity_date, 23) = pod_count.Date
            ORDER BY ua.activity_date DESC, ua.user_id
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """)

        result_activity = conn.execute(query_activity, {'offset': offset, 'limit': limit}).fetchall()
        
        activity_data = []
        for row in result_activity:
            user_id = row[0]
            date = row[1]

            total_minutes = row[2]
            hours = total_minutes // 60
            minutes = total_minutes % 60
            formatted_time = f"{int(hours)}H {int(minutes)}M"

            pod_count = row[3]
            site = row[4]

            if site is None:
                site = username_to_department.get(user_id, 'Unknown')

            activity_data.append({
                "Username": user_id,
                "Date": date,
                "Site": site,
                "ActivityTime": formatted_time,
                "TotalPODs": pod_count
            })
    
    return activity_data

def send_email(subject, sender, recipient, html_content):
    smtp_server = 'smtp.office365.com'
    smtp_port = 587
    smtp_username = 'biqbal@modern-electronics.com'
    smtp_password = 'Ryd@112299'
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient
    
    part = MIMEText(html_content, 'html')
    msg.attach(part)
    
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(sender, recipient, msg.as_string())

    print("Email sent successfully!")

# ---------------------- END EMAIL REPORTS---------------------- # 





if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
