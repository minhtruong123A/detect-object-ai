import cv2
from ultralytics import YOLO
import numpy as np
from pydantic import BaseModel
import datetime
import pyodbc
import threading

# Database connection string
DATABASE = 'Driver={SQL Server};Server=(local);Database=SWDProject;UID=sa;PWD=12345;'

# Load YOLOv8 model
model = YOLO('best.pt')

# Function to create a blank frame
def create_blank_frame(width, height):
    return np.zeros((height, width, 3), dtype=np.uint8)

# Function to combine frames
def combine_frames(frames, width, height):
    # Create a blank canvas large enough to hold all frames in a 2x2 grid
    canvas_height = 2 * height
    canvas_width = 2 * width
    canvas = create_blank_frame(canvas_width, canvas_height)

    # Place each frame on the canvas
    if frames[0] is not None:
        canvas[0:height, 0:width] = frames[0]
    if frames[1] is not None:
        canvas[0:height, width:2*width] = frames[1]
    if frames[2] is not None:
        canvas[height:2*height, 0:width] = frames[2]

    return canvas

# Function to add order details to a blank frame
def add_order_details(order_details, width, height):
    canvas = create_blank_frame(width, height)
    order_start_x = 20
    order_start_y = 20
    line_height = 30
    
    # Draw header
    cv2.putText(canvas, "POS Order", (order_start_x, order_start_y), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    y_offset = order_start_y + line_height
    cv2.putText(canvas, "-"*60, (order_start_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    y_offset += line_height
    cv2.putText(canvas, "Product", (order_start_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(canvas, "Price", (order_start_x + 200, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(canvas, "Quantity", (order_start_x + 400, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(canvas, "Total", (order_start_x + 550, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    y_offset += line_height
    cv2.putText(canvas, "-"*60, (order_start_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    # Draw order details
    for idx, (product_name, price, quantity) in enumerate(order_details):
        total = price * quantity
        y_offset += line_height
        cv2.putText(canvas, f"{product_name}", (order_start_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(canvas, f"{price:.2f} VND", (order_start_x + 200, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(canvas, f"{quantity}", (order_start_x + 400, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(canvas, f"{total:.2f} VND", (order_start_x + 550, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    y_offset += line_height
    cv2.putText(canvas, "-"*60, (order_start_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    total_quantity = sum([quantity for _, _, quantity in order_details])
    total_price = sum([price * quantity for _, price, quantity in order_details])
    y_offset += line_height
    cv2.putText(canvas, f"Total Quantity: {total_quantity}", (order_start_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(canvas, f"Total Price: {total_price:.2f} VND", (order_start_x + 350, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    return canvas

# Function to process video and perform detection on capture
def process_video(camera_indices, frames, width, height, capture_event, detected_objects):
    caps = []
    for i in camera_indices:
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            caps.append(cap)
        else:
            print(f"Failed to open camera {i}")

    if not caps:
        print("No cameras available.")
        return

    while True:
        for i, cap in enumerate(caps):
            ret, frame = cap.read()
            if not ret:
                print(f"Failed to read frame from camera {i}")
                frames[i] = create_blank_frame(width, height)
                continue
            frames[i] = frame
        
        combined_frame = combine_frames(frames, width, height)
        cv2.imshow('Combined Cameras', combined_frame)

        key = cv2.waitKey(1)
        if key & 0xFF == ord('q'):
            break
        elif key in [ord('1'), ord('2'), ord('3')]:  # Press '1', '2', or '3' to capture from specific cameras
            camera_index = int(chr(key)) - 1  # Convert ASCII to integer and adjust to 0-based index
            if camera_index < len(caps):
                ret, frame = caps[camera_index].read()
                if ret:
                    results = model(frame)
                    frame_objects = []
                    for result in results:
                        if result.boxes.xyxy.numel() > 0:
                            for box, class_id in zip(result.boxes.xyxy, result.boxes.cls):
                                class_name = model.names[int(class_id)]
                                frame_objects.append((class_name, 1))  # Store detected object name and count

                    detected_objects[camera_index] = frame_objects

                    # Process detected objects
                    all_detected_objects = []
                    for obj_list in detected_objects:
                        if obj_list is not None:
                            all_detected_objects.extend(obj_list)

                    product_quantities = {}
                    for obj_name, count in all_detected_objects:
                        if obj_name in product_quantities:
                            product_quantities[obj_name] += count
                        else:
                            product_quantities[obj_name] = count

                    order_details = []
                    for product_name, quantity in product_quantities.items():
                        price = get_product_price(product_name)
                        if price is not None:
                            order_details.append((product_name, price, quantity))
                        else:
                            print(f"Product not found: {product_name}")
                            order_details = []  # Clear order details
                            break

                    if order_details:
                        save_order_to_database(order_details)
                    else:
                        print("Order save cancelled due to missing product names.")

                    # Display updated order details in a new window
                    pos_frame = add_order_details(order_details, width + 400, height)
                    order_window = "POS Order"
                    cv2.namedWindow(order_window)
                    while True:
                        cv2.imshow(order_window, pos_frame)
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            cv2.destroyWindow(order_window)
                            break

    for cap in caps:
        cap.release()
    cv2.destroyAllWindows()

# Function to get product price from the database
def get_product_price(product_name):
    conn = pyodbc.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT Price FROM Product WHERE ProductName = ?", (product_name,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0]
    else:
        return None

# Function to save order details to the database
def save_order_to_database(order_details):
    conn = pyodbc.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get the next available ID for Order table
    cursor.execute("SELECT ISNULL(MAX(Id), 0) + 1 FROM [Order]")
    next_order_id = cursor.fetchone()[0]
    
    create_date = datetime.datetime.now()
    total_price = sum([price * quantity for _, price, quantity in order_details])
    cursor.execute("INSERT INTO [Order] (Id, BrandID, CreateDate, TotalPrice) VALUES (?, ?, ?, ?)", (next_order_id, 1, create_date, total_price))
    
    for product_name, price, quantity in order_details:
        cursor.execute("SELECT Id FROM Product WHERE ProductName = ?", (product_name,))
        product_id = cursor.fetchone()[0]
        
        # Get the next available ID for ProductOrder table
        cursor.execute("SELECT ISNULL(MAX(Id), 0) + 1 FROM ProductOrder")
        next_product_order_id = cursor.fetchone()[0]
        
        cursor.execute("INSERT INTO ProductOrder (Id, ProductId, OrderId, ProductQuantity, ProductTotalPrice) VALUES (?, ?, ?, ?, ?)",
                       (next_product_order_id, product_id, next_order_id, quantity, price * quantity))
    
    conn.commit()
    conn.close()

camera_indices = [0, 1, 2]
width, height = 640, 480
frames = [None, None, None]
capture_event = threading.Event()
detected_objects = [None, None, None]

process_video(camera_indices, frames, width, height, capture_event, detected_objects)
