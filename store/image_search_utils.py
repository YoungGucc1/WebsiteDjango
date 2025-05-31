import requests
import os
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils.text import slugify
from .models import Product, Image as StoreImage # Renamed to avoid conflict with PIL.Image
from PIL import Image as PILImage # For image processing/validation if needed
from io import BytesIO
from datetime import datetime

# Default search parameters (can be overridden by form)
DEFAULT_IMG_SIZE = "large"
DEFAULT_IMG_TYPE = "photo"
DEFAULT_IMG_COLOR_TYPE = "any"
DEFAULT_FILE_TYPE = "jpg"
DEFAULT_SAFE_SEARCH = "active"

def search_google_images(query, num_results=5, 
                         img_size=DEFAULT_IMG_SIZE, 
                         img_type=DEFAULT_IMG_TYPE, 
                         img_color_type=DEFAULT_IMG_COLOR_TYPE, 
                         file_type=DEFAULT_FILE_TYPE, 
                         safe_search=DEFAULT_SAFE_SEARCH):
    """
    Searches Google Images for a given query and returns a list of image URLs.
    Uses provided parameters or defaults.
    """
    api_key = getattr(settings, 'GOOGLE_API_KEY', None)
    cse_id = getattr(settings, 'GOOGLE_CSE_ID', None)

    if not api_key or not cse_id:
        print("Error: GOOGLE_API_KEY or GOOGLE_CSE_ID not configured in settings.")
        return []

    url = "https://customsearch.googleapis.com/customsearch/v1"
    params = {
        'q': query,
        'cx': cse_id,
        'key': api_key,
        'searchType': 'image',
        'num': num_results,
    }

    # Add filters if they are not "any" or "off" (for safe search)
    # API expects uppercase for imgSize
    if img_size and img_size.lower() != "any": params['imgSize'] = img_size.upper()
    if img_type and img_type.lower() != "any": params['imgType'] = img_type
    if img_color_type and img_color_type.lower() != "any": params['imgColorType'] = img_color_type
    if file_type and file_type.lower() != "any": params['fileType'] = file_type
    if safe_search and safe_search.lower() != "off": params['safe'] = safe_search


    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()  # Raise an exception for HTTP errors
        data = response.json()
        items = data.get('items', [])
        return [item['link'] for item in items if 'link' in item]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching images for '{query}': {e}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred while searching images for '{query}': {e}")
        return []

def save_image_for_product(product: Product, image_url: str, image_index: int):
    """
    Downloads an image from a URL, saves it as a StoreImage object,
    and associates it with the given product.
    Returns the created StoreImage instance or None if failed.
    """
    try:
        response = requests.get(image_url, timeout=15)
        response.raise_for_status()

        # Try to get the original file extension
        original_filename = image_url.split('/')[-1].split('?')[0] # Get filename part
        original_extension = os.path.splitext(original_filename)[1].lower()
        if not original_extension or original_extension not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            # Fallback or determine from content type if possible
            content_type = response.headers.get('content-type')
            if content_type:
                if 'image/jpeg' in content_type: original_extension = '.jpg'
                elif 'image/png' in content_type: original_extension = '.png'
                elif 'image/gif' in content_type: original_extension = '.gif'
                elif 'image/webp' in content_type: original_extension = '.webp'
                else: original_extension = '.jpg' # Default fallback
            else:
                original_extension = '.jpg' # Default fallback

        # Generate a filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_product_name = slugify(product.name)
        filename = f"{safe_product_name}_{image_index + 1}_{timestamp}{original_extension}"

        img_content = ContentFile(response.content, name=filename)
        
        # Create and save the image instance
        store_image = StoreImage(
            name=f"{product.name} Image {image_index + 1}",
            alt_text=f"Image for {product.name}",
            type=StoreImage.ImageType.PRODUCT,
            # is_main can be set based on logic (e.g., first image is main)
            is_main=(image_index == 0 and not product.images.filter(is_main=True).exists()) 
        )
        store_image.file_path.save(filename, img_content, save=True) # save=True will trigger model's save method

        # Add to product's images
        product.images.add(store_image)
        print(f"Successfully saved image '{filename}' for product '{product.name}'")
        return store_image

    except requests.exceptions.Timeout:
        print(f"Timeout downloading image for {product.name} from {image_url}")
    except requests.exceptions.RequestException as e:
        print(f"Error downloading image for {product.name} from {image_url}: {e}")
    except Exception as e:
        print(f"Error saving image for {product.name} from {image_url}: {e}")
    return None

def process_product_image_search(product: Product, 
                                 num_results=3, 
                                 img_size=DEFAULT_IMG_SIZE, 
                                 img_type=DEFAULT_IMG_TYPE, 
                                 img_color_type=DEFAULT_IMG_COLOR_TYPE, 
                                 file_type=DEFAULT_FILE_TYPE, 
                                 safe_search=DEFAULT_SAFE_SEARCH):
    """
    Searches for images for a single product using specified parameters and saves them.
    Returns the number of images successfully saved.
    """
    print(f"Processing product: {product.name} (ID: {product.id}) with search params: "
          f"num_results={num_results}, img_size={img_size}, img_type={img_type}, "
          f"img_color_type={img_color_type}, file_type={file_type}, safe_search={safe_search}")
    
    current_image_count = product.images.count()
    if current_image_count >= num_results:
        print(f"Product '{product.name}' already has {current_image_count} images (target: {num_results}). Skipping.")
        return 0

    # Use product name as the primary query. Could be extended with category, etc.
    query = product.name
    if product.category:
        query = f"{product.name} {product.category.name}"

    image_urls = search_google_images(
        query,
        num_results=num_results - current_image_count, # Only fetch remaining needed
        img_size=img_size,
        img_type=img_type,
        img_color_type=img_color_type,
        file_type=file_type,
        safe_search=safe_search
    )
    
    if not image_urls:
        print(f"No new image URLs found for product '{product.name}' with query '{query}'.")
        return 0

    saved_count = 0
    # Start image_index from current_image_count to avoid overwriting is_main logic if adding to existing
    for i, url in enumerate(image_urls, start=current_image_count): 
        if product.images.count() >= num_results: # Stop if we've reached the desired count
            break
        # Pass current total images count as index for naming and main image logic
        if save_image_for_product(product, url, product.images.count()): 
            saved_count += 1
            
    print(f"Finished processing for product '{product.name}'. Saved {saved_count} new images.")
    return saved_count
