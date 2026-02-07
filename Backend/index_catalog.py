import os
import cv2
import numpy as np
import torch
from ultralytics import YOLO
from transformers import CLIPProcessor, CLIPModel
from PIL import Image

# --- Configuration ---
IMG_FOLDER = "Rings/ring/"
SAVE_PATH = "catalog_data.npy"

# --- Load Models ---
print("Loading AI Models for indexing...")
device = "cuda" if torch.cuda.is_available() else "cpu"
# Using the same YOLO model as main.py
yolo_model = YOLO("yolov8m-seg.pt") 
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)
clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

def get_combined_embedding(cv2_img):
    """
    Generates a 1024-dim vector. 
    MUST match the logic in main.py exactly for search to work.
    """
    # 1. YOLO Segmentation for Stone Mask
    results = yolo_model(cv2_img, verbose=False)
    mask_img = cv2_img.copy()
    
    if results[0].masks is not None:
        mask = results[0].masks.data[0].cpu().numpy()
        mask = cv2.resize(mask, (cv2_img.shape[1], cv2_img.shape[0]))
        mask_uint8 = (mask * 255).astype(np.uint8)
        mask_img = cv2.bitwise_and(cv2_img, cv2_img, mask=mask_uint8)

    # 2. Canny Edge Detection (Structure)
    gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    edges_3ch = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)

    # 3. CLIP Encoding
    with torch.no_grad():
        # --- Process Stone Mask ---
        inputs_stone = clip_processor(images=Image.fromarray(cv2.cvtColor(mask_img, cv2.COLOR_BGR2RGB)), return_tensors="pt").to(device)
        outputs_stone = clip_model.get_image_features(**inputs_stone)
        
        # FIX: Extract tensor from BaseModelOutputWithPooling
        if hasattr(outputs_stone, "pooler_output"):
            stone_features = outputs_stone.pooler_output
        elif isinstance(outputs_stone, torch.Tensor):
            stone_features = outputs_stone
        else:
            stone_features = outputs_stone[0] if isinstance(outputs_stone, tuple) else outputs_stone.last_hidden_state[:, 0]

        # --- Process Structural Edges ---
        inputs_edge = clip_processor(images=Image.fromarray(edges_3ch), return_tensors="pt").to(device)
        outputs_edge = clip_model.get_image_features(**inputs_edge)
        
        # FIX: Extract tensor
        if hasattr(outputs_edge, "pooler_output"):
            edge_features = outputs_edge.pooler_output
        elif isinstance(outputs_edge, torch.Tensor):
            edge_features = outputs_edge
        else:
            edge_features = outputs_edge[0]

    # Combine Stone Mask (512) + Structure (512) = 1024 dimensions
    combined = torch.cat((stone_features, edge_features), dim=1)
    
    return combined.cpu().numpy().flatten().astype(np.float32)

def run_indexing():
    catalog_list = []
    if not os.path.exists(IMG_FOLDER):
        print(f"Error: Folder {IMG_FOLDER} not found!")
        return

    images = [f for f in os.listdir(IMG_FOLDER) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    print(f"Found {len(images)} images. Processing...")

    for i, img_name in enumerate(images):
        path = os.path.join(IMG_FOLDER, img_name)
        img = cv2.imread(path)
        
        if img is not None:
            try:
                # Generate the 1024-dim vector
                vector = get_combined_embedding(img)
                catalog_list.append({
                    "name": img_name, 
                    "vector": vector
                })
                
                if (i + 1) % 10 == 0 or (i + 1) == len(images):
                    print(f"Indexed {i + 1}/{len(images)} images...")
                    
            except Exception as e:
                print(f"Failed to process {img_name}: {e}")

    # Save the updated catalog
    np.save(SAVE_PATH, catalog_list)
    print(f"\nSuccess! {SAVE_PATH} updated with 1024-dim features.")
    print("You can now restart main.py to use the new catalog.")

if __name__ == "__main__":
    run_indexing()