import torch
import cv2
import numpy as np
import os
import io
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from scipy.spatial.distance import cosine
from ultralytics import YOLO
from transformers import CLIPProcessor, CLIPModel
from PIL import Image
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
# IMPORTANT: Change 'localhost' to your Computer's IP (e.g., 192.168.1.10) if debuging on a physical mobile device,
# so your mobile app can fetch images over Wi-Fi.
BASE_URL = "http://192.168.1.106:8004" 
STATIC_IMG_PATH = "Rings/ring/"

if os.path.exists(STATIC_IMG_PATH):
    app.mount("/static_images", StaticFiles(directory=STATIC_IMG_PATH), name="static_images")

# --- Load Models ---
device = "cuda" if torch.cuda.is_available() else "cpu"
yolo_model = YOLO("yolov8m-seg.pt") 
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)
clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

# --- Load Catalog ---
try:
    CATALOG_DATA = np.load("catalog_data.npy", allow_pickle=True)
except Exception:
    print("Warning: catalog_data.npy not found. Run indexing first.")
    CATALOG_DATA = np.array([])

def get_combined_embedding(cv2_img):
    """Generates a 1024-dim vector: 512 for stone shape + 512 for ring structure."""
    results = yolo_model(cv2_img, verbose=False)
    mask_img = cv2_img.copy()
    
    if results[0].masks is not None:
        mask = results[0].masks.data[0].cpu().numpy()
        mask = cv2.resize(mask, (cv2_img.shape[1], cv2_img.shape[0]))
        mask_uint8 = (mask * 255).astype(np.uint8)
        mask_img = cv2.bitwise_and(cv2_img, cv2_img, mask=mask_uint8)

    gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    edges_3ch = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)

    with torch.no_grad():
        # Stone Features
        inputs_stone = clip_processor(images=Image.fromarray(cv2.cvtColor(mask_img, cv2.COLOR_BGR2RGB)), return_tensors="pt").to(device)
        outputs_stone = clip_model.get_image_features(**inputs_stone)
        stone_features = outputs_stone.pooler_output if hasattr(outputs_stone, "pooler_output") else (outputs_stone[0] if isinstance(outputs_stone, tuple) else outputs_stone)
        
        # Edge Features
        inputs_edge = clip_processor(images=Image.fromarray(edges_3ch), return_tensors="pt").to(device)
        outputs_edge = clip_model.get_image_features(**inputs_edge)
        edge_features = outputs_edge.pooler_output if hasattr(outputs_edge, "pooler_output") else (outputs_edge[0] if isinstance(outputs_edge, tuple) else outputs_edge)

    combined = torch.cat((stone_features, edge_features), dim=1)
    return combined.cpu().numpy().flatten().astype(np.float32)
@app.post("/search")  # API endpoint for searching rings based on uploaded image
async def search_ring(file: UploadFile = File(...)):
    if len(CATALOG_DATA) == 0:
        return {"error": "Catalog is empty. Run indexing script."}

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # 1. BROAD DETECTION (Lower confidence to find small rings)
    results = yolo_model(img, conf=0.15, verbose=False)
    
    # --- LOGGING FOR DEBUGGING ---
    detected_classes = results[0].boxes.cls.cpu().numpy()
    confidences = results[0].boxes.conf.cpu().numpy()
    print(f"\n[DEBUG] Found {len(detected_classes)} objects: {detected_classes}")
    
    # 2. THE PERSON BLOCKER (Class 0 is 'person')
    # If a person is the main thing in the photo (>40% confidence), REJECT.
    for i, cls in enumerate(detected_classes):
        if int(cls) == 0 and confidences[i] > 0.40:
            print(f"  --> REJECTED: Person detected with {confidences[i]:.2f} confidence.")
            return {"error": "Invalid Image: Person detected. Please photograph only the ring."}

    # 3. MASK / RING VALIDATION
    # If no mask at all, we use the full image for CLIP but check similarity strictly.
    query_vector = get_combined_embedding(img)
    
    results_list = []
    for item in CATALOG_DATA:
        sim = 1 - cosine(query_vector, item["vector"])
        results_list.append({
            "name": str(item["name"]),
            "similarity": round(float(sim) * 100, 1),
            "image_url": f"{BASE_URL}/static_images/{item['name']}"
        })
    
    top_10 = sorted(results_list, key=lambda x: x["similarity"], reverse=True)[:10]
    best_sim = top_10[0]["similarity"]
    print(f"  --> BEST MATCH: {best_sim}%")

    # 4. THE QUALITY GATE
    # If best similarity is very low, it's a random object (table, floor, etc.)
    if best_sim < 38.0:
        return {"error": "No matching ring detected. Try a closer, centered photo."}

    return top_10

@app.get("/get_mask/{image_name}")
async def get_mask(image_name: str):
    img_path = os.path.join(STATIC_IMG_PATH, image_name)
    img = cv2.imread(img_path)
    if img is None: return {"error": "Image not found"}

    results = yolo_model(img, conf=0.15, verbose=False)
    if results[0].masks is not None:
        mask = results[0].masks.data[0].cpu().numpy()
        mask = cv2.resize(mask, (img.shape[1], img.shape[0]))
        mask_uint8 = (mask * 255).astype(np.uint8)

        stone_only = cv2.bitwise_and(img, img, mask=mask_uint8)
        gray_stone = cv2.cvtColor(stone_only, cv2.COLOR_BGR2GRAY)
        
        bgra = cv2.merge([gray_stone, gray_stone, gray_stone, mask_uint8])
        res, im_png = cv2.imencode(".png", bgra)
        return StreamingResponse(io.BytesIO(im_png.tobytes()), media_type="image/png")
    
    return {"error": "No stone detected"}

@app.get("/remove_stone/{image_name}")
async def remove_stone(image_name: str):
    img_path = os.path.join(STATIC_IMG_PATH, image_name)
    img = cv2.imread(img_path)
    if img is None: return {"error": "Image not found"}

    # Convert to Grayscale "Structure"
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    structure_img = cv2.merge([gray, gray, gray])

    # Detect with lower confidence to catch edges
    results = yolo_model(structure_img, conf=0.15, verbose=False)
    
    if results[0].masks is not None:
        mask = results[0].masks.data[0].cpu().numpy()
        mask = cv2.resize(mask, (img.shape[1], img.shape[0]))
        mask_uint8 = (mask * 255).astype(np.uint8)

        # BIGGER DILATION: Use a 25x25 kernel to swallow the edges of the stone
        kernel = np.ones((25, 25), np.uint8)
        mask_expanded = cv2.dilate(mask_uint8, kernel, iterations=1)
        
        # AGGRESSIVE INPAINTING: Using Telea with a radius of 15 for better blending
        empty_setting = cv2.inpaint(structure_img, mask_expanded, 15, cv2.INPAINT_TELEA)

        res, im_png = cv2.imencode(".png", empty_setting)
        return StreamingResponse(io.BytesIO(im_png.tobytes()), media_type="image/png")
    
    res, im_png = cv2.imencode(".png", structure_img)
    return StreamingResponse(io.BytesIO(im_png.tobytes()), media_type="image/png")

if __name__ == "__main__":
    uvicorn.run(app, host="192.168.1.106", port=8004)  # Use your Computer's IP here for mobile testing